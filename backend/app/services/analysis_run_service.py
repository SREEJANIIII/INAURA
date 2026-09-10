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
from .evidence.manager import evidence_manager

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
    """
    assessments: List[dict] = []
    assessed_keys = set()

    # 1. Process evidenced skills that match requirements or are extra
    for skill_name, sigs in grouped_signals.items():
        assessed_keys.add(skill_name.lower())
        assessed_keys.add(normalize_skill(skill_name, client) or skill_name)

        prof, ev_weight, ev_count, _ = engine.proficiency(sigs)
        diversity = len(set(s.get("source", s.get("source_type", "")) for s in sigs))
        conf, _, _ = engine.confidence(ev_weight, diversity)

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

        gap_val = engine.gap(prof, required_level)
        gap_type = "evidence_gap" if (ev_count == 0 or conf < 0.20) else "skill_gap"

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
            evidence_count=ev_count,
            source_diversity=diversity,
            signals=sigs,
            skill_name=skill_name,
        )

        assessments.append({
            "canonical_name": skill_name,
            "display_name": skill_name,
            "skill": skill_name,
            "category": category,
            "proficiency": prof,
            "confidence": conf,
            "evidence_weight": ev_weight,
            "source_diversity": float(diversity),
            "evidence_count": ev_count,
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
            "signals": sigs,
            "is_missing_evidence": False,
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
            "quadrant": a.get("quadrant", "exploratory"),
            "quadrant_title": a.get("quadrant_title", "Exploratory / Unclear"),
            "explanation": gap_explanation,
            "skills": {
                "canonical_name": skill,
                "display_name": a.get("display_name", skill),
                "category": a.get("category", "General"),
            },
        })

    # Sort gaps by priority descending
    gaps.sort(key=lambda x: x["priority_score"], reverse=True)
    return gaps


def calculate_readiness(
    assessments: List[dict],
    requirements: List[dict],
    gaps: List[dict],
) -> dict:
    """Calculate skill, industry, and evidence components of overall readiness."""
    skill_comp = engine.aggregate_skill_component(assessments, requirements)
    industry_comp = engine.aggregate_industry_component(gaps)
    evidence_comp = engine.aggregate_evidence_component(assessments)
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
) -> str:
    """Persist analysis run results and records to Supabase tables."""
    now = datetime.now(timezone.utc).isoformat()
    analysis_id = str(uuid.uuid4())

    if c is None:
        return analysis_id

    # 1. Deduplicate previous skill signals for this user to avoid signal duplication on re-runs
    try:
        c.table(TABLE_SIGNALS).delete().eq("user_id", user_id).execute()
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

    # Auto-verify unverified evidence items where an inspector is available (e.g. GitHub, LeetCode, Codeforces, Kaggle)
    for ev in evidence:
        meta = ev.get("metadata") or {}
        v_status = ev.get("verification_status") or meta.get("verification_status")
        if not v_status or v_status == "unverified":
            ev_id = ev.get("id")
            if ev_id:
                provider = evidence_manager.get_provider(ev)
                if provider:
                    try:
                        verified_item = await evidence_service.verify_evidence_item(user_id, ev_id)
                        ev.update(verified_item)
                    except Exception:
                        pass

    # 3. Load industry requirements
    requirements = load_industry_requirements(target_role)

    # 4. Extract raw evidence signals
    raw_signals = extract_skill_signals(evidence, projects, certs)

    # 5. Normalize signals through canonical taxonomy
    signals = normalize_signals(raw_signals, c)

    # 6. Group signals by canonical skill
    grouped_signals = aggregate_skills(signals)

    # 7. Map industry requirements to canonical keys
    req_map = build_requirements_map(requirements, c)

    # 8. Calculate skill assessments (including missing skills with 0 evidence)
    assessments = calculate_assessments(grouped_signals, req_map, c)

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
            }
            for a in sorted(assessments, key=lambda x: x["priority"], reverse=True)
        ],
        "gaps": sorted(gaps, key=lambda x: x["priority_score"], reverse=True),
        "created_at": now_iso,
    }
