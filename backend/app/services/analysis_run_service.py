from typing import List, Dict, Tuple, Optional, Any
from fastapi import HTTPException
from supabase import Client
from datetime import datetime, timezone
from collections import defaultdict
import uuid

from ..core.supabase import get_supabase_client
from . import profile_service, evidence_service, industry_service, retrieval_service
from . import skill_engine as engine
from .signal_extractor import extract_signals
from .skill_taxonomy import normalize_skill, normalize_skill_slug, get_all_skills
from .evidence.base import EVIDENCE_PIPELINE_VERSION
from .evidence.manager import evidence_manager
from .evidence_weights import ASSESSMENT_SOURCE
from .assessment.service import load_assessment_signals

TABLE_RESULTS = "analysis_results"
TABLE_ASSESSMENTS = "skill_assessments"
TABLE_GAPS = "skill_gaps"
TABLE_SIGNALS = "skill_signals"


def _client() -> Optional[Client]:
    return get_supabase_client()


def _get_skills_lookup(c: Optional[Client]) -> Dict[str, str]:
    """
    Return dictionary mapping skill identifiers (slug, canonical name, display name, lowercase)
    to database UUID or deterministic synthetic UUID.
    """
    lookup: Dict[str, str] = {}
    if c is not None:
        try:
            r = c.table("skills").select("id, canonical_name, display_name").execute()
            for row in (r.data or []):
                sid = row["id"]
                c_name = row.get("canonical_name", "")
                d_name = row.get("display_name", "")
                if c_name:
                    lookup[c_name] = sid
                    lookup[c_name.lower()] = sid
                    lookup[c_name.lower().replace("_", " ")] = sid
                if d_name:
                    lookup[d_name] = sid
                    lookup[d_name.lower()] = sid
            if lookup:
                return lookup
        except Exception:
            pass

    # Fallback: create deterministic UUIDs based on canonical skill catalog
    namespace = uuid.UUID("11111111-1111-1111-1111-111111111111")
    for s in get_all_skills(c):
        sid = str(uuid.uuid5(namespace, s["canonical_name"]))
        lookup[s["canonical_name"]] = sid
        lookup[s["canonical_name"].lower()] = sid
        lookup[s["display_name"]] = sid
        lookup[s["display_name"].lower()] = sid
    return lookup


# ---------------------------------------------------------------------------
# Discrete Orchestration Steps
# ---------------------------------------------------------------------------

def load_profile(user_id: str) -> dict:
    """Load and validate student profile."""
    try:
        profile = profile_service.get_profile(user_id)
    except HTTPException as e:
        if e.status_code == 404:
            raise HTTPException(status_code=400, detail="Profile not found — complete /profile/setup first")
        raise
    if not profile:
        raise HTTPException(status_code=400, detail="Profile not found — complete /profile/setup first")
    return profile


def load_evidence(user_id: str) -> Tuple[List[dict], List[dict], List[dict]]:
    """Load evidence items, projects, and certifications for student."""
    try:
        evidence = evidence_service.list_evidence(user_id)
        projects = evidence_service.list_projects(user_id)
        certs = evidence_service.list_certs(user_id)
        return evidence, projects, certs
    except HTTPException as e:
        if e.status_code == 503:
            raise HTTPException(status_code=503, detail="Evidence tables not configured — run 002_create_evidence.sql")
        raise


def load_industry_requirements(target_role: str) -> List[dict]:
    """Load normalized industry requirements for target role."""
    if not target_role or len(target_role.strip()) < 2:
        raise HTTPException(status_code=400, detail="Target role required")
    try:
        requirements = industry_service.list_by_role(target_role.strip())
        return requirements
    except HTTPException as e:
        if e.status_code == 503:
            raise HTTPException(status_code=503, detail="Industry knowledge not configured — run 003_industry_knowledge.sql")
        raise


def _signal_source(signal: dict) -> str:
    return str(signal.get("source") or signal.get("source_type") or "").strip().lower()


def _signal_strength(signal: dict) -> float:
    try:
        return float(signal.get("signal_strength", signal.get("signal_value", 0.0)) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def evidence_state(evidence_count: int, has_assessment: bool) -> Tuple[str, str]:
    """
    Classify how a skill estimate is supported, so the UI never presents
    artifact evidence as verified proficiency.

      no_evidence        — nothing submitted for this skill
      evidence_estimate  — supporting evidence only (GitHub/projects/documents):
                           the skill may be present, but nothing has validated it
      validated          — a completed INAURA assessment backs the estimate
    """
    if has_assessment:
        return "validated", "Validated by assessment"
    if int(evidence_count or 0) <= 0:
        return "no_evidence", "No evidence"
    return "evidence_estimate", "Evidence-based estimate"


def evidence_state_extended(signals: List[dict], has_assessment: bool) -> Tuple[str, str]:
    """
    Extended evidence labeling for provenance UI.

    Labels:
      No evidence            — no active signals
      Validated by assessment — assessment present (strongest)
      Performance evidence    — only HIGH tier (leetcode/codeforces/kaggle/coursework)
      Mixed evidence          — mix of HIGH + SUPPORTING/MEDIUM
      Evidence-based estimate — only SUPPORTING/MEDIUM/LOW (e.g., GitHub/project/cert/resume)

    Always returns (state_key, display_label).
    """
    if has_assessment:
        return "validated", "Validated by assessment"
    if not signals:
        return "no_evidence", "No evidence"
    # Determine tiers present
    from .evidence_weights import RELIABILITY_TIERS
    high_sources = set(RELIABILITY_TIERS.get("high", []))
    supporting_medium = set(RELIABILITY_TIERS.get("supporting", []) + RELIABILITY_TIERS.get("medium", []))
    low_sources = set(RELIABILITY_TIERS.get("low", []))

    src_types = {str(s.get("source") or s.get("source_type") or "").lower() for s in signals}
    has_high = bool(src_types & high_sources)
    has_supp_med = bool(src_types & supporting_medium)
    has_low = bool(src_types & low_sources)

    if has_high and (has_supp_med or has_low):
        return "mixed_evidence", "Mixed evidence"
    if has_high:
        return "performance_evidence", "Performance evidence"
    # supporting/medium/low only -> evidence-based estimate (covers GitHub, project, cert, resume)
    return "evidence_estimate", "Evidence-based estimate"


def build_evidence_sources(signals: List[dict]) -> List[dict]:
    """
    Structured provenance for a skill's signals.
    Each entry: source_type, source_id, source_label, strength, reliability, details
    For GitHub, preserves all contributing repositories where available.
    """
    sources = []
    for s in signals:
        src_type = str(s.get("source") or s.get("source_type") or "").lower()
        meta = s.get("metadata") or {}
        label = src_type
        details: Dict[str, Any] = {}
        source_url = meta.get("source_url") or s.get("source_url") or ""
        if src_type == "github":
            repo = meta.get("repo") or meta.get("full_name") or meta.get("project_name") or ""
            if not repo and s.get("evidence_id"):
                repo = f"evidence {str(s.get('evidence_id'))[:8]}"
            if meta.get("repo_count"):
                label = f"GitHub \u00b7 {meta.get('repo_count')} repos"
            elif repo:
                label = f"GitHub \u00b7 {repo}"
            else:
                label = "GitHub"
            # Preserve all repositories if available
            details = {k: v for k, v in meta.items() if k in ("project_name", "repo_count", "owned_count", "fork_count", "evidence_depth", "evidence_kinds", "languages", "inspection", "repositories", "owner")}
            if meta.get("repositories"):
                details["repositories"] = meta["repositories"]
            elif meta.get("repo_count"):
                details["repo_count"] = meta["repo_count"]
            if source_url:
                details["source_url"] = source_url
            # Evidence depth
            if meta.get("evidence_depth") is not None:
                details["evidence_depth"] = meta["evidence_depth"]
            if meta.get("project_name"):
                details["project"] = meta["project_name"]
        elif src_type == "project":
            proj_name = meta.get("project_name") or "Project"
            label = f"Project \u00b7 {proj_name}"
            details = {"project_name": proj_name}
            if meta.get("student_contribution"):
                details["contribution"] = meta["student_contribution"]
            if meta.get("evidence_depth") is not None:
                details["evidence_depth"] = meta["evidence_depth"]
            if source_url:
                details["source_url"] = source_url
        elif src_type in ("leetcode", "codeforces", "kaggle"):
            label = f"{src_type.capitalize()} \u00b7 performance"
            details = dict(meta)
            if source_url:
                details["source_url"] = source_url
        elif src_type == "assessment":
            correct = meta.get("correct_count")
            total = meta.get("question_count")
            if correct is not None and total:
                label = f"INAURA Assessment \u00b7 {correct}/{total}"
            else:
                label = "INAURA Assessment"
            details = {
                "assessment_attempt_id": meta.get("assessment_attempt_id"),
                "score": meta.get("assessment_score"),
                "version": meta.get("assessment_version"),
                "completed_at": meta.get("completed_at") or meta.get("source_created_at"),
            }
            if meta.get("evidence_depth") is not None:
                details["evidence_depth"] = meta["evidence_depth"]
        elif src_type in ("certification", "certification_file"):
            label = f"Certification \u00b7 {meta.get('issuing_org') or ''}".strip(" \u00b7")
            details = {"completion_year": meta.get("completion_year"), "issuing_org": meta.get("issuing_org")}
            if source_url:
                details["source_url"] = source_url
        elif src_type in ("resume", "linkedin", "self_declared", "syllabus", "coursework"):
            label = src_type.capitalize() if src_type != "self_declared" else "Self-declared"
            details = dict(meta)
            if source_url:
                details["source_url"] = source_url
        else:
            label = src_type.capitalize()
            details = dict(meta)
            if source_url:
                details["source_url"] = source_url

        strength = float(s.get("signal_strength", s.get("signal_value", 0.0)) or 0.0)
        reliability = float(s.get("source_reliability", 0.5) or 0.5)
        # Preserve timestamps for override supersede logic
        created_at = s.get("source_created_at") or meta.get("source_created_at") or meta.get("completed_at") or ""
        sources.append({
            "source_type": src_type,
            "source_id": s.get("evidence_id") or s.get("project_id") or s.get("certification_id") or meta.get("assessment_attempt_id") or "",
            "source_label": label,
            "source_url": source_url,
            "strength": round(strength, 3),
            "reliability": round(reliability, 3),
            "evidence_depth": meta.get("evidence_depth") if meta.get("evidence_depth") is not None else s.get("depth"),
            "details": details,
            "explanation": s.get("reason") or s.get("explanation", ""),
            "is_ai_assisted": bool(s.get("is_ai_assisted") or meta.get("is_ai_assisted")),
            "source_created_at": created_at,
            "completed_at": meta.get("completed_at") or "",
        })
    return sources


def load_user_overrides(user_id: str, c: Optional[Client]) -> Dict[str, dict]:
    """Load user skill overrides keyed by lowercase canonical skill."""
    if c is None:
        return {}
    try:
        r = c.table("user_skill_overrides").select("*").eq("user_id", user_id).eq("is_zero_override", True).execute()
        out: Dict[str, dict] = {}
        for row in (r.data or []):
            key = str(row.get("skill_key") or row.get("skill_name") or "").lower()
            if key:
                out[key] = row
                # also map by display name lower
                name_key = str(row.get("skill_name") or "").lower()
                out[name_key] = row
        return out
    except Exception:
        return {}


def _compute_github_diagnostics(evidence: List[dict], signals: List[dict]) -> Dict[str, int]:
    """
    Compute diagnostic counts for GitHub repository analysis.
    Returns dict with repositories_discovered, repositories_attempted,
    repositories_successfully_analyzed, repositories_with_evidence,
    repositories_contributing_skills, plus github_candidates_* if available.
    """
    discovered = 0
    attempted = 0
    successfully_analyzed = 0
    with_evidence = 0
    contributing = set()

    # From evidence metadata (profile level)
    for ev in evidence or []:
        if (ev.get("evidence_type") or "").lower() != "github":
            continue
        meta = ev.get("metadata") or {}
        # Try multiple possible locations
        inspection = meta.get("inspection") or meta.get("raw_metadata") or {}
        # Also check nested inspection inside raw_metadata
        if not inspection and isinstance(meta.get("raw_metadata"), dict):
            inspection = meta.get("raw_metadata", {})
        # For profile, repositories are in inspection
        repos = inspection.get("repositories") or meta.get("repositories") or []
        # Also check top-level raw_metadata
        if not repos and isinstance(inspection, dict):
            repos = inspection.get("repositories") or []
        # Count discovered from raw_metadata
        fetched = inspection.get("repositories_fetched") or meta.get("repositories_fetched") or len(repos) if repos else 0
        if fetched:
            discovered += int(fetched)
        else:
            # Fallback: count of repos list
            discovered += len(repos) if isinstance(repos, list) else 0

        # Attempted / successfully analyzed from inspection counts if available
        inspected = inspection.get("repositories_inspected")
        failed = inspection.get("repositories_failed", 0)
        skipped = inspection.get("repositories_skipped", 0)
        if inspected is not None:
            attempted += int(inspected) + int(failed or 0) + int(skipped or 0)
            successfully_analyzed += int(inspected)
            with_evidence += int(inspection.get("repositories_content_analyzed", 0) or 0)
        else:
            # Fallback: count repos with status inspected
            for r in repos if isinstance(repos, list) else []:
                if r.get("status") == "inspected":
                    successfully_analyzed += 1
                    attempted += 1
                elif r.get("status") in ("failed", "skipped", "skipped_low_evidence", "skipped_rate_limited"):
                    attempted += 1

    # Aggregate candidate diagnostics from inspection if present (new validation gate)
    candidates_detected = 0
    candidates_accepted = 0
    candidates_rejected = 0
    for ev in evidence or []:
        if (ev.get("evidence_type") or "").lower() != "github":
            continue
        meta = ev.get("metadata") or {}
        insp = meta.get("inspection") or meta.get("raw_metadata") or {}
        if isinstance(insp, dict):
            if "github_candidates_detected" in insp:
                candidates_detected += int(insp.get("github_candidates_detected") or 0)
                candidates_accepted += int(insp.get("github_candidates_accepted") or 0)
                candidates_rejected += int(insp.get("github_candidates_rejected") or 0)
    # Fallback: if no provider diagnostics yet (old pipeline), compute from signals via validation gate
    if candidates_detected == 0 and signals:
        # Use validator to estimate: total distinct github skills before filtering would be signals + rejected doc-only
        # For old evidence, we can approximate by counting doc-only would-be rejected
        from .evidence.github_validation import validate_aggregated_signal
        # Reconstruct distinct candidates as accepted + would-be rejected doc-only
        # For now, if no diagnostics, set candidates_detected = len github signals before filtering (unknown)
        # Keep as accepted count for backward compat
        candidates_detected = len([s for s in signals if str(s.get("source") or s.get("source_type") or "").lower() == "github"]) + candidates_rejected
        candidates_accepted = len([s for s in signals if str(s.get("source") or s.get("source_type") or "").lower() == "github"])

    # Contributing skills: distinct repos that contributed to at least one signal
    for sig in signals or []:
        src_type = str(sig.get("source") or sig.get("source_type") or "").lower()
        if src_type != "github":
            continue
        meta = sig.get("metadata") or {}
        repos = meta.get("repositories") or []
        if isinstance(repos, list):
            for r in repos:
                full = str(r.get("full_name") or r.get("name") or "").lower()
                if full:
                    contributing.add(full)
        else:
            # Fallback: single repo
            full = str(meta.get("full_name") or meta.get("project_name") or sig.get("evidence_id") or "").lower()
            if full:
                contributing.add(full)

    # If no discovered but signals exist, infer
    if discovered == 0 and (successfully_analyzed > 0 or contributing):
        discovered = max(successfully_analyzed, len(contributing))

    out = {
        "repositories_discovered": int(discovered),
        "repositories_attempted": int(attempted or successfully_analyzed),
        "repositories_successfully_analyzed": int(successfully_analyzed),
        "repositories_with_evidence": int(with_evidence or successfully_analyzed),
        "repositories_contributing_skills": int(len(contributing)),
    }
    if candidates_detected:
        out.update({
            "github_candidates_detected": int(candidates_detected),
            "github_candidates_accepted": int(candidates_accepted),
            "github_candidates_rejected": int(candidates_rejected),
        })
    return out


def _signal_spread(signals: List[dict]) -> float:
    """
    Disagreement between a skill's evidence signals (max - min strength).
    Used to flag conflicting evidence worth resolving with an assessment.
    """
    if len(signals) < 2:
        return 0.0
    strengths = [_signal_strength(s) for s in signals]
    return round(max(strengths) - min(strengths), 4)


def evidence_refresh_state(ev: dict) -> Tuple[bool, bool]:
    """
    Decide whether an evidence item must be inspected before the analysis run.

    Returns (is_unverified, is_stale_pipeline):
      - is_unverified: never inspected, so it carries no signals yet.
      - is_stale_pipeline: verified by an older evidence pipeline, so its
        cached signals predate the current extraction logic and must be
        re-inspected (bypassing the freshness cache) exactly once.
    """
    meta = ev.get("metadata") or {}
    v_status = ev.get("verification_status") or meta.get("verification_status")
    is_unverified = not v_status or v_status == "unverified"
    stored_version = meta.get("evidence_pipeline_version")
    is_stale_pipeline = (not is_unverified) and stored_version != EVIDENCE_PIPELINE_VERSION
    return is_unverified, is_stale_pipeline


def extract_skill_signals(
    evidence: List[dict],
    projects: List[dict],
    certifications: List[dict],
) -> List[dict]:
    """Extract deterministic evidence signals using signal_extractor."""
    return extract_signals(evidence, projects, certifications)


def normalize_signals(signals: List[dict], client: Optional[Client] = None) -> List[dict]:
    """
    Ensure every signal references a canonical skill name and preserves
    core signal attributes: skill, source, signal_strength, source_reliability, reason.
    """
    normalized: List[dict] = []
    for s in signals:
        raw_name = s.get("canonical_name") or s.get("skill") or ""
        canonical = normalize_skill(raw_name, client) or raw_name
        slug = normalize_skill_slug(raw_name, client) or canonical.lower().replace(" ", "_")
        normalized.append({
            **s,
            "skill": canonical,
            "canonical_name": canonical,
            "canonical_slug": slug,
        })
    return normalized


def aggregate_skills(signals: List[dict]) -> Dict[str, List[dict]]:
    """Group signals by canonical skill name."""
    grouped: Dict[str, List[dict]] = defaultdict(list)
    for s in signals:
        key = s.get("canonical_name") or s.get("skill") or ""
        grouped[key].append(s)
    return dict(grouped)


def build_requirements_map(requirements: List[dict], client: Optional[Client] = None) -> Dict[str, dict]:
    """
    Build canonical lookup map of target role requirements.
    Preserves separate dimensions: required_level, importance, demand, interview_relevance, industry_confidence.
    """
    req_map: Dict[str, dict] = {}
    for req in requirements:
        raw_skill = req.get("skill", "")
        canonical = normalize_skill(raw_skill, client) or raw_skill
        importance = float(req.get("importance", 0.5))
        required_level = float(req.get("required_level", req.get("importance", 0.75)))
        demand = float(req.get("demand", 0.5))
        interview = float(req.get("interview_relevance", 0.5))
        industry_confidence = float(req.get("industry_confidence", 0.85))

        req_map[canonical] = {
            "skill": canonical,
            "category": req.get("skill_category", "General"),
            "required_level": required_level,
            "importance": importance,
            "demand": demand,
            "interview": interview,
            "interview_relevance": interview,
            "industry_confidence": industry_confidence,
            "description": req.get("description", ""),
            "source": req.get("source", "Industry requirements"),
            "source_url": req.get("source_url", ""),
            "source_version": req.get("source_version") or req.get("version", ""),
            "source_reference": req.get("source_reference", ""),
            "source_occupation": req.get("source_occupation", ""),
            "mapping_version": req.get("mapping_version", ""),
            "retrieved_at": req.get("retrieved_at", ""),
            "role_relevance": req.get("role_relevance", "CORE" if importance >= 0.80 else ("IMPORTANT" if importance >= 0.70 else "RELEVANT")),
            "evidence_context": req.get("evidence_context", ""),
        }
    return req_map


def extract_dsa_topic_gaps(evidence: List[dict], signals: List[dict]) -> List[dict]:
    """
    Extract domain-specific topic coverage gaps across the 9 canonical DSA pillars.
    Surfaces weak (< 5 problems or weak status) and unpracticed (0 problems) pillars
    from LeetCode/Codeforces verification inspection.
    """
    topic_meta = None
    # 1. Inspect DSA signals first
    for s in signals:
        canon = (s.get("canonical_name") or s.get("skill") or "").strip()
        if canon in ("Data Structures & Algorithms", "Data Structures and Algorithms"):
            m = s.get("metadata") or {}
            if m.get("pillar_breakdown") or m.get("weak_topics") or m.get("missing_topics"):
                topic_meta = m
                break

    # 2. Inspect evidence items if not in signals
    if not topic_meta:
        for ev in evidence:
            if ev.get("evidence_type") == "leetcode":
                m = ev.get("metadata") or {}
                insp = m.get("inspection") or {}
                tc = insp.get("topic_coverage") or m.get("topic_coverage")
                if tc and isinstance(tc, dict):
                    topic_meta = tc
                    break

    if not topic_meta:
        return []

    pillar_breakdown = topic_meta.get("pillar_breakdown") or {}
    missing_pillars = list(topic_meta.get("missing_topics") or topic_meta.get("missing_pillars") or [])
    weak_pillars = list(topic_meta.get("weak_topics") or topic_meta.get("weak_pillars") or [])

    advanced_pillars = {"Dynamic Programming", "Graphs", "Trees", "Backtracking"}
    topic_gaps: List[dict] = []

    if pillar_breakdown:
        for pillar, data in pillar_breakdown.items():
            solved = int(data.get("solved", 0))
            status = str(data.get("status", "missing")).lower()
            if status in ("missing", "weak") or solved < 5:
                is_adv = pillar in advanced_pillars
                imp = 0.95 if is_adv else 0.75
                category = "critical" if (is_adv and (status == "missing" or solved == 0)) else "high"
                advice = (
                    f"Practice 5-10 canonical {pillar} interview patterns (e.g. recursion, memoization, BFS/DFS)."
                    if is_adv
                    else f"Solve 5 canonical problems in {pillar} to build algorithmic fluency."
                )
                topic_gaps.append({
                    "pillar": pillar,
                    "skill": "Data Structures & Algorithms",
                    "status": status,
                    "solved": solved,
                    "gap_type": "coverage_gap",
                    "priority_category": category,
                    "importance": imp,
                    "explanation": engine.explain_coverage_gap(pillar, solved, status, advice),
                    "actionable_advice": advice,
                })
    else:
        for p in missing_pillars:
            is_adv = p in advanced_pillars
            advice = f"Begin with fundamental easy and medium problems in {p}."
            topic_gaps.append({
                "pillar": p,
                "skill": "Data Structures & Algorithms",
                "status": "missing",
                "solved": 0,
                "gap_type": "coverage_gap",
                "priority_category": "critical" if is_adv else "high",
                "importance": 0.95 if is_adv else 0.75,
                "explanation": engine.explain_coverage_gap(p, 0, "missing", advice),
                "actionable_advice": advice,
            })
        for p in weak_pillars:
            is_adv = p in advanced_pillars
            advice = f"Expand problem diversity and attempt medium challenges in {p}."
            topic_gaps.append({
                "pillar": p,
                "skill": "Data Structures & Algorithms",
                "status": "weak",
                "solved": 3,
                "gap_type": "coverage_gap",
                "priority_category": "high" if is_adv else "medium",
                "importance": 0.90 if is_adv else 0.70,
                "explanation": engine.explain_coverage_gap(p, 3, "weak", advice),
                "actionable_advice": advice,
            })

    # Critical first, then advanced pillars
    topic_gaps.sort(key=lambda x: (x["priority_category"] != "critical", x["pillar"] not in advanced_pillars))
    return topic_gaps


def extract_strengths(assessments: List[dict]) -> List[dict]:
    """
    Extract student strengths.
    A strength is identified ONLY when:
    1. Proficiency meets or exceeds required_level (or >= 0.60 if elective)
    2. Evidence confidence is reasonable (>= 0.35)
    3. Evidence count > 0 (not missing evidence)
    4. Gap <= 1e-9
    """
    strengths = []
    for a in assessments:
        if a.get("is_missing_evidence", False):
            continue
        prof = float(a.get("proficiency", 0.0))
        conf = float(a.get("confidence", 0.0))
        gap_val = float(a.get("gap", 0.0))
        req = float(a.get("required_level", 0.50))
        ev_count = int(a.get("evidence_count", 0))

        if gap_val <= 1e-9 and prof >= min(req, 0.60) and conf >= 0.35 and ev_count > 0:
            strengths.append({
                "skill": a["canonical_name"],
                "display_name": a.get("display_name", a["canonical_name"]),
                "category": a.get("category", "General"),
                "proficiency": prof,
                "confidence": conf,
                "required_level": req,
                "evidence_count": ev_count,
                "explanation": a.get("explanation", ""),
                "quadrant": a.get("quadrant", "strong_validated"),
                "quadrant_title": a.get("quadrant_title", "Strong & Validated"),
            })
    strengths.sort(key=lambda x: (x["proficiency"], x["confidence"]), reverse=True)
    return strengths


def calculate_assessments(
    grouped_signals: Dict[str, List[dict]],
    requirements_map: Dict[str, dict],
    client: Optional[Client] = None,
    overrides: Optional[Dict[str, dict]] = None,
) -> List[dict]:
    """
    Calculate skill assessments for all required skills plus any additional evidenced skills.
    Ethical Missing Evidence Handling:
    When a skill is required by the role but the student has no supporting signals,
    INAURA marks:
      proficiency = 0.0
      evidence_count = 0
      confidence = 0.0
      gap = required_level
      gap_type = 'evidence_gap'
      explanation explicitly notes: 'No evidence found' != 'Student is definitely incapable'.
    HARD RULE: If there is no active supporting evidence (signals empty and no assessment),
               current_proficiency = 0, confidence = 0, gap = required_level, state = no_evidence.
               The industry required value must never be used as current proficiency.
    Overrides: user zero-override forces effective proficiency to 0 until new assessment.
    """
    overrides = overrides or {}
    assessments: List[dict] = []
    assessed_keys = set()

    # 1. Process evidenced skills that match requirements or are extra
    for skill_name, sigs in grouped_signals.items():
        assessed_keys.add(skill_name.lower())
        assessed_keys.add(normalize_skill(skill_name, client) or skill_name)

        # Proficiency includes the unvalidated-evidence prior: while nothing has
        # directly validated the skill, a high artifact-only estimate is shrunk
        # toward "not yet validated" (one-sided — it can never raise an estimate).
        orig_prof, ev_weight, ev_count, _, prior_applied = engine.proficiency_with_prior(sigs)
        diversity = len(set(s.get("source", s.get("source_type", "")) for s in sigs))
        # Confidence now also accounts for how directly the strongest evidence
        # demonstrates the person's own ability (assessment > platform > artifact).
        orig_conf, _, _, validation = engine.confidence_from_signals(sigs)

        # Separate the evidence-based estimate from the assessment-validated
        # result so both can be shown and compared.
        assessment_sigs = [s for s in sigs if _signal_source(s) == ASSESSMENT_SOURCE]
        evidence_sigs = [s for s in sigs if _signal_source(s) != ASSESSMENT_SOURCE]
        # The evidence-only estimate is by definition unvalidated, so it carries
        # the prior too — this is the number the UI labels "Evidence-based estimate".
        evidence_prof, _, evidence_count_only, _, _ = engine.proficiency_with_prior(evidence_sigs)
        assessment_score = (
            max(float(s.get("signal_strength", s.get("signal_value", 0.0)) or 0.0) for s in assessment_sigs)
            if assessment_sigs else None
        )
        assessment_meta = (assessment_sigs[0].get("metadata") or {}) if assessment_sigs else {}
        signal_spread = _signal_spread(sigs)

        # Lookup role requirement if applicable
        req = requirements_map.get(skill_name)
        if not req:
            norm_name = normalize_skill(skill_name, client)
            if norm_name:
                req = requirements_map.get(norm_name)

        if req:
            required_level = req["required_level"]
            importance = req["importance"]
            demand = req["demand"]
            interview = req["interview"]
            category = req["category"]
            industry_confidence = req.get("industry_confidence", 0.85)
            evidence_context = req.get("evidence_context", "")
            source = req.get("source", "Industry requirements")
            requirement_source = req.get("source", "")
            requirement_source_url = req.get("source_url", "")
            requirement_source_version = req.get("source_version", "")
            requirement_source_reference = req.get("source_reference", "")
            requirement_role_relevance = req.get("role_relevance", "")
            requirement_description = req.get("description", "")
            is_portfolio = False
        else:
            # Skill demonstrated but not explicitly required in target role
            required_level = 0.50
            importance = 0.30
            demand = 0.30
            interview = 0.30
            category = "Additional Demonstrated Skill"
            industry_confidence = 0.85
            evidence_context = "Elective demonstrated competency outside core requirements."
            source = "Demonstrated Evidence"
            requirement_source = "Demonstrated Evidence"
            requirement_source_url = ""
            requirement_source_version = ""
            requirement_source_reference = ""
            requirement_role_relevance = "OPTIONAL"
            requirement_description = ""
            is_portfolio = True

        # --- Provenance & evidence state (extended) ---
        evidence_sources = build_evidence_sources(sigs)
        state_key, state_label = evidence_state_extended(sigs, bool(assessment_sigs))

        # --- HARD RULE & timestamp-aware override handling ---
        override_key = (normalize_skill_slug(skill_name, client) or skill_name.lower())
        override = overrides.get(override_key) or overrides.get(skill_name.lower())
        is_overridden = False
        override_dt = None
        if override:
            # Parse override creation time
            try:
                ot_str = override.get("created_at") or override.get("updated_at") or ""
                if ot_str:
                    override_dt = datetime.fromisoformat(str(ot_str).replace("Z", "+00:00"))
                    if override_dt.tzinfo is None:
                        override_dt = override_dt.replace(tzinfo=timezone.utc)
            except Exception:
                override_dt = None
            # Determine newest evidence/assessment time for this skill
            newest_dt = None
            for s in sigs:
                meta = s.get("metadata") or {}
                # Assessment: completed_at, else evidence: source_created_at
                t_str = meta.get("completed_at") or meta.get("source_created_at") or s.get("source_created_at") or meta.get("source_created_at") or ""
                if not t_str:
                    # Fallback to signal's evidence created_at if present else treat as old
                    t_str = s.get("source_created_at") or ""
                if t_str:
                    try:
                        dt = datetime.fromisoformat(str(t_str).replace("Z", "+00:00"))
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        if newest_dt is None or dt > newest_dt:
                            newest_dt = dt
                    except Exception:
                        continue
            # If newest evidence is after override, override is superseded (new evidence)
            # If newest is None or <= override_dt, override remains active
            if newest_dt and override_dt and newest_dt > override_dt:
                is_overridden = False
            elif override_dt:
                is_overridden = True
            else:
                # No timestamp available -> conservative: treat as overridden
                is_overridden = True

        if is_overridden:
            # User explicitly said "I don't know this yet" — force 0 even after prior assessment
            # Historical assessment and evidence remain but are suppressed for active calculation
            original_prof = orig_prof
            original_conf = orig_conf
            prof = 0.0
            conf = 0.0
            ev_weight_effective = 0.0
            ev_count_effective = 0
            diversity_effective = 0.0
            validation_effective = 0.0
            evidence_state_key = "user_override"
            evidence_state_label = "User marked as not known"
            gap_val = engine.gap(prof, required_level)
            gap_type = "evidence_gap"
            for src in evidence_sources:
                src["is_overridden"] = True
        else:
            # No active override -> normal hard rule handling
            if ev_count == 0 and not assessment_sigs:
                prof = 0.0
                conf = 0.0
                gap_val = engine.gap(0.0, required_level)
                gap_type = "evidence_gap"
                evidence_state_key = "no_evidence"
                evidence_state_label = "No evidence"
                ev_weight_effective = 0.0
                ev_count_effective = 0
                diversity_effective = 0.0
                validation_effective = 0.0
                original_prof = orig_prof
                original_conf = orig_conf
            else:
                prof = orig_prof
                conf = orig_conf
                gap_val = engine.gap(prof, required_level)
                gap_type = "evidence_gap" if (ev_count == 0 or conf < 0.20) else "skill_gap"
                evidence_state_key = state_key
                evidence_state_label = state_label
                ev_weight_effective = ev_weight
                ev_count_effective = ev_count
                diversity_effective = float(diversity)
                validation_effective = validation
                original_prof = orig_prof
                original_conf = orig_conf

        if gap_type == "evidence_gap":
            advice = f"Submit a GitHub project repository, coding profile, or certification demonstrating {skill_name}."
        elif gap_val > 0.0:
            advice = f"Work on projects and technical challenges applying {skill_name} to close the {int(round(gap_val*100))}% gap."
        else:
            advice = f"Maintain fluency and showcase {skill_name} in technical interview demonstrations."

        priority_score, priority_category, breakdown = engine.calculate_prioritized_gap(
            gap_val=gap_val,
            importance=importance,
            demand=demand,
            student_confidence=conf,
            interview_relevance=interview,
            industry_confidence=industry_confidence,
            gap_type=gap_type,
        )
        quadrant_key, quadrant_title, quadrant_guidance = engine.classify_skill_quadrant(prof, conf)
        legacy_priority = engine.gap_priority(gap_val, importance, demand, conf, interview)

        explanation = engine.explain_proficiency(
            proficiency_val=prof,
            confidence_val=conf,
            evidence_count=ev_count_effective,
            source_diversity=int(diversity_effective) if isinstance(diversity_effective, (int, float)) else 0,
            signals=sigs if not (is_overridden and not assessment_sigs) else [],
            skill_name=skill_name,
        )

        assessments.append({
            "canonical_name": skill_name,
            "display_name": skill_name,
            "skill": skill_name,
            "category": category,
            "proficiency": prof,
            "confidence": conf,
            "evidence_weight": ev_weight_effective,
            "source_diversity": float(diversity_effective),
            "evidence_count": ev_count_effective,
            "explanation": explanation,
            "required_level": required_level,
            "gap": gap_val,
            "importance": importance,
            "demand": demand,
            "interview": interview,
            "interview_relevance": interview,
            "industry_confidence": industry_confidence,
            "evidence_context": evidence_context,
            "source": source,
            "requirement_source": requirement_source,
            "requirement_source_url": requirement_source_url,
            "requirement_source_version": requirement_source_version,
            "requirement_source_reference": requirement_source_reference,
            "requirement_role_relevance": requirement_role_relevance,
            "requirement_description": requirement_description,
            "priority": priority_score,
            "priority_score": priority_score,
            "legacy_priority": legacy_priority,
            "priority_category": priority_category,
            "gap_type": gap_type,
            "actionable_advice": advice,
            "quadrant": quadrant_key,
            "quadrant_title": quadrant_title,
            "quadrant_guidance": quadrant_guidance,
            "signals": sigs,
            "is_missing_evidence": ev_count_effective == 0 and not bool(assessment_sigs),
            # Assessment layer (evidence estimate vs direct validation)
            "evidence_proficiency": evidence_prof,
            "evidence_signal_count": evidence_count_only,
            "assessment_score": assessment_score,
            "has_assessment": bool(assessment_sigs),
            "assessment_attempt_id": assessment_meta.get("assessment_attempt_id"),
            "assessment_version": assessment_meta.get("assessment_version"),
            "validation_strength": validation_effective,
            "signal_spread": signal_spread,
            "evidence_state": evidence_state_key,
            "evidence_state_label": evidence_state_label,
            "unvalidated_prior_applied": prior_applied,
            # Provenance & personalization
            "evidence_sources": evidence_sources,
            "is_portfolio": is_portfolio,
            "is_overridden": is_overridden,
            "original_proficiency": original_prof,
            "original_confidence": original_conf,
        })

    # 2. Process required skills that have NO evidence (Missing Skills)
    for req_skill, req in requirements_map.items():
        if req_skill.lower() in assessed_keys or req_skill in assessed_keys:
            continue

        required_level = req["required_level"]
        importance = req["importance"]
        demand = req["demand"]
        interview = req["interview"]
        category = req["category"]
        industry_confidence = req.get("industry_confidence", 0.85)
        evidence_context = req.get("evidence_context", "")
        source = req.get("source", "Industry requirements")
        requirement_source = req.get("source", "")
        requirement_source_url = req.get("source_url", "")
        requirement_source_version = req.get("source_version", "")
        requirement_source_reference = req.get("source_reference", "")
        requirement_role_relevance = req.get("role_relevance", "")
        requirement_description = req.get("description", "")

        prof = 0.0
        conf = 0.0
        ev_weight = 0.0
        ev_count = 0
        diversity = 0
        gap_val = engine.gap(prof, required_level)
        gap_type = "evidence_gap"
        advice = f"Submit an evidence artifact (e.g. GitHub repository, technical project, or certification) demonstrating practical capability in {req_skill}."

        priority_score, priority_category, breakdown = engine.calculate_prioritized_gap(
            gap_val=gap_val,
            importance=importance,
            demand=demand,
            student_confidence=0.0,
            interview_relevance=interview,
            industry_confidence=industry_confidence,
            gap_type="evidence_gap",
        )
        legacy_priority = engine.gap_priority(gap_val, importance, demand, 0.0, interview)
        quadrant_key, quadrant_title, quadrant_guidance = engine.classify_skill_quadrant(0.0, 0.0)

        explanation = engine.explain_proficiency(
            proficiency_val=0.0,
            confidence_val=0.0,
            evidence_count=0,
            source_diversity=0,
            signals=[],
            skill_name=req_skill,
        )

        # Check override for missing skills (override on zero is redundant but preserve)
        override_key = (normalize_skill_slug(req_skill, client) or req_skill.lower())
        override_row = overrides.get(override_key) or overrides.get(req_skill.lower())
        is_overridden_missing = bool(override_row)
        # For missing skills, override remains active (no new evidence), so show user_override state if overridden
        missing_state = "user_override" if is_overridden_missing else "no_evidence"
        missing_label = "User marked as not known" if is_overridden_missing else "No evidence"

        assessments.append({
            "canonical_name": req_skill,
            "display_name": req_skill,
            "skill": req_skill,
            "category": category,
            "proficiency": 0.0,
            "confidence": 0.0,
            "evidence_weight": 0.0,
            "source_diversity": 0.0,
            "evidence_count": 0,
            "explanation": explanation,
            "required_level": required_level,
            "gap": gap_val,
            "importance": importance,
            "demand": demand,
            "interview": interview,
            "interview_relevance": interview,
            "industry_confidence": industry_confidence,
            "evidence_context": evidence_context,
            "source": source,
            "priority": priority_score,
            "priority_score": priority_score,
            "legacy_priority": legacy_priority,
            "priority_category": priority_category,
            "gap_type": gap_type,
            "actionable_advice": advice,
            "quadrant": quadrant_key,
            "quadrant_title": quadrant_title,
            "quadrant_guidance": quadrant_guidance,
            "signals": [],
            "is_missing_evidence": True,
            "evidence_proficiency": 0.0,
            "evidence_signal_count": 0,
            "assessment_score": None,
            "has_assessment": False,
            "assessment_attempt_id": None,
            "assessment_version": None,
            "validation_strength": 0.0,
            "signal_spread": 0.0,
            "evidence_state": missing_state,
            "evidence_state_label": missing_label,
            "unvalidated_prior_applied": False,
            "evidence_sources": [],
            "is_portfolio": False,
            "is_overridden": is_overridden_missing,
            "original_proficiency": 0.0,
            "original_confidence": 0.0,
            "requirement_source": requirement_source,
            "requirement_source_url": requirement_source_url,
            "requirement_source_version": requirement_source_version,
            "requirement_source_reference": requirement_source_reference,
            "requirement_role_relevance": requirement_role_relevance,
            "requirement_description": requirement_description,
        })

    return assessments


def calculate_gaps(assessments: List[dict], target_role: str) -> List[dict]:
    """
    Calculate prioritized skill gaps from assessments.
    Sorted by priority score descending.
    """
    gaps: List[dict] = []
    for a in assessments:
        skill = a.get("canonical_name", a.get("skill", "Unknown"))
        prof = float(a.get("proficiency", 0.0))
        req = float(a.get("required_level", prof + float(a.get("gap", 0.0))))
        gap_val = float(a.get("gap", max(0.0, req - prof)))
        importance = float(a.get("importance", 0.5))
        demand = float(a.get("demand", 0.5))
        interview = float(a.get("interview_relevance", a.get("interview", 0.5)))
        conf = float(a.get("confidence", 0.0))
        priority = float(a.get("priority_score", a.get("priority", 0.0)))
        priority_category = a.get("priority_category", "medium")
        gap_type = a.get("gap_type", "skill_gap")
        advice = a.get("actionable_advice", "")
        industry_confidence = float(a.get("industry_confidence", 0.85))
        evidence_context = a.get("evidence_context", "")


        if gap_type == "evidence_gap":
            gap_explanation = engine.explain_evidence_gap(
                skill=skill,
                required_level=req,
                importance=importance,
                actionable_advice=advice,
            )
        else:
            gap_explanation = engine.explain_gap(
                skill=skill,
                current=prof,
                required=req,
                gap_val=gap_val,
                importance=importance,
                confidence_val=conf,
                evidence_count=a["evidence_count"],
            )

        gaps.append({
            "canonical_name": skill,
            "skill": skill,
            "target_role": target_role,
            "required_level": req,
            "current_proficiency": prof,
            "confidence": conf,
            "gap": gap_val,
            "importance": importance,
            "demand": demand,
            "interview_relevance": interview,
            "industry_confidence": industry_confidence,
            "priority": priority,
            "priority_score": priority,
            "priority_category": priority_category,
            "gap_type": gap_type,
            "actionable_advice": advice,
            "evidence_context": evidence_context,
            "source": a.get("source", "Industry requirements"),
            "requirement_source": a.get("requirement_source", a.get("source", "")),
            "requirement_source_url": a.get("requirement_source_url", a.get("source_url", "")),
            "requirement_source_version": a.get("requirement_source_version", ""),
            "requirement_source_reference": a.get("requirement_source_reference", ""),
            "requirement_role_relevance": a.get("requirement_role_relevance", ""),
            "requirement_description": a.get("requirement_description", ""),
            "quadrant": a.get("quadrant", "exploratory"),
            "quadrant_title": a.get("quadrant_title", "Exploratory / Unclear"),
            "explanation": gap_explanation,
            "skills": {
                "canonical_name": skill,
                "display_name": a.get("display_name", skill),
                "category": a.get("category", "General"),
            },
            # Provenance & personalization fields for frontend
            "evidence_sources": a.get("evidence_sources", []),
            "evidence_state": a.get("evidence_state", "no_evidence"),
            "evidence_state_label": a.get("evidence_state_label", "No evidence"),
            "is_portfolio": bool(a.get("is_portfolio", False)),
            "is_overridden": bool(a.get("is_overridden", False)),
            "has_assessment": bool(a.get("has_assessment", False)),
            "assessment_score": a.get("assessment_score"),
            "evidence_count": int(a.get("evidence_count", 0)),
            "source_diversity": float(a.get("source_diversity", 0)),
        })

    # Sort gaps by priority descending
    gaps.sort(key=lambda x: x["priority_score"], reverse=True)
    return gaps


def calculate_readiness(
    assessments: List[dict],
    requirements: List[dict],
    gaps: List[dict],
) -> dict:
    """Calculate skill, industry, and evidence components of overall readiness.
    Portfolio-only skills are excluded from readiness so they cannot inflate
    target-role readiness. Only target-role assessments (is_portfolio==False)
    contribute to skill and evidence components.
    """
    target_assessments = [a for a in assessments if not a.get("is_portfolio")]
    # If no target assessments (edge), fall back to all to avoid divide by zero
    if not target_assessments:
        target_assessments = assessments
    target_gaps = [g for g in gaps if not g.get("is_portfolio")]
    if not target_gaps:
        target_gaps = gaps
    skill_comp = engine.aggregate_skill_component(target_assessments, requirements)
    industry_comp = engine.aggregate_industry_component(target_gaps)
    evidence_comp = engine.aggregate_evidence_component(target_assessments)
    readiness_score = engine.readiness(skill_comp, industry_comp, evidence_comp)
    explanation = engine.explain_readiness(skill_comp, industry_comp, evidence_comp, readiness_score)

    return {
        "readiness_score": readiness_score,
        "skill_component": skill_comp,
        "industry_component": industry_comp,
        "evidence_component": evidence_comp,
        "explanation": explanation,
    }


def persist_analysis(
    user_id: str,
    target_role: str,
    readiness_data: dict,
    assessments: List[dict],
    gaps: List[dict],
    signals: List[dict],
    skills_map: Dict[str, str],
    c: Optional[Client],
    strengths: Optional[List[dict]] = None,
    topic_gaps: Optional[List[dict]] = None,
    github_diagnostics: Optional[Dict[str, int]] = None,
) -> str:
    """Persist analysis run results and records to Supabase tables."""
    now = datetime.now(timezone.utc).isoformat()
    analysis_id = str(uuid.uuid4())

    if c is None:
        return analysis_id

    # 1. Deduplicate previous skill signals and assessments for this user to avoid duplication on re-runs
    try:
        c.table(TABLE_SIGNALS).delete().eq("user_id", user_id).execute()
    except Exception:
        pass
    try:
        c.table(TABLE_ASSESSMENTS).delete().eq("user_id", user_id).execute()
    except Exception:
        pass

    # 2. Persist analysis_results (Historical Snapshot)
    result_data = {
        "id": analysis_id,
        "user_id": user_id,
        "target_role": target_role,
        "skill_component": readiness_data["skill_component"],
        "industry_component": readiness_data["industry_component"],
        "evidence_component": readiness_data["evidence_component"],
        "readiness_score": readiness_data["readiness_score"],
        "assessment_count": len(assessments),
        "gap_count": len([g for g in gaps if g["gap"] > 0]),
        "engine_version": engine.ENGINE_VERSION,
        "readiness_explanation": readiness_data.get("explanation", ""),
        "industry_confidence": readiness_data.get("industry_confidence", 0.85),
        "metadata": {
            "strengths_count": len(strengths or []),
            "priority_breakdown": {
                "critical": len([g for g in gaps if g.get("priority_category") == "critical"]),
                "high": len([g for g in gaps if g.get("priority_category") == "high"]),
                "medium": len([g for g in gaps if g.get("priority_category") == "medium"]),
                "low": len([g for g in gaps if g.get("priority_category") == "low"]),
                "covered": len([g for g in gaps if g.get("priority_category") == "covered"]),
            },
            "topic_gaps_count": len(topic_gaps or []),
            "github_diagnostics": github_diagnostics or {},
        },
        "created_at": now,
        "updated_at": now,
    }
    try:
        r = c.table(TABLE_RESULTS).insert(result_data).execute()
        if r.data and len(r.data) > 0:
            analysis_id = r.data[0]["id"]
    except Exception as e:
        msg = str(e).lower()
        if "could not find the table" in msg or "pgrst205" in msg:
            raise HTTPException(status_code=503, detail="Analysis tables not found — run 005_skill_engine.sql")
        if "permission denied" in msg:
            raise HTTPException(status_code=503, detail="Database permission denied for analysis_results")
        # Graceful fallback without 011 migration columns if DB is pre-011
        try:
            baseline_result = {
                "id": analysis_id,
                "user_id": user_id,
                "target_role": target_role,
                "skill_component": readiness_data["skill_component"],
                "industry_component": readiness_data["industry_component"],
                "evidence_component": readiness_data["evidence_component"],
                "readiness_score": readiness_data["readiness_score"],
                "assessment_count": len(assessments),
                "gap_count": len([g for g in gaps if g["gap"] > 0]),
                "engine_version": engine.ENGINE_VERSION,
                "created_at": now,
                "updated_at": now,
            }
            c.table(TABLE_RESULTS).insert(baseline_result).execute()
        except Exception:
            pass

    # 3. Persist skill_assessments
    for a in assessments:
        skill_id = skills_map.get(a["canonical_name"]) or skills_map.get(a["canonical_name"].lower())
        if not skill_id:
            continue
        row = {
            "user_id": user_id,
            "skill_id": skill_id,
            "proficiency": a["proficiency"],
            "confidence": a["confidence"],
            "evidence_weight": a["evidence_weight"],
            "source_diversity": a["source_diversity"],
            "evidence_count": a["evidence_count"],
            "explanation": a["explanation"],
        }
        # Assessment layer columns (012 migration) — persisted separately so a
        # pre-012 database still records the baseline row.
        enriched = {
            **row,
            "evidence_proficiency": a.get("evidence_proficiency"),
            "assessment_score": a.get("assessment_score"),
            "validation_strength": a.get("validation_strength"),
            "has_assessment": bool(a.get("has_assessment")),
            "metadata": {
                "signal_spread": a.get("signal_spread", 0.0),
                "assessment_attempt_id": a.get("assessment_attempt_id"),
                "assessment_version": a.get("assessment_version"),
                "gap_type": a.get("gap_type"),
                "quadrant": a.get("quadrant"),
                "evidence_state": a.get("evidence_state"),
                "evidence_state_label": a.get("evidence_state_label"),
                "unvalidated_prior_applied": bool(a.get("unvalidated_prior_applied")),
                "evidence_sources": a.get("evidence_sources", []),
                "is_portfolio": bool(a.get("is_portfolio")),
                "is_overridden": bool(a.get("is_overridden")),
                "original_proficiency": a.get("original_proficiency"),
                "original_confidence": a.get("original_confidence"),
            },
        }
        try:
            c.table(TABLE_ASSESSMENTS).insert(enriched).execute()
        except Exception:
            try:
                c.table(TABLE_ASSESSMENTS).insert(row).execute()
            except Exception:
                pass

    # 4. Persist skill_gaps
    for g in gaps:
        skill_id = skills_map.get(g["canonical_name"]) or skills_map.get(g["canonical_name"].lower())
        if not skill_id:
            continue
        row = {
            "user_id": user_id,
            "analysis_result_id": analysis_id,
            "skill_id": skill_id,
            "target_role": target_role,
            "required_level": g["required_level"],
            "current_proficiency": g["current_proficiency"],
            "confidence": g["confidence"],
            "gap": g["gap"],
            "importance": g["importance"],
            "demand": g["demand"],
            "interview_relevance": g["interview_relevance"],
            "priority_score": g["priority_score"],
            "explanation": g["explanation"],
            "gap_type": g.get("gap_type", "skill_gap"),
            "priority_category": g.get("priority_category", "medium"),
            "industry_confidence": g.get("industry_confidence", 0.85),
            "evidence_context": g.get("evidence_context", ""),
            "actionable_advice": g.get("actionable_advice", ""),
        }
        try:
            c.table(TABLE_GAPS).insert(row).execute()
        except Exception:
            # Fallback to pre-011 baseline columns if migration not applied
            try:
                baseline_gap = {
                    "user_id": user_id,
                    "analysis_result_id": analysis_id,
                    "skill_id": skill_id,
                    "target_role": target_role,
                    "required_level": g["required_level"],
                    "current_proficiency": g["current_proficiency"],
                    "confidence": g["confidence"],
                    "gap": g["gap"],
                    "importance": g["importance"],
                    "demand": g["demand"],
                    "interview_relevance": g["interview_relevance"],
                    "priority_score": g["priority_score"],
                    "explanation": g["explanation"],
                }
                c.table(TABLE_GAPS).insert(baseline_gap).execute()
            except Exception:
                pass

    # 5. Persist skill_signals
    for sig in signals:
        canonical_name = sig.get("canonical_name", sig.get("skill", ""))
        skill_id = skills_map.get(canonical_name) or skills_map.get(canonical_name.lower())
        if not skill_id:
            continue
        row = {
            "user_id": user_id,
            "skill_id": skill_id,
            "evidence_id": sig.get("evidence_id"),
            "project_id": sig.get("project_id"),
            "certification_id": sig.get("certification_id"),
            "source_type": sig.get("source_type", sig.get("source", "evidence")),
            "signal_value": sig.get("signal_value", sig.get("signal_strength", 0.5)),
            "source_reliability": sig.get("source_reliability", 0.5),
            "explanation": sig.get("explanation", sig.get("reason", "")),
            "metadata": sig.get("metadata", {}),
        }
        try:
            c.table(TABLE_SIGNALS).insert(row).execute()
        except Exception:
            pass

    # 6. Update user analysis state
    try:
        from .analysis_service import upsert_state
        retr = {
            "role": target_role,
            "count": len(gaps),
            "note": "retrieved via analysis execution",
        }
        upsert_state(user_id, target_role, "completed", retr)
    except Exception:
        pass

    return analysis_id


# ---------------------------------------------------------------------------
# Main Analysis Pipeline Orchestrator
# ---------------------------------------------------------------------------

async def run_analysis(user_id: str, target_role: str) -> dict:
    """
    Deterministic Analysis Pipeline Orchestrator:
    Profile -> Evidence -> Signals -> Canonical Skills -> Skill Assessments
    -> Industry Requirements -> Skill Gaps -> Readiness -> Persist.
    """
    c = _client()

    # 1. Load profile & validate
    profile = load_profile(user_id)

    # 2. Load evidence
    evidence, projects, certs = load_evidence(user_id)

    # 2b. Best-effort backfill: parse legacy resume/syllabus uploads that
    # have no parsed_text yet so they still contribute skill signals.
    try:
        evidence_service.ensure_file_evidence_parsed(user_id, evidence)
    except Exception:
        pass

    # Auto-verify evidence items where an inspector is available (e.g. GitHub,
    # LeetCode, Codeforces, Kaggle). Items verified by an older evidence
    # pipeline are re-inspected once so the live run always uses signals from
    # the current extraction logic (e.g. deep GitHub repository evidence)
    # instead of previously cached shallow signals.
    for ev in evidence:
        is_unverified, is_stale_pipeline = evidence_refresh_state(ev)
        if is_unverified or is_stale_pipeline:
            ev_id = ev.get("id")
            if ev_id:
                provider = evidence_manager.get_provider(ev)
                if provider:
                    try:
                        verified_item = await evidence_service.verify_evidence_item(
                            user_id, ev_id, force_refresh=is_stale_pipeline
                        )
                        ev.update(verified_item)
                    except Exception:
                        pass

    # 3. Load industry requirements
    requirements = load_industry_requirements(target_role)

    # 4. Extract raw evidence signals
    raw_signals = extract_skill_signals(evidence, projects, certs)

    # 4a. Apply per-repository personalization (each GitHub repo independent)
    try:
        repo_settings = evidence_service.get_github_repo_settings_map(user_id)
        if repo_settings:
            raw_signals = evidence_service.adjust_github_signals_for_repo_settings(raw_signals, repo_settings)
    except Exception:
        pass

    # 4b. Add INAURA assessment evidence (VERY HIGH reliability, direct
    # validation). Missing or unavailable assessments simply contribute
    # nothing — analysis never depends on them.
    raw_signals.extend(load_assessment_signals(user_id))

    # 4c. Diagnostic counts for GitHub pipeline verification
    try:
        github_diagnostics = _compute_github_diagnostics(evidence, raw_signals)
    except Exception:
        github_diagnostics = {
            "repositories_discovered": 0,
            "repositories_attempted": 0,
            "repositories_successfully_analyzed": 0,
            "repositories_with_evidence": 0,
            "repositories_contributing_skills": 0,
        }

    # 5. Normalize signals through canonical taxonomy
    signals = normalize_signals(raw_signals, c)

    # 6. Group signals by canonical skill
    grouped_signals = aggregate_skills(signals)

    # 7. Map industry requirements to canonical keys
    req_map = build_requirements_map(requirements, c)

    # 7b. Load user overrides (downward personalization)
    try:
        overrides = load_user_overrides(user_id, c)
    except Exception:
        overrides = {}

    # 8. Calculate skill assessments (including missing skills with 0 evidence)
    assessments = calculate_assessments(grouped_signals, req_map, c, overrides=overrides)

    # 9. Calculate prioritized skill gaps
    gaps = calculate_gaps(assessments, target_role)

    # 10. Extract domain coverage topic gaps (e.g. DSA pillars) and verified strengths
    topic_gaps = extract_dsa_topic_gaps(evidence, signals)
    strengths = extract_strengths(assessments)

    # 11. Calculate confidence-aware quadrant summary
    quadrant_summary = {
        "strong_validated": [a["canonical_name"] for a in assessments if a.get("quadrant") == "strong_validated"],
        "unverified_claim": [a["canonical_name"] for a in assessments if a.get("quadrant") == "unverified_claim"],
        "confirmed_gap": [a["canonical_name"] for a in assessments if a.get("quadrant") == "confirmed_gap"],
        "exploratory": [a["canonical_name"] for a in assessments if a.get("quadrant") == "exploratory"],
    }

    # 12. Calculate career readiness score and components
    readiness_result = calculate_readiness(assessments, requirements, gaps)

    # 13. Persist analysis records (Snapshot preservation & signal deduplication)
    skills_map = _get_skills_lookup(c)
    now_iso = datetime.now(timezone.utc).isoformat()
    analysis_id = persist_analysis(
        user_id=user_id,
        target_role=target_role,
        readiness_data=readiness_result,
        assessments=assessments,
        gaps=gaps,
        signals=signals,
        skills_map=skills_map,
        c=c,
        strengths=strengths,
        topic_gaps=topic_gaps,
        github_diagnostics=github_diagnostics,
    )

    # 14. Return structured, versioned result matching frontend and API expectations
    return {
        "id": analysis_id,
        "user_id": user_id,
        "target_role": target_role,
        "readiness_score": readiness_result["readiness_score"],
        "skill_component": readiness_result["skill_component"],
        "industry_component": readiness_result["industry_component"],
        "evidence_component": readiness_result["evidence_component"],
        "readiness_explanation": readiness_result["explanation"],
        "disclaimer": "Career readiness represents alignment with target role benchmarks based on submitted evidence, not a statistical hiring probability or guarantee of placement.",
        "assessment_count": len(assessments),
        "gap_count": len([g for g in gaps if g["gap"] > 0]),
        "engine_version": engine.ENGINE_VERSION,
        "strengths": strengths,
        "priority_gaps": [g for g in gaps if g["gap"] > 0 and g.get("priority_category") in ("critical", "high")],
        "evidence_gaps": [g for g in gaps if g.get("gap_type") == "evidence_gap"],
        "topic_gaps": topic_gaps,
        "quadrant_summary": quadrant_summary,
        "assessments": [
            {
                "skill": a["canonical_name"],
                "display_name": a["display_name"],
                "category": a.get("category", "General"),
                "proficiency": a["proficiency"],
                "confidence": a["confidence"],
                "required_level": a["required_level"],
                "gap": a["gap"],
                "importance": a["importance"],
                "demand": a["demand"],
                "interview_relevance": a["interview_relevance"],
                "industry_confidence": a.get("industry_confidence", 0.85),
                "priority": a["priority"],
                "priority_score": a["priority_score"],
                "priority_category": a.get("priority_category", "medium"),
                "gap_type": a.get("gap_type", "skill_gap"),
                "actionable_advice": a.get("actionable_advice", ""),
                "quadrant": a.get("quadrant", "exploratory"),
                "quadrant_title": a.get("quadrant_title", "Exploratory / Unclear"),
                "evidence_count": a["evidence_count"],
                "source_diversity": a["source_diversity"],
                "explanation": a["explanation"],
                "is_missing_evidence": a.get("is_missing_evidence", False),
                # Assessment layer: evidence-only estimate vs direct validation
                "evidence_proficiency": a.get("evidence_proficiency", 0.0),
                "assessment_score": a.get("assessment_score"),
                "has_assessment": bool(a.get("has_assessment")),
                "validation_strength": a.get("validation_strength", 0.0),
                "signal_spread": a.get("signal_spread", 0.0),
                "evidence_state": a.get("evidence_state", "no_evidence"),
                "evidence_state_label": a.get("evidence_state_label", "No evidence"),
                "unvalidated_prior_applied": bool(a.get("unvalidated_prior_applied")),
                # Provenance & personalization
                "evidence_sources": a.get("evidence_sources", []),
                "is_portfolio": bool(a.get("is_portfolio", False)),
                "is_overridden": bool(a.get("is_overridden", False)),
                "original_proficiency": a.get("original_proficiency", a["proficiency"]),
                "original_confidence": a.get("original_confidence", a["confidence"]),
            }
            for a in sorted(assessments, key=lambda x: x["priority"], reverse=True)
        ],
        "gaps": sorted(gaps, key=lambda x: x["priority_score"], reverse=True),
        # Target-role vs portfolio separation (frontend uses these)
        "target_role_gaps": [g for g in sorted(gaps, key=lambda x: x["priority_score"], reverse=True) if not g.get("is_portfolio")],
        "portfolio_gaps": [g for g in sorted(gaps, key=lambda x: x["priority_score"], reverse=True) if g.get("is_portfolio")],
        "target_role_assessments": [a for a in sorted(assessments, key=lambda x: x["priority"], reverse=True) if not a.get("is_portfolio")],
        "portfolio_assessments": [a for a in sorted(assessments, key=lambda x: x["priority"], reverse=True) if a.get("is_portfolio")],
        "github_diagnostics": github_diagnostics,
        "created_at": now_iso,
    }
