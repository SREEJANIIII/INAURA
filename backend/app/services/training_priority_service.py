"""P1.1: training priority engine (action-prioritization layer).

Transforms existing P0 evidence into deterministic, explainable training
priorities. Consumes district training intelligence (which itself composes
P0 #1 demand via P0 #4 alignment, P0 #2 curriculum/trainers, and P0 #3
cohort supply) and answers only: "how urgent / actionable is this
already-observed gap?"

No new evidence is invented: demand, supply, gaps, trends, confidences, and
the P0 #4 priority policy (threshold constants imported below, rules
mirrored) are reused verbatim. No LLM. No numerical ranking score.

Level mapping from district rows:
  market absent                       -> INSUFFICIENT_EVIDENCE (never LOW)
  attainment undecidable + not a
    curriculum gap                    -> INSUFFICIENT_EVIDENCE (never HIGH)
  district high/medium/low            -> HIGH/MEDIUM/LOW (same rule outcome)
Status (orthogonal to urgency):
  aligned              — fully covered + strong attainment (never "LOW")
  actionable_gap       — a real gap exists at some urgency
  insufficient_evidence — no judgment possible
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from . import district_training_service as district_svc
from .course_alignment_service import (
    HIGH_OBSERVED_SHARE,
    MODERATE_OBSERVED_SHARE,
    LOW_OBSERVED_SHARE,
    MIN_VERIFIED_COVERAGE_FOR_STRONG_ATTAINMENT,
    MIN_VERIFIED_COVERAGE_FOR_MODERATE_ATTAINMENT,
)

ENGINE_VERSION = "training-priority-v1"

LEVELS = ("HIGH", "MEDIUM", "LOW", "INSUFFICIENT_EVIDENCE")
_LEVEL_RANK = {level: rank for rank, level in enumerate(LEVELS)}

SEAT_NOTE = ("Capacity recommendation unavailable: "
             "no validated capacity data.")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Priority derivation (pure — mirrors the P0 #4/P0 #5 rule outcome)
# ---------------------------------------------------------------------------

def _derive_level(district_skill: Dict[str, Any]) -> tuple[str, List[str]]:
    """Map one district skill row to (level, reasons).

    Missing market evidence or undecidable attainment (without a
    supply-independent curriculum gap) can never become LOW or HIGH —
    only INSUFFICIENT_EVIDENCE. Reasons are restated from the district
    row's own evidence reasons (no new claims).
    """
    market = district_skill.get("market")
    gap = district_skill.get("gap") or {}
    dlevel = str((district_skill.get("priority") or {}).get("level") or "low")
    dreasons = list((district_skill.get("priority") or {}).get("reasons") or [])
    if market is None:
        return "INSUFFICIENT_EVIDENCE", ["no market evidence for this skill"]
    if (gap.get("attainment") == "insufficient_evidence"
            and gap.get("curriculum") != "district_curriculum_gap"):
        return "INSUFFICIENT_EVIDENCE", ["learner attainment cannot be assessed from available evidence"]
    if dlevel == "high":
        return "HIGH", dreasons
    if dlevel == "medium":
        return "MEDIUM", dreasons
    return "LOW", dreasons


def _derive_status(district_skill: Dict[str, Any], level: str) -> str:
    if level == "INSUFFICIENT_EVIDENCE":
        return "insufficient_evidence"
    gap = district_skill.get("gap") or {}
    if gap.get("curriculum") == "fully_covered" and gap.get("attainment") == "strong":
        return "aligned"
    return "actionable_gap"


def _evidence_packet(district_skill: Dict[str, Any]) -> Dict[str, Any]:
    """Compact evidence packet: preserved P0 values only, nulls kept as nulls.

    required_level/importance are not observed from postings (P0 #1 keeps
    them null); they are carried as explicit nulls rather than omitted, so
    consumers never mistake absence for zero. No priority_confidence is
    derived — market and supply confidences are preserved separately.
    """
    market = district_skill.get("market") or {}
    supply = district_skill.get("training_supply") or {}
    curriculum = district_skill.get("curriculum") or {}
    trainer = district_skill.get("trainer") or {}
    return {
        "skill": district_skill.get("skill"),
        "market": {
            "trend": market.get("trend"),
            "skill_share": market.get("skill_share"),
            "posting_count": market.get("posting_count"),
            "skill_posting_count": market.get("skill_posting_count"),
            "required_level": None,
            "importance": None,
            "market_confidence": market.get("confidence"),
            "match_type": None,  # filled by the orchestrator from market context
            "provider_id": market.get("provider_id"),
            "data_origin": market.get("data_origin"),
            "evidence_suppressed": market.get("evidence_suppressed"),
        },
        "curriculum": {
            "courses_teaching": curriculum.get("courses_teaching", 0),
            "courses_missing": curriculum.get("courses_missing", 0),
            "coverages": curriculum.get("coverages", []),
        },
        "learner_supply": {
            "learner_count": supply.get("learner_count", 0),
            "evidenced_learner_count": supply.get("evidenced_learner_count", 0),
            "verified_learner_count": supply.get("verified_learner_count", 0),
            "evidence_coverage": supply.get("evidence_coverage"),
            "verified_coverage": supply.get("verified_coverage"),
            "average_proficiency": supply.get("average_proficiency"),
            "supply_confidence": supply.get("average_confidence"),
        },
        "trainer": {
            "trainer_count": trainer.get("trainer_count", 0),
            "institutions_with_skill_trainers": trainer.get("institutions_with_skill_trainers", 0),
            "trainer_signal": trainer.get("trainer_signal"),
            "capacity_status": trainer.get("capacity_status"),
        },
    }


def _priority_entry(district_skill: Dict[str, Any], match_type: Optional[str]) -> Dict[str, Any]:
    level, reasons = _derive_level(district_skill)
    packet = _evidence_packet(district_skill)
    packet["market"]["match_type"] = match_type
    return {
        "skill": str(district_skill.get("skill")),
        "display_name": district_skill.get("display_name"),
        "category": district_skill.get("category"),
        "priority": level,
        "status": _derive_status(district_skill, level),
        "reasons": reasons,
        "evidence": packet,
    }


def _sort_key(entry: Dict[str, Any]) -> tuple:
    """HIGH, MEDIUM, LOW, INSUFFICIENT_EVIDENCE; then skill share desc
    (nulls last); then skill slug asc. Documented, deterministic, and —
    deliberately — not a score: order within a level carries no urgency
    claim beyond the documented sort."""
    share = ((entry.get("evidence") or {}).get("market") or {}).get("skill_share")
    return (_LEVEL_RANK[entry["priority"]],
            0 if isinstance(share, (int, float)) else 1,
            -(share or 0.0),
            str(entry.get("skill") or ""))


# ---------------------------------------------------------------------------
# Orchestration (live projection — no persistence)
# ---------------------------------------------------------------------------

def get_training_priorities(
    district: str,
    role: str,
    state: Optional[str] = None,
    country: Optional[str] = None,
    city: Optional[str] = None,
    region: Optional[str] = None,
    start_date: Any = None,
    end_date: Any = None,
    provider_id: Optional[str] = None,
    priority: Optional[str] = None,
) -> Dict[str, Any]:
    """Priorities for one district + role + market context."""
    if priority is not None and str(priority).upper() not in LEVELS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid priority filter: {priority!r}. Allowed: {list(LEVELS)}",
        )
    full = district_svc.get_district_training(
        district=district, role=role, state=state, country=country, city=city,
        region=region, start_date=start_date, end_date=end_date, provider_id=provider_id,
    )
    match_type = (full.get("market_context") or {}).get("match_type")
    entries = [_priority_entry(s, match_type) for s in (full.get("skills") or [])]
    entries.sort(key=_sort_key)
    if priority is not None:
        entries = [e for e in entries if e["priority"] == str(priority).upper()]
    counts = {level: sum(1 for e in entries if e["priority"] == level) for level in LEVELS}
    return {
        "district": full.get("district"),
        "district_status": full.get("district_status"),
        "state": full.get("state"),
        "country": full.get("country"),
        "role": full.get("role"),
        "canonical_role": full.get("canonical_role"),
        "role_mapping_status": full.get("role_mapping_status"),
        "market_context": full.get("market_context"),
        "priorities": entries,
        "summary": {
            **counts,
            "aligned_count": sum(1 for e in entries if e["status"] == "aligned"),
            "actionable_gap_count": sum(1 for e in entries if e["status"] == "actionable_gap"),
            "total": len(entries),
        },
        "capacity_note": SEAT_NOTE,
        "provenance": {
            "engine_version": ENGINE_VERSION,
            "computed_at": _now(),
            "district_training_version": (full.get("provenance") or {}).get("engine_version"),
            "thresholds_reused_from_p0_4": {
                "strong_attainment": MIN_VERIFIED_COVERAGE_FOR_STRONG_ATTAINMENT,
                "moderate_attainment": MIN_VERIFIED_COVERAGE_FOR_MODERATE_ATTAINMENT,
                "high_share": HIGH_OBSERVED_SHARE,
                "moderate_share": MODERATE_OBSERVED_SHARE,
                "low_share": LOW_OBSERVED_SHARE,
            },
            "note": ("Priorities project P0 #5 district rows through the P0 #4 "
                     "rule outcome. No new measurements; no LLM judgments."),
        },
        "note": full.get("note", ""),
    }


def get_skill_priority(skill: str, **kwargs) -> Dict[str, Any]:
    """Single-skill evidence packet (thin lookup for future P1.2 use)."""
    if not skill or not str(skill).strip():
        raise HTTPException(status_code=400, detail="skill is required")
    full = get_training_priorities(**kwargs)
    wanted = str(skill).strip().lower()
    for entry in full["priorities"]:
        if str(entry.get("skill") or "").lower() == wanted:
            return {**entry,
                    "district": full["district"], "role": full["role"],
                    "market_context": full["market_context"],
                    "provenance": full["provenance"]}
    raise HTTPException(status_code=404, detail=f"No priority for skill {skill!r} in this context")


def get_priority_summary(**kwargs) -> Dict[str, Any]:
    """Counts only (cheap planning-overview slice of the full projection)."""
    full = get_training_priorities(**kwargs)
    return {"district": full["district"], "role": full["role"],
            "market_context": full["market_context"],
            "summary": full["summary"], "capacity_note": full["capacity_note"],
            "provenance": full["provenance"], "note": full["note"]}
