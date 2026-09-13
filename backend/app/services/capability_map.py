"""
Skill Capability Map (core INAURA feature, deterministic — no LLM required).

For every important skill required by a target role, explains:
  1. WHAT THE INDUSTRY EXPECTS (from industry requirements + RAG evidence)
  2. WHAT THE STUDENT SHOULD BE ABLE TO DO (observable abilities)
  3. WHAT INAURA ALREADY KNOWS (demonstrated capabilities + evidence)
  4. WHAT IS STILL MISSING (gaps, priorities, next actions)

Architecture (reuses the existing INAURA flow, duplicates nothing):

  Industry Role -> Industry Requirements / RAG -> Canonical Skill
      -> Skill Capability Definition -> Student Evidence (grouped signals)
      -> Deterministic Comparison -> Capability Map

Skill vs capability (kept strictly separate):
  Skill       = a technology in the canonical taxonomy (e.g. Python).
  Capability  = something observable a candidate can DO with it
                (e.g. build REST APIs, write automated tests).

A student can therefore show strong Python proficiency while a specific
async capability stays weak — the map reports both honestly.

Anti-fabrication rules:
- Capability vocabulary comes from the curated blueprints below (product
  content, versioned here — same standing as roadmap_catalog templates).
- Industry expectations are attached ONLY from real requirement rows and
  real supporting chunks. Without an industry requirement or without a
  blueprint, the skill is marked `insufficient_industry_data` and NO
  capabilities are invented to fill the UI.
- Demonstrated capabilities require matching signal evidence; a README
  mention (depth 1) never satisfies a rule that needs implementation.
- Absence of evidence is reported as `evidence_gap`, never as proof the
  student lacks the capability — unless implementation-level evidence for
  the skill exists while the specific capability is unmet (`skill_gap`).

Scores here NEVER enter proficiency, confidence, readiness, or gap math:
priority reuse calls skill_engine.calculate_prioritized_gap for ranking
only, exactly as the gap engine does for gaps.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

from ..core.supabase import get_supabase_client
from . import analysis_run_service as ars
from . import analysis_service
from . import skill_engine as engine
from .roadmap_catalog import get_resources_for_skill, get_template_for_skill
from .skill_taxonomy import normalize_skill, normalize_skill_slug


# ---------------------------------------------------------------------------
# Matching engine (deterministic; reads grouped signals only, writes nothing)
# ---------------------------------------------------------------------------

def _canon(name: Any) -> str:
    """Canonical display name for matching (falls back to stripped raw)."""
    text = str(name or "").strip()
    if not text:
        return ""
    try:
        return normalize_skill(text) or text
    except Exception:
        return text


def _signal_depth(sig: Dict[str, Any]) -> int:
    try:
        return int(sig.get("depth", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _signal_source(sig: Dict[str, Any]) -> str:
    return str(sig.get("source") or sig.get("source_type") or "").strip().lower()


def _signal_files(sig: Dict[str, Any]) -> List[str]:
    meta = sig.get("metadata") or {}
    files = meta.get("relevant_files") or []
    if not isinstance(files, list):
        return []
    return [str(f) for f in files if str(f or "").strip()][:5]


def _signal_patterns(sig: Dict[str, Any]) -> List[str]:
    meta = sig.get("metadata") or {}
    patterns = meta.get("detected_usage_patterns") or []
    if isinstance(patterns, dict):
        return sorted(str(p) for p in patterns.keys())
    if isinstance(patterns, (list, tuple, set)):
        return sorted(str(p) for p in patterns)
    return []


def _provenance_entry(sig: Dict[str, Any]) -> Dict[str, Any]:
    """Compact, path-only provenance for one signal (no source contents)."""
    meta = sig.get("metadata") or {}
    repo = (
        meta.get("project_name")
        or meta.get("full_name")
        or meta.get("repo")
        or ""
    )
    reason = str(sig.get("reason") or sig.get("explanation") or "")[:300]
    return {
        "provider": _signal_source(sig) or "evidence",
        "repository": str(repo),
        "files": _signal_files(sig),
        "depth": _signal_depth(sig),
        "reason": reason,
    }


def _dedupe_evidence(entries: List[Dict[str, Any]], limit: int = 8) -> List[Dict[str, Any]]:
    seen = set()
    out = []
    for entry in entries:
        key = (entry.get("provider"), entry.get("repository"),
               tuple(entry.get("files") or []), entry.get("depth"))
        if key in seen:
            continue
        seen.add(key)
        out.append(entry)
        if len(out) >= limit:
            break
    return out


def _rule_matches(rule: Dict[str, Any], grouped: Dict[str, List[dict]]) -> Tuple[bool, List[Dict[str, Any]]]:
    """Evaluate one evidence rule. Returns (matched, provenance entries)."""
    kind = str(rule.get("kind") or "")
    if kind == "signal":
        skill = _canon(rule.get("skill", ""))
        candidates = grouped.get(skill, [])
        try:
            min_depth = int(rule.get("min_depth", 0) or 0)
        except (TypeError, ValueError):
            min_depth = 0
        sources = {str(s).strip().lower() for s in (rule.get("sources") or []) if str(s or "").strip()}
        usage_in = {str(s).strip().lower() for s in (rule.get("usage_in") or []) if str(s or "").strip()}
        try:
            min_files = int(rule.get("min_files", 0) or 0)
        except (TypeError, ValueError):
            min_files = 0
        matched = [
            s for s in candidates
            if _signal_depth(s) >= min_depth
            and (not sources or _signal_source(s) in sources)
            and (not usage_in or str((s.get("metadata") or {}).get("usage_status") or "").lower() in usage_in)
        ]
        if min_files:
            total_files = sum(len(_signal_files(s)) for s in matched)
            if total_files < min_files:
                return False, []
        if not matched:
            return False, []
        return True, _dedupe_evidence([_provenance_entry(s) for s in matched])
    if kind == "patterns":
        skill = _canon(rule.get("skill", ""))
        wanted = {str(p) for p in (rule.get("any_of") or [])}
        hits = []
        for sig in grouped.get(skill, []):
            found = set(_signal_patterns(sig)) & wanted
            if found:
                entry = _provenance_entry(sig)
                entry["patterns"] = sorted(found)
                hits.append(entry)
        if not hits:
            return False, []
        return True, _dedupe_evidence(hits)
    if kind == "files":
        skill = _canon(rule.get("skill", ""))
        try:
            min_count = int(rule.get("min_count", 1) or 1)
        except (TypeError, ValueError):
            min_count = 1
        files: List[str] = []
        entries: List[Dict[str, Any]] = []
        for sig in grouped.get(skill, []):
            for f in _signal_files(sig):
                if f not in files:
                    files.append(f)
            entries.append(_provenance_entry(sig))
            if len(files) >= min_count and len(entries) >= 3:
                break
        if len(files) < min_count:
            return False, []
        return True, _dedupe_evidence(entries)
    if kind == "related_present":
        skills = [_canon(s) for s in (rule.get("skills") or [])]
        skills = [s for s in skills if s]
        entries = []
        for skill in skills:
            for sig in grouped.get(skill, [])[:2]:
                entries.append(_provenance_entry(sig))
            if entries:
                break
        if not entries:
            return False, []
        return True, _dedupe_evidence(entries)
    return False, []


def evaluate_capability(
    capability: Dict[str, Any],
    grouped: Dict[str, List[dict]],
) -> Dict[str, Any]:
    """
    Score one capability against grouped student signals.
    Returns {support [0..1], demonstrated bool, evidence [...]}.
    support = matched rule weight / total rule weight (rounded to 3).
    demonstrated = support >= 0.75. A README mention (depth 1) can never
    satisfy a rule requiring implementation depth.
    """
    rules = capability.get("evidence_rules") or []
    total = 0.0
    matched_weight = 0.0
    evidence: List[Dict[str, Any]] = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        try:
            weight = float(rule.get("weight", 1.0) or 0.0)
        except (TypeError, ValueError):
            weight = 0.0
        if weight <= 0:
            continue
        total += weight
        try:
            matched, entries = _rule_matches(rule, grouped)
        except Exception:
            matched, entries = False, []
        if matched:
            matched_weight += weight
            evidence.extend(entries)
    support = round(matched_weight / total, 3) if total > 0 else 0.0
    return {
        "support": support,
        "demonstrated": support >= DEMONSTRATED_SUPPORT,
        "evidence": _dedupe_evidence(evidence),
    }


def _has_implementation(signals: List[dict]) -> bool:
    """Any implementation-level (depth >= 3) signal for the skill itself."""
    return any(_signal_depth(s) >= 3 for s in (signals or []))


def get_capability_blueprint(skill: Any) -> List[Dict[str, Any]]:
    """Curated capability definitions for a canonical skill (slug or name)."""
    text = str(skill or "").strip()
    if not text:
        return []
    try:
        slug = normalize_skill_slug(text) or ""
    except Exception:
        slug = ""
    if slug and slug in CAPABILITY_BLUEPRINTS:
        return CAPABILITY_BLUEPRINTS[slug]
    lowered = text.lower().replace(" ", "_")
    return CAPABILITY_BLUEPRINTS.get(lowered, [])


def validate_blueprints() -> List[str]:
    """
    Audit the curated catalog. Returns error strings (empty = valid):
    unique ids, non-empty titles/abilities, well-formed rules, and every
    referenced skill resolvable through the canonical taxonomy.
    """
    errors: List[str] = []
    seen_ids = set()
    for slug, capabilities in CAPABILITY_BLUEPRINTS.items():
        if normalize_skill(slug) is None and slug not in (
                (normalize_skill_slug(slug) or ""),):
            # slug keys must themselves be canonical slugs
            pass
        if not isinstance(capabilities, list) or not capabilities:
            errors.append(f"{slug}: no capabilities defined")
            continue
        for cap in capabilities:
            cap_id = str(cap.get("id") or "")
            if not cap_id:
                errors.append(f"{slug}: capability missing id")
                continue
            if cap_id in seen_ids:
                errors.append(f"{slug}: duplicate capability id '{cap_id}'")
            seen_ids.add(cap_id)
            if not str(cap.get("title") or "").strip():
                errors.append(f"{cap_id}: missing title")
            if not [a for a in (cap.get("observable_abilities") or []) if str(a).strip()]:
                errors.append(f"{cap_id}: no observable abilities")
            if not str(cap.get("action") or "").strip():
                errors.append(f"{cap_id}: missing next action")
            for rule in (cap.get("evidence_rules") or []):
                if not isinstance(rule, dict) or rule.get("kind") not in (
                        "signal", "patterns", "files", "related_present"):
                    errors.append(f"{cap_id}: malformed evidence rule {rule!r}")
                    continue
                for skill_ref in ([rule.get("skill")] if rule.get("skill")
                                  else list(rule.get("skills") or [])):
                    if skill_ref and normalize_skill(str(skill_ref)) is None:
                        errors.append(
                            f"{cap_id}: rule references unknown skill '{skill_ref}'")
    return errors


def _capability_relevance(capability: Dict[str, Any], requirement: Dict[str, Any],
                          role: str) -> List[str]:
    """Why this capability is expected for the role (deterministic)."""
    reasons: List[str] = []
    try:
        required_level = float(requirement.get("required_level", 0.0) or 0.0)
    except (TypeError, ValueError):
        required_level = 0.0
    try:
        interview = float(requirement.get("interview_relevance", 0.0) or 0.0)
    except (TypeError, ValueError):
        interview = 0.0
    if required_level >= 0.80:
        reasons.append(f"core requirement (level {required_level:.2f})")
    if interview >= 0.80:
        reasons.append("interview-critical")
    if str(requirement.get("role_relevance") or "").upper() == "CORE":
        reasons.append(f"core for {role}")
    return reasons[:3]


def _chunk_topics_for_skill(requirement: Dict[str, Any]) -> List[str]:
    """Chunk topics backing this requirement (references only, capped)."""
    topics: List[str] = []
    for chunk in (requirement.get("supporting_chunks") or []):
        if not isinstance(chunk, dict):
            continue
        topic = str(chunk.get("topic") or "").strip()
        if topic and topic not in topics:
            topics.append(topic)
        if len(topics) >= 2:
            break
    return topics


def _next_actions(capability: Dict[str, Any], canonical_skill: str) -> Tuple[List[str], List[Dict[str, str]]]:
    """Deterministic next actions: curated action + roadmap catalog template
    steps + catalog resources. No separate roadmap engine is created."""
    actions: List[str] = []
    curated = str(capability.get("action") or "").strip()
    if curated:
        actions.append(curated)
    try:
        template = get_template_for_skill(canonical_skill) or {}
    except Exception:
        template = {}
    for slot in ("practice", "project"):
        try:
            step = str(template.get(slot) or "").strip()
        except AttributeError:
            step = ""
        if step and step not in actions:
            actions.append(f"{slot.capitalize()}: {step}")
    resources: List[Dict[str, str]] = []
    try:
        for res in (get_resources_for_skill(canonical_skill) or [])[:2]:
            if not isinstance(res, dict):
                continue
            title = str(res.get("title") or "").strip()
            url = str(res.get("url") or "").strip()
            if title and url:
                resources.append({
                    "title": title,
                    "url": url,
                    "provider": str(res.get("provider") or ""),
                })
    except Exception:
        pass
    return actions[:3], resources


def build_skill_capability(
    role: str,
    requirement: Optional[Dict[str, Any]],
    grouped: Dict[str, List[dict]],
    assessment: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Build the capability map for one required skill. Pure function of
    (requirement, grouped signals, assessment): no I/O, no scoring changes.
    Assessment contributes proficiency/confidence context only.
    """
    assessment = assessment or {}
    skill = str((requirement or {}).get("skill") or assessment.get("canonical_name")
                or assessment.get("skill") or "").strip()
    canonical = _canon(skill) or skill
    try:
        slug = normalize_skill_slug(canonical) or canonical.lower().replace(" ", "_")
    except Exception:
        slug = canonical.lower().replace(" ", "_")

    try:
        proficiency = float(assessment.get("proficiency", 0.0) or 0.0)
    except (TypeError, ValueError):
        proficiency = 0.0
    try:
        confidence = float(assessment.get("confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0

    base: Dict[str, Any] = {
        "skill": canonical or skill,
        "slug": slug,
        "role": role,
        "proficiency": proficiency,
        "confidence": confidence,
        "required_level": 0.0,
        "importance": 0.0,
        "status": STATUS_INSUFFICIENT_DATA,
        "priority": 0.0,
        "priority_category": "covered",
        "industry_expectations": [],
        "capabilities": [],
        "demonstrated_capabilities": [],
        "missing_capabilities": [],
        "evidence_gap": [],
        "skill_gap": [],
        "evidence_sources": [],
        "requirement": {},
        "explanation": "",
    }

    if not requirement:
        base["explanation"] = (
            f"No industry requirement for {canonical or skill} under role '{role}': "
            "INAURA cannot define expected capabilities without industry evidence."
        )
        return base
    blueprint = get_capability_blueprint(slug) or get_capability_blueprint(canonical)
    if not blueprint:
        base.update(_requirement_context(requirement, role))
        base["explanation"] = (
            f"INAURA has no capability definition for {canonical}: industry "
            "expectations are not invented to fill the UI."
        )
        return base

    base.update(_requirement_context(requirement, role))
    try:
        importance = float(requirement.get("importance", 0.5) or 0.5)
    except (TypeError, ValueError):
        importance = 0.5
    try:
        demand = float(requirement.get("demand", 0.5) or 0.5)
    except (TypeError, ValueError):
        demand = 0.5
    try:
        interview = float(requirement.get("interview_relevance", 0.5) or 0.5)
    except (TypeError, ValueError):
        interview = 0.5
    try:
        industry_confidence = float(requirement.get("industry_confidence", 0.85) or 0.85)
    except (TypeError, ValueError):
        industry_confidence = 0.85

    skill_signals = grouped.get(canonical, [])
    if not skill_signals:
        for key, sigs in grouped.items():
            if _canon(key) == canonical:
                skill_signals = sigs
                break
    has_impl = _has_implementation(skill_signals)

    # Industry expectations: every blueprint capability annotated with why
    # the role expects it, plus requirement + chunk provenance.
    chunk_topics = _chunk_topics_for_skill(requirement)
    expectations = []
    for cap in blueprint:
        relevance = _capability_relevance(cap, requirement, role)
        for topic in chunk_topics:
            marker = f"highlighted in {topic}"
            if marker not in relevance and len(relevance) < 3:
                relevance.append(marker)
        expectations.append({
            "capability_id": cap.get("id"),
            "title": cap.get("title"),
            "detail": cap.get("summary"),
            "relevance": relevance,
        })

    capabilities_out = []
    demonstrated_out = []
    missing_out = []
    evidence_gap_titles: List[str] = []
    skill_gap_titles: List[str] = []
    best_priority = 0.0
    best_category = "covered"

    for cap in blueprint:
        evaluated = evaluate_capability(cap, grouped)
        support = evaluated["support"]
        entry = {
            "id": cap.get("id"),
            "title": cap.get("title"),
            "summary": cap.get("summary"),
            "observable_abilities": list(cap.get("observable_abilities") or []),
            "related_skills": list(cap.get("related_skills") or []),
            "support": support,
            "evidence": evaluated["evidence"],
        }
        capabilities_out.append(entry)
        if evaluated["demonstrated"]:
            strengths = [float(s.get("signal_strength", s.get("signal_value", 0.0)) or 0.0)
                         for s in _signals_for_evidence(grouped, cap, evaluated["evidence"])]
            cap_conf = round(max(strengths) if strengths else support, 3)
            demonstrated_out.append({
                "id": cap.get("id"),
                "title": cap.get("title"),
                "support": support,
                "confidence": cap_conf,
                "evidence": evaluated["evidence"],
            })
            continue
        gap_kind = STATUS_SKILL_GAP if has_impl else STATUS_EVIDENCE_GAP
        status = STATUS_DEVELOPING if support > 0 else gap_kind
        priority, category, _breakdown = engine.calculate_prioritized_gap(
            gap_val=round(1.0 - support, 3),
            importance=importance,
            demand=demand,
            student_confidence=confidence,
            interview_relevance=interview,
            industry_confidence=industry_confidence,
            gap_type=gap_kind,
        )
        actions, resources = _next_actions(cap, canonical)
        missing_out.append({
            "id": cap.get("id"),
            "title": cap.get("title"),
            "support": support,
            "status": status,
            "priority": priority,
            "priority_category": category,
            "next_actions": actions,
            "resources": resources,
            "evidence": evaluated["evidence"],
        })
        if status == STATUS_SKILL_GAP:
            skill_gap_titles.append(str(cap.get("title")))
        elif status == STATUS_EVIDENCE_GAP:
            evidence_gap_titles.append(str(cap.get("title")))
        # developing capabilities are partial, not gaps: listed in
        # missing_capabilities with support > 0, in neither gap list.
        if priority > best_priority:
            best_priority = priority
            best_category = category

    # Skill-level evidence provenance across the skill's own signals.
    evidence_sources = _dedupe_evidence(
        [_provenance_entry(s) for s in skill_signals]
    )[:10]

    if str(requirement.get("evidence_strength") or "").lower() == "insufficient":
        status = STATUS_INDUSTRY_GAP
        explanation = (
            f"Industry evidence for {canonical} under role '{role}' is too thin "
            "to set firm expectations; shown capabilities use cautious baselines."
        )
    elif len(demonstrated_out) == len(blueprint):
        status = STATUS_DEMONSTRATED
        explanation = (
            f"All {len(blueprint)} expected {canonical} capabilities are demonstrated."
        )
    elif demonstrated_out or any(c["support"] > 0 for c in capabilities_out):
        status = STATUS_DEVELOPING
        explanation = (
            f"{len(demonstrated_out)} of {len(blueprint)} expected {canonical} "
            "capabilities demonstrated; the rest are developing or missing."
        )
    elif skill_gap_titles:
        status = STATUS_SKILL_GAP
        explanation = (
            f"INAURA sees {canonical} implementation evidence but not the expected "
            "capabilities listed below."
        )
    else:
        status = STATUS_EVIDENCE_GAP
        explanation = (
            f"No evidence found for the expected {canonical} capabilities. Note: "
            "this indicates absence of submitted evidence, not confirmed inability."
        )

    base.update({
        "industry_expectations": expectations,
        "capabilities": capabilities_out,
        "demonstrated_capabilities": demonstrated_out,
        "missing_capabilities": missing_out,
        "evidence_gap": evidence_gap_titles,
        "skill_gap": skill_gap_titles,
        "evidence_sources": evidence_sources,
        "status": status,
        "priority": best_priority,
        "priority_category": best_category,
        "explanation": explanation,
    })
    return base


def _requirement_context(requirement: Dict[str, Any], role: str) -> Dict[str, Any]:
    """Shared requirement-derived fields (provenance for 'why required')."""
    try:
        required_level = float(requirement.get("required_level", 0.0) or 0.0)
    except (TypeError, ValueError):
        required_level = 0.0
    try:
        importance = float(requirement.get("importance", 0.0) or 0.0)
    except (TypeError, ValueError):
        importance = 0.0
    chunks = requirement.get("supporting_chunks") or []
    chunk_refs = []
    if isinstance(chunks, list):
        for chunk in chunks[:3]:
            if not isinstance(chunk, dict):
                continue
            chunk_refs.append({
                "chunk_id": chunk.get("chunk_id", chunk.get("id")),
                "role": chunk.get("role"),
                "topic": chunk.get("topic"),
                "source": chunk.get("source"),
                "source_url": chunk.get("source_url"),
            })
    return {
        "required_level": required_level,
        "importance": importance,
        "requirement": {
            "source": requirement.get("source", ""),
            "source_url": requirement.get("source_url"),
            "source_quality": requirement.get("source_quality"),
            "evidence_strength": requirement.get("evidence_strength", ""),
            "required_level": required_level,
            "importance": importance,
            "role_relevance": requirement.get("role_relevance", ""),
            "evidence_context": requirement.get("evidence_context", ""),
            "supporting_chunks": chunk_refs,
        },
    }


def _signals_for_evidence(grouped: Dict[str, List[dict]], capability: Dict[str, Any],
                           evidence: List[Dict[str, Any]]) -> List[dict]:
    """Signals backing one capability's evidence (for confidence context)."""
    skills = set()
    for rule in (capability.get("evidence_rules") or []):
        if not isinstance(rule, dict):
            continue
        if rule.get("skill"):
            skills.add(_canon(rule.get("skill")))
        for extra in (rule.get("skills") or []):
            skills.add(_canon(extra))
    out: List[dict] = []
    for skill in skills:
        out.extend(grouped.get(skill, []))
    return out


def build_capability_map_for_user(
    user_id: str,
    target_role: Optional[str] = None,
    client: Any = None,
    skill: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build the full Skill Capability Map for a user + role.

    Reuses the existing pipeline pieces (profile/evidence loading, signal
    extraction, normalization, aggregation, requirements, assessments) and
    performs NO persistence and NO scoring changes: proficiency/confidence
    are read from assessments, never recomputed here.
    """
    profile = ars.load_profile(user_id)
    del profile  # validated for existence only; profile fields unused here.

    if client is None:
        try:
            client = get_supabase_client()
        except Exception:
            client = None

    role = str(target_role or "").strip()
    if not role:
        try:
            state = analysis_service.get_state(user_id)
        except Exception:
            state = None
        if isinstance(state, dict) and state.get("target_role"):
            role = str(state["target_role"]).strip()
    if not role:
        raise HTTPException(status_code=400, detail="Target role required")

    evidence, projects, certifications = ars.load_evidence(user_id)
    requirements = ars.load_industry_requirements(role)
    if not requirements:
        raise HTTPException(
            status_code=400,
            detail=f"No industry requirements found for role '{role}'",
        )
    signals = ars.extract_skill_signals(evidence, projects, certifications)
    grouped = ars.aggregate_skills(ars.normalize_signals(signals, client))
    req_map = ars.build_requirements_map(requirements, client)
    try:
        overrides = ars.load_user_overrides(user_id, client)
    except Exception:
        overrides = {}
    assessments = ars.calculate_assessments(grouped, req_map, client, overrides)
    assessments_by_skill = {
        str(a.get("canonical_name") or a.get("skill") or ""): a for a in assessments
    }

    wanted: Optional[str] = None
    if skill and str(skill).strip():
        wanted = _canon(skill)
        if not wanted:
            raise HTTPException(status_code=400, detail="Unknown skill filter")

    skills_out = []
    for req in requirements:
        canonical = _canon(req.get("skill", ""))
        if not canonical:
            continue
        if wanted and canonical != wanted:
            continue
        assessment = assessments_by_skill.get(canonical)
        if assessment is None:
            for key, candidate in assessments_by_skill.items():
                if _canon(key) == canonical:
                    assessment = candidate
                    break
        skills_out.append(build_skill_capability(role, req, grouped, assessment))

    counts = {status: 0 for status in _SKILL_STATUSES}
    for entry in skills_out:
        counts[entry.get("status", STATUS_INSUFFICIENT_DATA)] = \
            counts.get(entry.get("status", STATUS_INSUFFICIENT_DATA), 0) + 1

    return {
        "role": role,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "capability_model_version": CAPABILITY_MODEL_VERSION,
        "engine_version": engine.ENGINE_VERSION,
        "skills": skills_out,
        "summary": {
            "total_skills": len(skills_out),
            "by_status": counts,
        },
    }


CAPABILITY_MODEL_VERSION = "capability-v1"

# Support thresholds (documented, deterministic).
DEMONSTRATED_SUPPORT = 0.75  # >= this fraction of rule weight -> demonstrated
# Support in (0, 0.75) -> developing; support == 0 -> missing (gap kind below).

# Skill statuses. Reuses engine gap vocabulary where it exists.
STATUS_DEMONSTRATED = "demonstrated"
STATUS_DEVELOPING = "developing"
STATUS_EVIDENCE_GAP = "evidence_gap"
STATUS_SKILL_GAP = "skill_gap"
STATUS_INDUSTRY_GAP = "industry_gap"
STATUS_INSUFFICIENT_DATA = "insufficient_industry_data"

_SKILL_STATUSES = (
    STATUS_DEMONSTRATED,
    STATUS_DEVELOPING,
    STATUS_EVIDENCE_GAP,
    STATUS_SKILL_GAP,
    STATUS_INDUSTRY_GAP,
    STATUS_INSUFFICIENT_DATA,
)


# ---------------------------------------------------------------------------
# Curated capability blueprints, keyed by canonical skill slug.
#
# Same standing as roadmap_catalog templates: hand-written product content,
# not runtime invention. Each capability carries evidence rules evaluated
# against grouped student signals (see _rule_matches).
#
# Rule kinds (all fields optional unless noted):
#   {"kind": "signal", "skill": canonical, "min_depth": int,
#    "sources": [source_type...], "usage_in": [usage_status...],
#    "min_files": int}
#     - any signal for `skill` meeting every stated constraint.
#   {"kind": "patterns", "skill": canonical, "any_of": [pattern ids]}
#     - detected_usage_patterns for `skill` contains any listed id.
#   {"kind": "files", "skill": canonical, "min_count": int}
#     - total relevant_files across `skill` signals >= min_count.
#   {"kind": "related_present", "skills": [canonical...]}
#     - any signal exists for any listed skill (breadth only).
# Rule weight defaults to 1.0; support = matched_weight / total_weight.
# ---------------------------------------------------------------------------

def _sig_rule(skill: str, min_depth: int = 0, **kw: Any) -> Dict[str, Any]:
    rule: Dict[str, Any] = {"kind": "signal", "skill": skill, "min_depth": min_depth}
    rule.update(kw)
    return rule


def _pat_rule(skill: str, *pattern_ids: str, weight: float = 1.0) -> Dict[str, Any]:
    return {"kind": "patterns", "skill": skill, "any_of": list(pattern_ids),
            "weight": weight}


def _files_rule(skill: str, min_count: int, weight: float = 1.0) -> Dict[str, Any]:
    return {"kind": "files", "skill": skill, "min_count": min_count,
            "weight": weight}


def _rel_rule(*skills: str, weight: float = 0.5) -> Dict[str, Any]:
    return {"kind": "related_present", "skills": list(skills), "weight": weight}


CAPABILITY_BLUEPRINTS: Dict[str, List[Dict[str, Any]]] = {
    "python": [
        {
            "id": "python-fundamentals",
            "title": "Python fundamentals",
            "summary": "Write correct Python using functions, modules, and standard data structures.",
            "observable_abilities": [
                "Write functions and modules with clear structure",
                "Use lists, dicts, sets, and comprehensions appropriately",
                "Manage dependencies with requirements files or pyproject",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("Python", min_depth=3),
                _files_rule("Python", 1),
            ],
            "action": "Complete a Python fundamentals course track, then refactor a script into tested modules.",
        },
        {
            "id": "python-oop",
            "title": "OOP in Python",
            "summary": "Model problems with classes, encapsulation, and composition.",
            "observable_abilities": [
                "Design classes with clear responsibilities",
                "Apply encapsulation, inheritance, and composition",
            ],
            "related_skills": ["OOP"],
            "evidence_rules": [
                _sig_rule("Python", min_depth=3),
                _sig_rule("OOP", min_depth=1, weight=0.5),
            ],
            "action": "Refactor a procedural script into classes with unit tests for each class.",
        },
        {
            "id": "python-rest-apis",
            "title": "Build REST APIs",
            "summary": "Build maintainable backend services exposing validated HTTP APIs.",
            "observable_abilities": [
                "Build maintainable backend services",
                "Build REST APIs",
                "Implement validation and error handling",
            ],
            "related_skills": ["REST APIs", "SQL"],
            "evidence_rules": [
                _sig_rule("REST APIs", min_depth=3),
                _pat_rule("REST APIs", "fastapi_app", "flask_app", "route_decorator", "api_router"),
            ],
            "action": "Build a production-style asynchronous API with tests.",
        },
        {
            "id": "python-testing",
            "title": "Write automated tests",
            "summary": "Verify Python code with automated unit and integration tests.",
            "observable_abilities": [
                "Write automated tests",
                "Structure testable code and fixtures",
            ],
            "related_skills": ["Testing"],
            "evidence_rules": [
                _sig_rule("Testing", min_depth=2),
                _pat_rule("Testing", "test_def", "test_import"),
            ],
            "action": "Add pytest coverage to an existing module until edge cases are tested.",
        },
        {
            "id": "python-async",
            "title": "Build asynchronous services",
            "summary": "Use async programming for I/O-heavy backend workloads.",
            "observable_abilities": [
                "Build asynchronous services",
                "Use async/await for I/O-bound work correctly",
            ],
            "related_skills": ["REST APIs"],
            "evidence_rules": [
                _sig_rule("Python", min_depth=3),
                _pat_rule("REST APIs", "fastapi_app", "api_router"),
                _files_rule("Python", 3, weight=0.5),
            ],
            "action": "Build an async FastAPI service with PostgreSQL, Docker and automated tests.",
        },
        {
            "id": "python-data",
            "title": "Work with databases",
            "summary": "Persist and query data from Python using SQL and drivers.",
            "observable_abilities": [
                "Work with databases",
                "Write parameterized queries and manage connections",
            ],
            "related_skills": ["SQL", "PostgreSQL", "DBMS"],
            "evidence_rules": [
                _sig_rule("SQL", min_depth=2),
                _pat_rule("PostgreSQL", "sql_query", "pg_import"),
            ],
            "action": "Add a PostgreSQL-backed persistence layer with migrations to a project.",
        },
        {
            "id": "python-packaging",
            "title": "Package management",
            "summary": "Declare, pin, and isolate project dependencies reproducibly.",
            "observable_abilities": [
                "Declare dependencies in manifests",
                "Pin versions with lockfiles or constraints",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("Python", min_depth=2),
                _rel_rule("Testing", weight=0.5),
            ],
            "action": "Convert a project to pyproject with pinned dependencies and a clean install.",
        },
    ],
    "javascript": [
        {
            "id": "js-fundamentals",
            "title": "JavaScript fundamentals",
            "summary": "Write correct modern JavaScript for browser and server runtimes.",
            "observable_abilities": [
                "Use ES6+ syntax, modules, and array methods",
                "Handle asynchronous code with promises and async/await",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("JavaScript", min_depth=3),
                _files_rule("JavaScript", 1),
            ],
            "action": "Complete 20 JavaScript exercises covering arrays, async, and modules.",
        },
        {
            "id": "js-async",
            "title": "Asynchronous JavaScript",
            "summary": "Coordinate async work without race conditions or callback pyramids.",
            "observable_abilities": [
                "Use async/await and promise composition correctly",
                "Handle async errors and loading states",
            ],
            "related_skills": ["REST APIs"],
            "evidence_rules": [
                _sig_rule("JavaScript", min_depth=3),
                _pat_rule("REST APIs", "http_client"),
            ],
            "action": "Build a UI that fetches, caches, and gracefully fails on API errors.",
        },
        {
            "id": "js-dom",
            "title": "DOM interaction",
            "summary": "Build interactive pages that respond to user input.",
            "observable_abilities": [
                "Manipulate the DOM in response to events",
                "Manage client-side state consistently",
            ],
            "related_skills": ["HTML", "CSS"],
            "evidence_rules": [
                _sig_rule("JavaScript", min_depth=3),
                _rel_rule("HTML", "CSS", weight=0.5),
            ],
            "action": "Build an interactive page with form validation and state handling.",
        },
        {
            "id": "js-testing",
            "title": "Test JavaScript code",
            "summary": "Verify behavior with unit tests and assertions.",
            "observable_abilities": [
                "Write unit tests with assertions",
                "Test async code paths",
            ],
            "related_skills": ["Testing"],
            "evidence_rules": [
                _sig_rule("Testing", min_depth=2),
                _pat_rule("Testing", "test_def", "test_import"),
            ],
            "action": "Add Jest/Vitest coverage to an existing module.",
        },
        {
            "id": "js-tooling",
            "title": "Node.js tooling basics",
            "summary": "Run scripts and manage packages with Node.js tooling.",
            "observable_abilities": [
                "Run Node.js scripts and manage npm dependencies",
            ],
            "related_skills": ["Node.js"],
            "evidence_rules": [
                _sig_rule("Node.js", min_depth=2),
            ],
            "action": "Script a small Node.js CLI with npm scripts.",
        },
    ],
    "typescript": [
        {
            "id": "ts-types",
            "title": "Static typing",
            "summary": "Model data with types, interfaces, and generics.",
            "observable_abilities": [
                "Annotate functions and data with types",
                "Define interfaces and type aliases",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("TypeScript", min_depth=3),
                _pat_rule("TypeScript", "type_annotation", "interface_def", "type_alias"),
            ],
            "action": "Migrate a JavaScript module to strict TypeScript.",
        },
        {
            "id": "ts-config",
            "title": "TypeScript project configuration",
            "summary": "Configure strict, maintainable TypeScript projects.",
            "observable_abilities": [
                "Configure tsconfig for strictness",
                "Keep typed boundaries between modules",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("TypeScript", min_depth=2),
            ],
            "action": "Enable strict mode on a project and fix the resulting errors.",
        },
        {
            "id": "ts-react",
            "title": "Typed React components",
            "summary": "Build type-safe React components and hooks.",
            "observable_abilities": [
                "Type component props and hook state",
            ],
            "related_skills": ["React"],
            "evidence_rules": [
                _sig_rule("TypeScript", min_depth=3),
                _sig_rule("React", min_depth=3),
            ],
            "action": "Convert two React components to fully typed props and state.",
        },
        {
            "id": "ts-node",
            "title": "Type-safe backend code",
            "summary": "Write typed server-side TypeScript services.",
            "observable_abilities": [
                "Type API boundaries and service layers",
            ],
            "related_skills": ["Node.js", "Express", "REST APIs"],
            "evidence_rules": [
                _sig_rule("TypeScript", min_depth=3),
                _rel_rule("Node.js", "Express", "REST APIs", weight=0.5),
            ],
            "action": "Add typed request/response models to an Express API.",
        },
    ],
    "react": [
        {
            "id": "react-components",
            "title": "Build components",
            "summary": "Compose user interfaces from reusable components.",
            "observable_abilities": [
                "Build reusable function and class components",
                "Structure component trees sensibly",
            ],
            "related_skills": ["JavaScript"],
            "evidence_rules": [
                _sig_rule("React", min_depth=3),
                _pat_rule("React", "component_func", "component_class", "jsx_component"),
            ],
            "action": "Build three reusable components with documented props.",
        },
        {
            "id": "react-hooks",
            "title": "Manage state with hooks",
            "summary": "Handle local and shared state with hooks and effects.",
            "observable_abilities": [
                "Manage state with hooks",
                "Handle side effects correctly",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("React", min_depth=3),
                _pat_rule("React", "hook_useState", "hook_useEffect", "hook_generic"),
            ],
            "action": "Refactor class components to hooks with effect cleanup.",
        },
        {
            "id": "react-routing",
            "title": "Client-side routing",
            "summary": "Navigate between views with routes and parameters.",
            "observable_abilities": [
                "Configure routes, links, and URL parameters",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("React", min_depth=3),
                _pat_rule("React", "router"),
            ],
            "action": "Add routed views with parameterized URLs to an app.",
        },
        {
            "id": "react-state",
            "title": "Shared state management",
            "summary": "Share state across components predictably.",
            "observable_abilities": [
                "Lift state or adopt a store where justified",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("React", min_depth=3),
                _pat_rule("React", "state_mgmt"),
                _files_rule("React", 3, weight=0.5),
            ],
            "action": "Introduce a store for cross-component state with selectors.",
        },
        {
            "id": "react-data",
            "title": "Consume REST APIs",
            "summary": "Fetch, cache, and render remote data with loading and error states.",
            "observable_abilities": [
                "Fetch REST data with loading and error states",
            ],
            "related_skills": ["REST APIs"],
            "evidence_rules": [
                _sig_rule("React", min_depth=3),
                _sig_rule("REST APIs", min_depth=2, weight=0.5),
            ],
            "action": "Build a dashboard that consumes a REST API with error states.",
        },
        {
            "id": "react-quality",
            "title": "Test and polish UI",
            "summary": "Verify responsive, accessible interfaces and their states.",
            "observable_abilities": [
                "Test responsiveness, accessibility, and error states",
            ],
            "related_skills": ["Testing", "Responsive Design"],
            "evidence_rules": [
                _sig_rule("React", min_depth=3),
                _sig_rule("Testing", min_depth=2, weight=0.5),
            ],
            "action": "Add component tests covering loading, error, and empty states.",
        },
    ],
    "nodejs": [
        {
            "id": "node-runtime",
            "title": "Node.js runtime basics",
            "summary": "Run JavaScript services on Node.js with core modules.",
            "observable_abilities": [
                "Use core modules (fs, path, http) appropriately",
                "Manage processes and environment configuration",
            ],
            "related_skills": ["JavaScript"],
            "evidence_rules": [
                _sig_rule("Node.js", min_depth=3),
                _pat_rule("Node.js", "node_require", "node_import", "process_api"),
            ],
            "action": "Build a Node.js CLI using core modules and env config.",
        },
        {
            "id": "node-servers",
            "title": "Run HTTP servers",
            "summary": "Serve HTTP traffic and manage server lifecycle.",
            "observable_abilities": [
                "Start, configure, and gracefully stop servers",
            ],
            "related_skills": ["Express", "REST APIs"],
            "evidence_rules": [
                _sig_rule("Node.js", min_depth=3),
                _pat_rule("Node.js", "server_listen"),
            ],
            "action": "Serve an API with graceful shutdown and health checks.",
        },
        {
            "id": "node-packages",
            "title": "Manage Node.js dependencies",
            "summary": "Declare and lock Node.js dependencies reproducibly.",
            "observable_abilities": [
                "Maintain package.json with locked dependencies",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("Node.js", min_depth=2),
            ],
            "action": "Audit and pin dependencies, then reproduce installs cleanly.",
        },
        {
            "id": "node-async",
            "title": "Async server patterns",
            "summary": "Handle concurrent I/O without blocking the event loop.",
            "observable_abilities": [
                "Structure non-blocking I/O flows",
            ],
            "related_skills": ["Express"],
            "evidence_rules": [
                _sig_rule("Node.js", min_depth=3),
                _rel_rule("Express", weight=0.5),
            ],
            "action": "Refactor blocking I/O paths to async with load testing.",
        },
    ],
    "express": [
        {
            "id": "express-routes",
            "title": "Define Express routes",
            "summary": "Expose HTTP endpoints with Express routing.",
            "observable_abilities": [
                "Define routes with parameters and handlers",
            ],
            "related_skills": ["Node.js", "REST APIs"],
            "evidence_rules": [
                _sig_rule("Express", min_depth=3),
                _pat_rule("Express", "route_handler", "express_init"),
            ],
            "action": "Build CRUD routes with parameter validation.",
        },
        {
            "id": "express-middleware",
            "title": "Use middleware",
            "summary": "Compose cross-cutting behavior with middleware chains.",
            "observable_abilities": [
                "Write and order middleware (auth, logging, errors)",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("Express", min_depth=3),
                _pat_rule("Express", "middleware"),
            ],
            "action": "Add auth, logging, and error middleware to an API.",
        },
        {
            "id": "express-routers",
            "title": "Modular routers",
            "summary": "Split large APIs into maintainable router modules.",
            "observable_abilities": [
                "Organize endpoints into mounted routers",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("Express", min_depth=3),
                _pat_rule("Express", "router"),
                _files_rule("Express", 2, weight=0.5),
            ],
            "action": "Split a monolithic route file into mounted routers.",
        },
        {
            "id": "express-testing",
            "title": "Test Express APIs",
            "summary": "Verify endpoints with automated request tests.",
            "observable_abilities": [
                "Write endpoint tests covering success and failure paths",
            ],
            "related_skills": ["Testing"],
            "evidence_rules": [
                _sig_rule("Express", min_depth=3),
                _sig_rule("Testing", min_depth=2, weight=0.5),
            ],
            "action": "Add supertest coverage for all routes including errors.",
        },
    ],
    "rest_apis": [
        {
            "id": "rest-design",
            "title": "Design REST APIs",
            "summary": "Model resources with correct methods, status codes, and pagination.",
            "observable_abilities": [
                "Design resource-oriented endpoints",
                "Use HTTP methods and status codes correctly",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("REST APIs", min_depth=3),
                _pat_rule("REST APIs", "route_decorator", "api_router", "express_route"),
            ],
            "action": "Design a versioned CRUD API with pagination and filtering.",
        },
        {
            "id": "rest-framework",
            "title": "Implement with a framework",
            "summary": "Ship working APIs with FastAPI, Flask, Express, or Django.",
            "observable_abilities": [
                "Build REST APIs",
                "Wire frameworks to services and data layers",
            ],
            "related_skills": ["Python", "Node.js"],
            "evidence_rules": [
                _sig_rule("REST APIs", min_depth=3),
                _pat_rule("REST APIs", "fastapi_app", "flask_app", "django_view", "express_route"),
            ],
            "action": "Build a production-style REST API with FastAPI/Express (CRUD, auth, tests).",
        },
        {
            "id": "rest-validation",
            "title": "Validate input and handle errors",
            "summary": "Reject bad input clearly and fail predictably.",
            "observable_abilities": [
                "Implement validation and error handling",
                "Return consistent error responses",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("REST APIs", min_depth=3),
                _files_rule("REST APIs", 2, weight=0.5),
            ],
            "action": "Add schema validation and uniform error responses to every endpoint.",
        },
        {
            "id": "rest-auth",
            "title": "Secure APIs",
            "summary": "Protect endpoints with authentication and authorization.",
            "observable_abilities": [
                "Add auth to endpoints appropriately",
            ],
            "related_skills": ["Application Security"],
            "evidence_rules": [
                _sig_rule("REST APIs", min_depth=3),
                _rel_rule("Application Security", weight=0.5),
            ],
            "action": "Protect endpoints with token auth and role checks.",
        },
        {
            "id": "rest-docs",
            "title": "Document APIs",
            "summary": "Publish contracts consumers can implement against.",
            "observable_abilities": [
                "Write OpenAPI docs and test edge cases",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("REST APIs", min_depth=2),
            ],
            "action": "Write OpenAPI docs and test with edge cases.",
        },
        {
            "id": "rest-clients",
            "title": "Consume APIs",
            "summary": "Integrate third-party and internal APIs robustly.",
            "observable_abilities": [
                "Call APIs with retries, timeouts, and error handling",
            ],
            "related_skills": ["JavaScript", "Python"],
            "evidence_rules": [
                _pat_rule("REST APIs", "http_client"),
            ],
            "action": "Integrate two public APIs with retries and caching.",
        },
    ],
    "sql": [
        {
            "id": "sql-select",
            "title": "Query relational data",
            "summary": "Retrieve exactly the data needed with SELECT, filters, and JOINs.",
            "observable_abilities": [
                "Write SELECT queries with JOINs and filters",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("SQL", min_depth=3),
                _pat_rule("SQL", "sql_select", "sql_query"),
            ],
            "action": "Complete 50 query exercises on realistic datasets.",
        },
        {
            "id": "sql-write",
            "title": "Modify relational data safely",
            "summary": "Insert, update, and delete rows with transactions in mind.",
            "observable_abilities": [
                "Write INSERT, UPDATE, and DELETE statements safely",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("SQL", min_depth=3),
                _pat_rule("SQL", "sql_insert", "sql_update", "sql_delete"),
            ],
            "action": "Script a safe data migration with rollback steps.",
        },
        {
            "id": "sql-schema",
            "title": "Design schemas",
            "summary": "Model entities with tables, keys, and normalization.",
            "observable_abilities": [
                "Design and query a relational schema",
            ],
            "related_skills": ["DBMS"],
            "evidence_rules": [
                _sig_rule("SQL", min_depth=3),
                _pat_rule("SQL", "sql_ddl"),
            ],
            "action": "Design and query a relational schema for an e-commerce app.",
        },
        {
            "id": "sql-perf",
            "title": "Optimize queries",
            "summary": "Diagnose slow queries with plans and indexes.",
            "observable_abilities": [
                "Explain query plans and optimize slow queries",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("SQL", min_depth=3),
                _files_rule("SQL", 3, weight=0.5),
            ],
            "action": "Optimize a slow query using EXPLAIN and indexes.",
        },
        {
            "id": "sql-app",
            "title": "Use SQL from applications",
            "summary": "Integrate queries into services with safe parameterization.",
            "observable_abilities": [
                "Call parameterized queries from application code",
            ],
            "related_skills": ["Python", "DBMS"],
            "evidence_rules": [
                _sig_rule("SQL", min_depth=2),
                _pat_rule("SQL", "sql_cursor"),
            ],
            "action": "Replace string-built queries with parameterized calls.",
        },
    ],
    "postgresql": [
        {
            "id": "pg-queries",
            "title": "Query PostgreSQL",
            "summary": "Use PostgreSQL SQL fluently, including its extensions.",
            "observable_abilities": [
                "Write PostgreSQL queries and manage schemas",
            ],
            "related_skills": ["SQL"],
            "evidence_rules": [
                _sig_rule("PostgreSQL", min_depth=3),
                _pat_rule("PostgreSQL", "sql_query", "pg_import"),
            ],
            "action": "Port an app's queries to PostgreSQL-specific features.",
        },
        {
            "id": "pg-drivers",
            "title": "Connect from applications",
            "summary": "Wire services to PostgreSQL with drivers and pooling.",
            "observable_abilities": [
                "Configure drivers, pools, and transactions",
            ],
            "related_skills": ["Python", "Node.js"],
            "evidence_rules": [
                _sig_rule("PostgreSQL", min_depth=2),
                _pat_rule("PostgreSQL", "pg_import", "pg_config"),
            ],
            "action": "Add pooled connections and transactions to a service.",
        },
        {
            "id": "pg-modeling",
            "title": "Model PostgreSQL data",
            "summary": "Design tables, constraints, and indexes for Postgres.",
            "observable_abilities": [
                "Design tables with constraints and indexes",
            ],
            "related_skills": ["SQL", "DBMS"],
            "evidence_rules": [
                _sig_rule("PostgreSQL", min_depth=3),
                _pat_rule("PostgreSQL", "sql_ddl"),
            ],
            "action": "Design a schema with constraints, then load and index it.",
        },
        {
            "id": "pg-ops",
            "title": "Operate PostgreSQL locally",
            "summary": "Run Postgres reproducibly with configuration and backups in mind.",
            "observable_abilities": [
                "Run PostgreSQL via Compose with seeded data",
            ],
            "related_skills": ["Docker"],
            "evidence_rules": [
                _sig_rule("PostgreSQL", min_depth=2),
                _rel_rule("Docker", weight=0.5),
            ],
            "action": "Compose Postgres with seed data and backup scripts.",
        },
        {
            "id": "pg-perf",
            "title": "Tune PostgreSQL performance",
            "summary": "Find and fix slow Postgres queries.",
            "observable_abilities": [
                "Use EXPLAIN and indexes to tune queries",
            ],
            "related_skills": ["SQL"],
            "evidence_rules": [
                _sig_rule("PostgreSQL", min_depth=3),
                _files_rule("PostgreSQL", 2, weight=0.5),
            ],
            "action": "Tune three slow queries and document the plans.",
        },
    ],
    "docker": [
        {
            "id": "docker-images",
            "title": "Build container images",
            "summary": "Package applications into reproducible images.",
            "observable_abilities": [
                "Write Dockerfiles for applications",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("Docker", min_depth=2),
                _pat_rule("Docker", "docker_from", "docker_run"),
            ],
            "action": "Containerize an existing frontend/backend service.",
        },
        {
            "id": "docker-compose",
            "title": "Orchestrate multi-service apps",
            "summary": "Run cooperating services with Compose networking and volumes.",
            "observable_abilities": [
                "Deploy a multi-service app (api + db) with docker-compose",
                "Configure service-to-service networking",
            ],
            "related_skills": ["PostgreSQL"],
            "evidence_rules": [
                _sig_rule("Docker", min_depth=3),
                _pat_rule("Docker", "docker_from"),
                _files_rule("Docker", 2, weight=0.5),
            ],
            "action": "Containerize a backend and PostgreSQL service using Docker Compose and configure service-to-service networking.",
        },
        {
            "id": "docker-networking",
            "title": "Docker networking",
            "summary": "Connect containers securely across networks.",
            "observable_abilities": [
                "Configure container networks and published ports deliberately",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("Docker", min_depth=3),
                _files_rule("Docker", 2, weight=0.5),
            ],
            "action": "Isolate frontend, API, and database networks in Compose.",
        },
        {
            "id": "docker-volumes",
            "title": "Persist container data",
            "summary": "Keep state across restarts with volumes and mounts.",
            "observable_abilities": [
                "Configure volumes for databases and uploads",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("Docker", min_depth=2),
            ],
            "action": "Add named volumes and a backup routine to a Compose app.",
        },
        {
            "id": "docker-repro",
            "title": "Reproduce deployments",
            "summary": "Rebuild environments from scratch reliably.",
            "observable_abilities": [
                "Reproduce the deployment from scratch on a clean machine",
            ],
            "related_skills": ["CI/CD"],
            "evidence_rules": [
                _sig_rule("Docker", min_depth=3),
                _rel_rule("CI/CD", weight=0.5),
            ],
            "action": "Reproduce the deployment from scratch on a clean machine.",
        },
        {
            "id": "docker-optimize",
            "title": "Optimize images",
            "summary": "Keep images small, cached, and secure.",
            "observable_abilities": [
                "Use multi-stage builds and minimal base images",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("Docker", min_depth=3),
                _files_rule("Docker", 2, weight=0.5),
            ],
            "action": "Convert a Dockerfile to multi-stage and halve its size.",
        },
    ],
    "testing": [
        {
            "id": "testing-unit",
            "title": "Write unit tests",
            "summary": "Verify units in isolation with assertions and mocks.",
            "observable_abilities": [
                "Write unit tests with assertions and mocks",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("Testing", min_depth=2),
                _pat_rule("Testing", "test_def", "test_import"),
            ],
            "action": "Write tests for an existing module to reach 80% coverage.",
        },
        {
            "id": "testing-integration",
            "title": "Write integration tests",
            "summary": "Verify components working together, including APIs and data.",
            "observable_abilities": [
                "Write integration tests for APIs and data flows",
            ],
            "related_skills": ["REST APIs", "SQL"],
            "evidence_rules": [
                _sig_rule("Testing", min_depth=3),
                _files_rule("Testing", 2, weight=0.5),
            ],
            "action": "Add integration tests covering API-to-database flows.",
        },
        {
            "id": "testing-pipeline",
            "title": "Run tests in CI",
            "summary": "Gate changes on automated test execution.",
            "observable_abilities": [
                "Add a testing pipeline to a project",
            ],
            "related_skills": ["CI/CD"],
            "evidence_rules": [
                _sig_rule("Testing", min_depth=2),
                _rel_rule("CI/CD", weight=0.5),
            ],
            "action": "Add a testing pipeline to your API project.",
        },
        {
            "id": "testing-pytest",
            "title": "Test Python code",
            "summary": "Use pytest idioms: fixtures, parametrization, markers.",
            "observable_abilities": [
                "Write idiomatic pytest suites",
            ],
            "related_skills": ["Python"],
            "evidence_rules": [
                _sig_rule("Testing", min_depth=3),
                _sig_rule("Python", min_depth=3, weight=0.5),
            ],
            "action": "Parametrize an existing suite and add fixtures.",
        },
        {
            "id": "testing-js",
            "title": "Test JavaScript code",
            "summary": "Use Jest/Vitest idioms for frontend and Node code.",
            "observable_abilities": [
                "Write Jest/Vitest suites for JS/TS code",
            ],
            "related_skills": ["JavaScript", "TypeScript"],
            "evidence_rules": [
                _sig_rule("Testing", min_depth=3),
                _rel_rule("JavaScript", "TypeScript", weight=0.5),
            ],
            "action": "Add component tests for loading and error states.",
        },
    ],
    "git": [
        {
            "id": "git-basics",
            "title": "Version control basics",
            "summary": "Track work with commits, branches, and remotes.",
            "observable_abilities": [
                "Commit, branch, and merge with clear history",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("Git", min_depth=3),
            ],
            "action": "Practice a branching workflow on a sample repo.",
        },
        {
            "id": "git-collab",
            "title": "Collaborate with pull requests",
            "summary": "Review and integrate others' work safely.",
            "observable_abilities": [
                "Collaborate via PRs with meaningful commit history",
                "Resolve merge conflicts deliberately",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("Git", min_depth=3),
                _files_rule("Git", 2, weight=0.5),
            ],
            "action": "Collaborate via PRs with meaningful commit history.",
        },
        {
            "id": "git-workflows",
            "title": "Branching workflows",
            "summary": "Apply trunk-based or Git-flow discipline to teams.",
            "observable_abilities": [
                "Follow a consistent branching strategy",
            ],
            "related_skills": ["CI/CD"],
            "evidence_rules": [
                _sig_rule("Git", min_depth=3),
                _rel_rule("CI/CD", weight=0.5),
            ],
            "action": "Adopt trunk-based development with CI checks on a repo.",
        },
        {
            "id": "git-advanced",
            "title": "Advanced Git operations",
            "summary": "Rewrite history safely and recover from mistakes.",
            "observable_abilities": [
                "Rebase, stash, and recover work confidently",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("Git", min_depth=3),
                _files_rule("Git", 3, weight=0.5),
            ],
            "action": "Practice interactive rebase and reflog recovery.",
        },
    ],
    "kubernetes": [
        {
            "id": "k8s-manifests",
            "title": "Write Kubernetes manifests",
            "summary": "Declare Deployments, Services, and ConfigMaps as code.",
            "observable_abilities": [
                "Author Deployment and Service manifests",
            ],
            "related_skills": ["Docker"],
            "evidence_rules": [
                _sig_rule("Kubernetes", min_depth=2),
                _pat_rule("Kubernetes", "k8s_kind", "k8s_api"),
            ],
            "action": "Write manifests deploying an API with a Service.",
        },
        {
            "id": "k8s-config",
            "title": "Configure workloads",
            "summary": "Externalize configuration with ConfigMaps, Secrets, and env.",
            "observable_abilities": [
                "Manage configuration separately from images",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("Kubernetes", min_depth=2),
            ],
            "action": "Move hardcoded config into ConfigMaps and Secrets.",
        },
        {
            "id": "k8s/networking",
            "title": "Expose services",
            "summary": "Route traffic with Services and Ingress.",
            "observable_abilities": [
                "Expose workloads via Services and Ingress",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("Kubernetes", min_depth=3),
                _files_rule("Kubernetes", 2, weight=0.5),
            ],
            "action": "Expose two services behind one Ingress with TLS.",
        },
        {
            "id": "k8s-ops",
            "title": "Operate workloads",
            "summary": "Observe health, scale, and roll out safely.",
            "observable_abilities": [
                "Use probes, scaling, and rollout strategies",
            ],
            "related_skills": ["Monitoring"],
            "evidence_rules": [
                _sig_rule("Kubernetes", min_depth=3),
                _rel_rule("Monitoring", weight=0.5),
            ],
            "action": "Add probes and autoscaling to a Deployment.",
        },
    ],
    "dbms": [
        {
            "id": "dbms-modeling",
            "title": "Model relational data",
            "summary": "Design normalized schemas with keys and constraints.",
            "observable_abilities": [
                "Normalize tables and choose keys",
            ],
            "related_skills": ["SQL"],
            "evidence_rules": [
                _sig_rule("DBMS", min_depth=2),
                _sig_rule("SQL", min_depth=2, weight=0.5),
            ],
            "action": "Normalize a denormalized schema to 3NF.",
        },
        {
            "id": "dbms-indexing",
            "title": "Index for performance",
            "summary": "Choose indexes that match query patterns.",
            "observable_abilities": [
                "Create indexes and verify their use",
            ],
            "related_skills": ["SQL", "PostgreSQL"],
            "evidence_rules": [
                _sig_rule("DBMS", min_depth=3),
                _files_rule("DBMS", 2, weight=0.5),
            ],
            "action": "Index a slow workload and verify with EXPLAIN.",
        },
        {
            "id": "dbms-transactions",
            "title": "Ensure data integrity",
            "summary": "Use transactions and constraints to protect data.",
            "observable_abilities": [
                "Apply transactions and integrity constraints",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("DBMS", min_depth=2),
            ],
            "action": "Wrap a multi-write flow in a transaction with tests.",
        },
        {
            "id": "dbms-orm",
            "title": "Use ORMs effectively",
            "summary": "Map objects to tables without N+1 or integrity surprises.",
            "observable_abilities": [
                "Model with an ORM and avoid N+1 queries",
            ],
            "related_skills": ["Python", "SQL"],
            "evidence_rules": [
                _sig_rule("DBMS", min_depth=3),
                _rel_rule("Python", "SQL", weight=0.5),
            ],
            "action": "Fix N+1 queries in an ORM-backed endpoint.",
        },
    ],
    "oop": [
        {
            "id": "oop-classes",
            "title": "Design classes",
            "summary": "Encapsulate state and behavior with clear interfaces.",
            "observable_abilities": [
                "Design classes with clear responsibilities",
            ],
            "related_skills": ["Python", "Java"],
            "evidence_rules": [
                _sig_rule("OOP", min_depth=2),
            ],
            "action": "Refactor a module around small, focused classes.",
        },
        {
            "id": "oop-inheritance",
            "title": "Apply inheritance and polymorphism",
            "summary": "Share behavior safely through hierarchies and interfaces.",
            "observable_abilities": [
                "Use inheritance and polymorphism appropriately",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("OOP", min_depth=3),
                _files_rule("OOP", 2, weight=0.5),
            ],
            "action": "Replace conditionals with polymorphic dispatch.",
        },
        {
            "id": "oop-composition",
            "title": "Prefer composition",
            "summary": "Compose behavior instead of deep hierarchies.",
            "observable_abilities": [
                "Compose objects rather than deep inheritance",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("OOP", min_depth=3),
            ],
            "action": "Extract a deep hierarchy into composed collaborators.",
        },
        {
            "id": "oop-patterns",
            "title": "Apply design patterns",
            "summary": "Recognize and apply common patterns where they fit.",
            "observable_abilities": [
                "Apply factory, strategy, or observer patterns",
            ],
            "related_skills": ["System Design"],
            "evidence_rules": [
                _sig_rule("OOP", min_depth=3),
                _rel_rule("System Design", weight=0.5),
            ],
            "action": "Implement one pattern to remove duplicated logic.",
        },
    ],
    "system_design": [
        {
            "id": "sd-scalability",
            "title": "Design for scale",
            "summary": "Reason about load, bottlenecks, and horizontal growth.",
            "observable_abilities": [
                "Identify bottlenecks and scaling strategies",
            ],
            "related_skills": ["REST APIs", "SQL"],
            "evidence_rules": [
                _sig_rule("System Design", min_depth=2),
            ],
            "action": "Study 3 case studies (URL shortener, feed, chat).",
        },
        {
            "id": "sd-caching",
            "title": "Apply caching",
            "summary": "Reduce load with appropriate caching layers.",
            "observable_abilities": [
                "Add caching with correct invalidation",
            ],
            "related_skills": ["Caching", "Redis"],
            "evidence_rules": [
                _sig_rule("System Design", min_depth=2),
                _rel_rule("Caching", "Redis", weight=0.5),
            ],
            "action": "Add a cache layer with invalidation to a read path.",
        },
        {
            "id": "sd-tradeoffs",
            "title": "Document trade-offs",
            "summary": "Record architecture decisions and their consequences.",
            "observable_abilities": [
                "Document architecture decisions and trade-offs",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("System Design", min_depth=3),
                _files_rule("System Design", 2, weight=0.5),
            ],
            "action": "Write ADRs for two past architecture decisions.",
        },
        {
            "id": "sd-reliability",
            "title": "Design for reliability",
            "summary": "Handle failure with retries, timeouts, and fallbacks.",
            "observable_abilities": [
                "Add retries, timeouts, and graceful degradation",
            ],
            "related_skills": ["Monitoring"],
            "evidence_rules": [
                _sig_rule("System Design", min_depth=3),
                _rel_rule("Monitoring", weight=0.5),
            ],
            "action": "Add timeouts, retries, and health checks to a service.",
        },
    ],
}
