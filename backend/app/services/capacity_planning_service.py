"""P1.4: capacity planning signals.

Represents the evidence available (and missing) for capacity planning. It
answers "what capacity information exists for addressing the identified
training priorities?" — never "how many seats to add".

Deterministic data rule (the whole engine in one sentence): the repository
contains no validated seat-capacity source, so capacity_status is always
CAPACITY_DATA_INSUFFICIENT and the mandatory planning note says so. The
CAPACITY_DATA_AVAILABLE state exists in the controlled vocabulary for the
day validated data arrives, with an explicit gate (a validated
seat-capacity source); tests assert it never fires today. A planning data
gap is reported as missing data, never as an observed shortage — shortage
states do not exist because no source could support them.

Inputs are composed, never recomputed: P1.1 priorities (urgency + evidence
counts) and district training intelligence (institutions, per-skill teaching
coverage, learner totals). No ratios, no seat numbers, no trainer counts
presented as requirements, no ids.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from . import district_training_service as district_svc
from . import training_priority_service as prio_svc

ENGINE_VERSION = "capacity-planning-signal-v1"

STATUS_AVAILABLE = "CAPACITY_DATA_AVAILABLE"
STATUS_INSUFFICIENT = "CAPACITY_DATA_INSUFFICIENT"

PLANNING_NOTE = ("Capacity recommendation unavailable: "
                 "no validated capacity data.")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _capacity_status() -> tuple[str, str]:
    """The only honest answer without a validated seat-capacity source."""
    return STATUS_INSUFFICIENT, PLANNING_NOTE


def get_capacity_planning(
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
) -> Dict[str, Any]:
    """Capacity planning signals for a district + role (+ optional course)."""
    if not district or not str(district).strip():
        raise HTTPException(status_code=400, detail="district is required")
    if not role or not str(role).strip():
        raise HTTPException(status_code=400, detail="role is required")

    full = prio_svc.get_training_priorities(
        district=district, role=role, state=state, country=country, city=city,
        region=region, start_date=start_date, end_date=end_date, provider_id=provider_id,
    )
    try:
        district_full = district_svc.get_district_training(
            district=str(full.get("district")), role=str(full.get("role")),
            state=state, country=country, city=city, region=region,
            start_date=start_date, end_date=end_date, provider_id=provider_id)
    except HTTPException:
        district_full = {"institutions": [], "summary": {}, "skills": []}
    dskills = {str(s.get("skill")): s for s in (district_full.get("skills") or [])}
    institutions = district_full.get("institutions") or []
    summary = district_full.get("summary") or {}
    status, note = _capacity_status()

    if course_id is not None:
        from . import institution_service as inst
        course = inst.get_course(str(course_id))
        owner = str(course.get("institution_id"))
        if owner not in {str(i.get("id")) for i in institutions}:
            raise HTTPException(status_code=400, detail="Course does not belong to this district")

    rows = []
    for entry in full.get("priorities") or []:
        slug = str(entry.get("skill"))
        ev = entry.get("evidence") or {}
        market = ev.get("market") or {}
        learner = ev.get("learner_supply") or {}
        curriculum = ev.get("curriculum") or {}
        trainer = ev.get("trainer") or {}
        drow = dskills.get(slug, {}).get("training_supply", {}) if isinstance(
            dskills.get(slug), dict) else {}
        rows.append({
            "skill": slug,
            "display_name": entry.get("display_name"),
            "priority": entry.get("priority"),
            "status": entry.get("status"),
            "district": full.get("district"),
            "courses_teaching": int(curriculum.get("courses_teaching", 0)),
            "courses_missing": int(curriculum.get("courses_missing", 0)),
            "institutions_teaching": int(drow.get("institutions_teaching", 0) or 0),
            "institutions_total": len(institutions),
            "learner_count": int(learner.get("learner_count", 0)),
            "evidenced_learner_count": int(learner.get("evidenced_learner_count", 0)),
            "verified_learner_count": int(learner.get("verified_learner_count", 0)),
            "trainers_observed": int(trainer.get("trainer_count", 0)),
            "market_trend": market.get("trend"),
            "market_share": market.get("skill_share"),
            "match_type": market.get("match_type"),
            "capacity_status": status,
            "planning_note": note,
        })

    if skill is not None:
        rows = [r for r in rows if r["skill"] == str(skill).strip().lower()]
    rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "INSUFFICIENT_EVIDENCE": 3}
    rows.sort(key=lambda r: (rank.get(str(r["priority"]), 4), r["skill"]))
    counts = {"skills_evaluated": len(rows),
              "with_learner_data": sum(1 for r in rows if r["learner_count"] > 0),
              "with_trainer_data": sum(1 for r in rows if r["trainers_observed"] > 0),
              "capacity_data_available": sum(
                  1 for r in rows if r["capacity_status"] == STATUS_AVAILABLE)}
    return {
        "district": full.get("district"),
        "district_status": full.get("district_status"),
        "role": full.get("role"),
        "canonical_role": full.get("canonical_role"),
        "role_mapping_status": full.get("role_mapping_status"),
        "course_id": str(course_id) if course_id is not None else None,
        "market_context": full.get("market_context"),
        "capacity": rows,
        "summary": {
            **counts,
            "institution_count": len(institutions),
            "course_count": int(summary.get("course_count", 0) or 0),
            "cohort_count": int(summary.get("cohort_count", 0) or 0),
            "learner_count": int(summary.get("learner_count", 0) or 0),
        },
        "capacity_evidence_status": status,
        "planning_note": note,
        "provenance": {
            "engine_version": ENGINE_VERSION,
            "computed_at": _now(),
            "priority_engine_version": "training-priority-v1",
            "district_training_version": "district-training-v1",
            "note": ("Planning inputs project observed counts; seat capacity is "
                     "not measured anywhere in the repository, so no seat, ratio, "
                     "or shortage claim is produced."),
        },
        "note": full.get("note", ""),
    }
