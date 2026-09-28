"""P1.3: trainer development signals.

Determines whether observed trainer capability appears sufficient to
support already-identified training priorities. Consumes P1.1 priorities
(urgency), P1.2 proposals (course-level actions), P0 #2 trainer mappings,
and district roster/training context — no new measurements, no inference
beyond explicit mapping presence.

Core evidentiary rule: a trainer_skills row mapping a trainer to a skill IS
evidence; the absence of a mapping is NOT evidence of inability ("no trainer
capability evidence observed", never "no trainer knows X"). Reasons use only
observed counts and coverage.

Signal levels (not P1.1 HIGH/MEDIUM/LOW — different question):
  DEVELOPMENT_SIGNAL   — mapped capability does not cover the training need
  SUFFICIENT_EVIDENCE  — mapped capability covers every teaching institution
  INSUFFICIENT_EVIDENCE — no actionable priority to support (never a verdict)
Signal types (descriptive, from observed data only):
  NO_TRAINER_OBSERVED, LOW_TRAINER_COVERAGE, SKILL_TRAINER_MISMATCH,
  TRAINER_CAPABILITY_OBSERVED, TRAINER_DATA_INSUFFICIENT.
No trainer assignment, no training plans, no ratios, no ids/names exposed.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from . import district_training_service as district_svc
from . import training_priority_service as prio_svc
from . import curriculum_proposal_service as prop_svc
from . import institution_service as inst
from .skill_taxonomy import get_canonical_skill

ENGINE_VERSION = "trainer-development-signal-v1"

LEVEL_DEVELOPMENT = "DEVELOPMENT_SIGNAL"
LEVEL_SUFFICIENT = "SUFFICIENT_EVIDENCE"
LEVEL_INSUFFICIENT = "INSUFFICIENT_EVIDENCE"

TYPE_ABSENT = "NO_TRAINER_OBSERVED"
TYPE_LOW_COVERAGE = "LOW_TRAINER_COVERAGE"
TYPE_MISMATCH = "SKILL_TRAINER_MISMATCH"
TYPE_OBSERVED = "TRAINER_CAPABILITY_OBSERVED"
TYPE_NO_DATA = "TRAINER_DATA_INSUFFICIENT"

_LEVEL_RANK = {LEVEL_DEVELOPMENT: 0, LEVEL_SUFFICIENT: 1, LEVEL_INSUFFICIENT: 2}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Roster + mapping reads (P0 #2 only; counts and sets, never identities)
# ---------------------------------------------------------------------------

def _district_roster(district: str, state: Any, country: Any,
                     course_id: Optional[str] = None) -> tuple[List[Dict[str, Any]], Dict[str, str]]:
    """Institutions in scope + course_id -> institution_id for active courses."""
    rows = inst.list_institutions(district=str(district), state=state)
    if country:
        rows = [r for r in rows
                if str(r.get("country") or "").strip().lower() == str(country).strip().lower()]
    institutions = [r for r in rows]
    course_owner: Dict[str, str] = {}
    for institution in institutions:
        try:
            courses = inst.list_courses(str(institution["id"]), status="active")
        except HTTPException:
            continue
        for c in courses:
            course_owner[str(c.get("id"))] = str(institution["id"])
    if course_id is not None:
        course = inst.get_course(str(course_id))
        owner = str(course.get("institution_id"))
        if owner not in {str(i.get("id")) for i in institutions}:
            raise HTTPException(status_code=400, detail="Course does not belong to this district")
        institutions = [i for i in institutions if str(i.get("id")) == owner]
        course_owner = {str(course.get("id")): owner}
    return institutions, course_owner


def _teaching_sets(course_owner: Dict[str, str]) -> Dict[str, Dict[str, set]]:
    """Per-skill teaching institutions/courses from P0 #2 curriculum rows."""
    taught: Dict[str, Dict[str, set]] = {}
    for cid, iid in course_owner.items():
        try:
            skills = inst.list_course_skills(cid, mapping_status="mapped")
        except HTTPException:
            continue
        for s in skills:
            slug = str(s.get("canonical_skill_slug") or "")
            if not slug:
                continue
            entry = taught.setdefault(slug, {"institutions": set(), "courses": set()})
            entry["institutions"].add(iid)
            entry["courses"].add(cid)
    return taught


def _trainer_maps(institutions: List[Dict[str, Any]]) -> tuple[Dict[str, Dict[str, Any]], int]:
    """Per-skill mapped-trainer aggregates + total trainers in scope.

    Returns ({slug: {trainer_count, institutions, proficiency, by_institution}},
    total). Proficiency values are counted as observed (including unstated);
    they describe records, not capability judgments. by_institution allows
    evidence scoped to the teaching context: {iid: {count, proficiency}}.
    """
    agg: Dict[str, Dict[str, Any]] = {}
    total = 0
    seen_trainers = set()
    for institution in institutions:
        iid = str(institution.get("id"))
        try:
            trainers = inst.list_trainers(iid)
        except HTTPException:
            continue
        for tr in trainers:
            tid = str(tr.get("id"))
            if tid in seen_trainers:
                continue
            seen_trainers.add(tid)
            total += 1
            try:
                skills = inst.list_trainer_skills(tid)
            except HTTPException:
                continue
            for s in skills:
                slug = str(s.get("canonical_skill_slug") or "")
                if not slug:
                    continue
                entry = agg.setdefault(slug, {"trainer_count": 0, "institutions": set(),
                                              "proficiency": {}, "by_institution": {}})
                entry["trainer_count"] += 1
                entry["institutions"].add(iid)
                prof = str(s.get("proficiency") or "unstated")
                entry["proficiency"][prof] = entry["proficiency"].get(prof, 0) + 1
                slot = entry["by_institution"].setdefault(iid, {"count": 0, "proficiency": {}})
                slot["count"] += 1
                slot["proficiency"][prof] = slot["proficiency"].get(prof, 0) + 1
    return agg, total


# ---------------------------------------------------------------------------
# Signal determination (pure)
# ---------------------------------------------------------------------------

def _determine(actionable: bool, teaching: set, scope_institutions: set,
               mapped_institutions: set, mapped_count: int,
               trainers_in_teaching: int) -> tuple[str, str, List[str]]:
    """Return (level, type, reasons) from observed sets only."""
    if not actionable:
        return (LEVEL_INSUFFICIENT, TYPE_NO_DATA,
                ["no actionable training priority for this skill"])
    if not teaching:
        if mapped_count > 0:
            return (LEVEL_SUFFICIENT, TYPE_OBSERVED,
                    [f"trainer capability evidence observed in {len(mapped_institutions)} "
                     "district institution(s), ahead of curriculum coverage"])
        # Untaught skills have no teaching context: district trainer presence
        # without a mapping is a mismatch, not proof of absence; zero
        # trainers anywhere is simply no observed evidence.
        if trainers_in_teaching > 0:
            return (LEVEL_DEVELOPMENT, TYPE_MISMATCH,
                    ["no trainer capability evidence is currently observed for this skill "
                     "in the district; absence of a mapping is not evidence of inability"])
        return (LEVEL_DEVELOPMENT, TYPE_ABSENT,
                ["no trainer capability evidence is currently observed for this skill "
                 "in the relevant training context; absence of evidence is not "
                 "evidence of inability"])
    mapped_here = mapped_institutions & teaching
    if not mapped_here:
        if trainers_in_teaching > 0:
            return (LEVEL_DEVELOPMENT, TYPE_MISMATCH,
                    ["trainers are observed in the teaching institution(s) but none is "
                     "mapped to this skill; absence of a mapping is not evidence of inability"])
        return (LEVEL_DEVELOPMENT, TYPE_ABSENT,
                ["no trainer capability evidence is currently observed for this skill "
                 "in the relevant training context; absence of evidence is not "
                 "evidence of inability"])
    if len(mapped_here) < len(teaching):
        return (LEVEL_DEVELOPMENT, TYPE_LOW_COVERAGE,
                [f"trainer capability evidence observed in {len(mapped_here)} of "
                 f"{len(teaching)} teaching institution(s)"])
    return (LEVEL_SUFFICIENT, TYPE_OBSERVED,
            ["trainer capability evidence observed in every teaching institution"])


# ---------------------------------------------------------------------------
# Orchestration (live projection — no persistence)
# ---------------------------------------------------------------------------

def get_trainer_development_signals(
    district: str,
    role: str,
    state: Any = None,
    country: Any = None,
    city: Any = None,
    region: Any = None,
    start_date: Any = None,
    end_date: Any = None,
    provider_id: Any = None,
    course_id: Any = None,
    skill: Any = None,
    signal: Any = None,
) -> Dict[str, Any]:
    """Trainer development signals for a district + role (+ optional course)."""
    if not district or not str(district).strip():
        raise HTTPException(status_code=400, detail="district is required")
    if not role or not str(role).strip():
        raise HTTPException(status_code=400, detail="role is required")
    if signal is not None and str(signal) not in (
            TYPE_ABSENT, TYPE_LOW_COVERAGE, TYPE_MISMATCH, TYPE_OBSERVED, TYPE_NO_DATA):
        raise HTTPException(status_code=400, detail=f"Invalid signal filter: {signal!r}")

    full = prio_svc.get_training_priorities(
        district=district, role=role, state=state, country=country, city=city,
        region=region, start_date=start_date, end_date=end_date, provider_id=provider_id,
    )
    match_type = (full.get("market_context") or {}).get("match_type")
    if full.get("role_mapping_status") != "mapped":
        # Without a resolved role there is no priority context to support;
        # return the envelope with no signals rather than uncontextualized rows.
        return {
            "district": full.get("district"), "district_status": full.get("district_status"),
            "role": full.get("role"), "canonical_role": full.get("canonical_role"),
            "role_mapping_status": full.get("role_mapping_status"),
            "course_id": str(course_id) if course_id is not None else None,
            "market_context": full.get("market_context"),
            "signals": [],
            "summary": {"DEVELOPMENT_SIGNAL": 0, "SUFFICIENT_EVIDENCE": 0,
                        "INSUFFICIENT_EVIDENCE": 0, "total": 0,
                        "trainer_total": 0, "institution_count": 0},
            "provenance": {
                "engine_version": ENGINE_VERSION,
                "computed_at": _now(),
                "priority_engine_version": "training-priority-v1",
                "proposal_engine_version": "curriculum-proposal-v1",
                "note": ("Signals project observed trainer_skill mappings against "
                         "teaching context and P1.1 priorities. No assignment, no "
                         "plans, no capability inference beyond mappings."),
            },
            "note": full.get("note", ""),
        }
    prio_by_skill = {str(e.get("skill")): e for e in (full.get("priorities") or [])}

    institutions, course_owner = _district_roster(
        str(full.get("district")), state, country,
        str(course_id) if course_id is not None else None)
    scope_ids = {str(i.get("id")) for i in institutions}
    taught = _teaching_sets(course_owner)
    trainer_agg, trainer_total = _trainer_maps(institutions)

    try:
        proposals = prop_svc.get_curriculum_proposals(
            district=str(full.get("district")), role=str(full.get("role")),
            state=state, country=country, city=city, region=region,
            start_date=start_date, end_date=end_date, provider_id=provider_id,
            **({"course_id": str(course_id)} if course_id is not None else {}))
        related: Dict[str, List[Dict[str, Any]]] = {}
        for p in proposals.get("proposals") or []:
            related.setdefault(str(p["skill"]["id"]), []).append({
                "proposal_id": p["proposal_id"], "course_id": p["course_id"],
                "action_type": p["action"]["type"],
                "priority": p["priority"]["level"]})
    except HTTPException:
        related = {}

    signals = []
    for slug in sorted(set(prio_by_skill) | set(taught) | set(trainer_agg)):
        entry = prio_by_skill.get(slug, {})
        level = str(entry.get("priority") or "")
        actionable = level in ("HIGH", "MEDIUM")
        teaching = set(taught.get(slug, {}).get("institutions", set())) & scope_ids
        mapped = set((trainer_agg.get(slug) or {}).get("institutions", set())) & scope_ids
        trainers_in_teaching = 0
        if teaching:
            for iid in teaching:
                try:
                    trainers_in_teaching += len(inst.list_trainers(iid))
                except HTTPException:
                    continue
        else:
            trainers_in_teaching = trainer_total
        slevel, stype, reasons = _determine(
            actionable, teaching, scope_ids, mapped,
            int((trainer_agg.get(slug) or {}).get("trainer_count", 0)),
            trainers_in_teaching)
        # Evidence counts follow the same teaching scope as the signal:
        # mappings outside the teaching institutions describe other
        # contexts, not this training need.
        scoped = (trainer_agg.get(slug) or {}).get("by_institution", {})
        if teaching:
            scoped = {iid: v for iid, v in scoped.items() if iid in teaching}
        scoped_count = sum(v["count"] for v in scoped.values())
        scoped_insts = {iid for iid in scoped if scoped[iid]["count"] > 0}
        scoped_prof: Dict[str, int] = {}
        for v in scoped.values():
            for prof, n in v["proficiency"].items():
                scoped_prof[prof] = scoped_prof.get(prof, 0) + n
        if entry.get("display_name"):
            display = entry["display_name"]
        else:
            hit = get_canonical_skill(slug)
            display = hit.display_name if hit else slug
        signals.append({
            "skill": slug,
            "display_name": display,
            "signal": slevel,
            "signal_type": stype,
            "reasons": reasons,
            "priority": {"level": level or None,
                         "status": entry.get("status"),
                         "reasons": list(entry.get("reasons") or [])},
            "trainer_evidence": {
                "trainer_count": scoped_count,
                "institutions_with_skill_trainers": len(scoped_insts),
                "institutions_teaching": len(teaching),
                "trainers_in_teaching_institutions": trainers_in_teaching,
                "proficiency_breakdown": scoped_prof,
            },
            "related_proposals": related.get(slug, []),
            "market_context": {"match_type": match_type,
                               "provider_id": ((entry.get("evidence") or {}).get("market") or {}).get("provider_id")},
        })

    if skill is not None:
        signals = [s for s in signals if s["skill"] == str(skill).strip().lower()]
    if signal is not None:
        signals = [s for s in signals if s["signal_type"] == str(signal)]
    rank = {LEVEL_DEVELOPMENT: 0, LEVEL_SUFFICIENT: 1, LEVEL_INSUFFICIENT: 2}
    signals.sort(key=lambda s: (rank[s["signal"]], s["skill"]))
    counts = {LEVEL_DEVELOPMENT: 0, LEVEL_SUFFICIENT: 0, LEVEL_INSUFFICIENT: 0}
    for s in signals:
        counts[s["signal"]] += 1
    return {
        "district": full.get("district"),
        "district_status": full.get("district_status"),
        "role": full.get("role"),
        "canonical_role": full.get("canonical_role"),
        "role_mapping_status": full.get("role_mapping_status"),
        "course_id": str(course_id) if course_id is not None else None,
        "market_context": full.get("market_context"),
        "signals": signals,
        "summary": {**counts, "total": len(signals),
                    "trainer_total": trainer_total,
                    "institution_count": len(institutions)},
        "provenance": {
            "engine_version": ENGINE_VERSION,
            "computed_at": _now(),
            "priority_engine_version": "training-priority-v1",
            "proposal_engine_version": "curriculum-proposal-v1",
            "note": ("Signals project observed trainer_skill mappings against "
                     "teaching context and P1.1 priorities. No assignment, no "
                     "plans, no capability inference beyond mappings."),
        },
        "note": full.get("note", ""),
    }
