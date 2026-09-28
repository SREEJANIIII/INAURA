"""P1.2: curriculum change proposal engine.

Human-reviewable, deterministic proposals built on P1.1 training priorities
+ per-course P0 #4 alignment rows. Answers only: "given this observed
priority, what curriculum change could reasonably address the evidence?"

A proposal NEVER modifies curriculum data (no INSERT/UPDATE/DELETE anywhere
in this module — statically asserted in tests), is never auto-approved
(status starts and stays PENDING_REVIEW; no approval workflow exists yet),
and never invents modules, hours, seats, assessments, or employer claims.

Action selection (explicit precedence over per-course evidence):
  missing curriculum + HIGH/MEDIUM            -> ADD_SKILL
  taught + weak attainment + HIGH/MEDIUM      -> ADD_PRACTICAL_ASSESSMENT
      when firmly covered (intermediate/advanced: depth exists,
      practical demonstration is the gap); otherwise INCREASE_COVERAGE
  taught + moderate attainment + HIGH/MEDIUM  -> UPDATE_MODULE when the
      demand trend is declining and a real module resolves, else
      REVIEW_CONTENT (gap without sufficient specificity)
  taught + strong attainment + declining      -> UPDATE_MODULE (module) /
      REVIEW_CONTENT (no module); strong + stable -> no proposal
  no market / INSUFFICIENT_EVIDENCE / LOW     -> no proposal (never action)
"""

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from . import training_priority_service as prio
from . import institution_service as inst
from . import course_alignment_service as align

ENGINE_VERSION = "curriculum-proposal-v1"

ACTION_ADD_SKILL = "ADD_SKILL"
ACTION_INCREASE_COVERAGE = "INCREASE_COVERAGE"
ACTION_ADD_ASSESSMENT = "ADD_PRACTICAL_ASSESSMENT"
ACTION_UPDATE_MODULE = "UPDATE_MODULE"
ACTION_REVIEW_CONTENT = "REVIEW_CONTENT"
ACTION_TYPES = (ACTION_ADD_SKILL, ACTION_INCREASE_COVERAGE,
                ACTION_ADD_ASSESSMENT, ACTION_UPDATE_MODULE,
                ACTION_REVIEW_CONTENT)

STATUS_PENDING_REVIEW = "PENDING_REVIEW"
KNOWN_STATUSES = (STATUS_PENDING_REVIEW,)

FIRM_COVERAGE_LEVELS = frozenset({"intermediate", "advanced"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "unknown share"


# ---------------------------------------------------------------------------
# Deterministic title + rationale generation (templates over evidence fields)
# ---------------------------------------------------------------------------

def _title(action: str, display: str) -> str:
    if action == ACTION_ADD_SKILL:
        return f"Add {display} to the curriculum"
    if action == ACTION_INCREASE_COVERAGE:
        return f"Increase {display} curriculum coverage"
    if action == ACTION_ADD_ASSESSMENT:
        return f"Add practical assessment coverage for {display}"
    if action == ACTION_UPDATE_MODULE:
        return f"Review {display} module content"
    return f"Review {display} curriculum coverage"


def _rationale(action: str, display: str, industry: Dict[str, Any],
               curriculum_status: str, verified_coverage: Any,
               modules: List[str], fallback_global: bool) -> List[str]:
    out: List[str] = []
    trend = str(industry.get("trend") or "insufficient_data")
    share = industry.get("skill_share")
    if trend == "rising":
        out.append(f"{display} shows rising labour-market demand (share {_pct(share)}).")
    elif trend == "declining":
        out.append(f"{display} shows a declining demand signal (share {_pct(share)}); "
                   "review is indicated, not removal.")
    elif trend == "stable":
        out.append(f"{display} shows stable labour-market demand (share {_pct(share)}).")
    else:
        out.append(f"{display} has observed labour-market demand (share {_pct(share)}).")
    if action == ACTION_ADD_SKILL:
        out.append(f"{display} is absent from the course curriculum.")
    else:
        where = f" in {', '.join(modules)}" if modules else ""
        out.append(f"{display} is already covered by the course{where}.")
    if action in (ACTION_INCREASE_COVERAGE, ACTION_ADD_ASSESSMENT):
        out.append(f"Verified learner coverage is {share_label(verified_coverage)}, "
                   "below the established attainment bar.")
    if fallback_global:
        out.append("Market evidence uses global fallback, not district-measured demand.")
    out.append("Proposed for human review.")
    return out


def share_label(value: Any) -> str:
    try:
        return f"{float(value) * 100:.0f}%"
    except (TypeError, ValueError):
        return "unknown"


# ---------------------------------------------------------------------------
# Action selection (pure)
# ---------------------------------------------------------------------------

def _select_action(curriculum_status: str, attainment_status: str,
                   coverage: Any, trend: str,
                   modules_resolved: List[Dict[str, Any]]) -> Optional[str]:
    if curriculum_status == "missing":
        return ACTION_ADD_SKILL
    if attainment_status == "weak":
        if str(coverage) in FIRM_COVERAGE_LEVELS:
            return ACTION_ADD_ASSESSMENT
        return ACTION_INCREASE_COVERAGE
    if attainment_status == "moderate":
        if trend == "declining" and modules_resolved:
            return ACTION_UPDATE_MODULE
        return ACTION_REVIEW_CONTENT
    if attainment_status == "strong":
        if trend == "declining":
            return ACTION_UPDATE_MODULE if modules_resolved else ACTION_REVIEW_CONTENT
        return None
    return None


def _proposal_id(course_id: str, skill: str, action: str, role: str,
                 district: str, period_start: Any, provider: Any) -> str:
    basis = "|".join(str(p or "") for p in
                     (course_id, skill, action, role, district, period_start, provider))
    return "prop-" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]


def build_proposal(
    course: Dict[str, Any],
    institution: Dict[str, Any],
    district: str,
    role: str,
    al_row: Dict[str, Any],
    prio_entry: Dict[str, Any],
    modules_resolved: List[Dict[str, Any]],
    match_type: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Build one proposal from a P0 #4 alignment row + P1.1 priority entry.

    Returns None when the evidence does not support action (no market,
    INSUFFICIENT_EVIDENCE, LOW, or aligned/stable with nothing to review).
    Never invents modules: UPDATE_MODULE requires a resolved real module.
    """
    industry = al_row.get("industry") or {}
    slug = str(al_row.get("skill"))
    display = str(al_row.get("display_name") or slug)
    if not industry:
        return None
    level = str(prio_entry.get("priority") or "")
    if level in ("INSUFFICIENT_EVIDENCE", "LOW"):
        return None
    alignment = al_row.get("alignment") or {}
    curriculum_status = str(alignment.get("curriculum_status") or "")
    attainment_status = str(alignment.get("attainment_status") or "")
    trend = str(industry.get("trend") or "insufficient_data")
    coverage = (al_row.get("curriculum") or {}).get("coverage")
    action = _select_action(curriculum_status, attainment_status, coverage,
                            trend, modules_resolved)
    if action is None:
        return None

    module_names = [str(m.get("name")) for m in modules_resolved if m.get("name")]
    period = industry.get("period") or {}
    fallback_global = (match_type == "fallback_global")
    verified_cov = (al_row.get("cohort") or {}).get("verified_coverage")
    rationale = _rationale(action, display, industry, curriculum_status,
                           verified_cov, module_names, fallback_global)
    target = "module" if action == ACTION_UPDATE_MODULE else "course"
    return {
        "proposal_id": _proposal_id(str(course.get("id")), slug, action, role,
                                    district, period.get("start"), industry.get("provider_id")),
        "course_id": str(course.get("id")),
        "course_name": course.get("name"),
        "institution_id": str(institution.get("id")),
        "institution_name": institution.get("name"),
        "district": district,
        "role": role,
        "skill": {"id": slug, "name": display},
        "priority": {"level": level, "status": prio_entry.get("status"),
                     "reasons": list(prio_entry.get("reasons") or [])},
        "action": {"type": action, "status": STATUS_PENDING_REVIEW},
        "title": _title(action, display),
        "rationale": rationale,
        "current_state": {
            "curriculum_status": curriculum_status,
            "coverage": coverage,
            "modules": sorted({str(n) for n in module_names}),
            "learner_attainment": attainment_status,
            "verified_coverage": verified_cov,
            "market_status": str(alignment.get("demand_status") or ""),
            "trend": trend,
            "skill_share": industry.get("skill_share"),
        },
        "proposed_change": {
            "action_type": action,
            "skill": slug,
            "target": target,
            "module_ids": sorted({str(m.get("id")) for m in modules_resolved if m.get("id")}),
            "module_names": sorted({str(m.get("name")) for m in modules_resolved if m.get("name")}),
        },
        "evidence": prio_entry.get("evidence") or {},
        "market_context": {
            "match_type": match_type,
            "provider_id": industry.get("provider_id"),
            "period_start": period.get("start"),
            "period_end": period.get("end"),
            "role": role,
        },
        "provenance": {
            "engine_version": ENGINE_VERSION,
            "computed_at": _now(),
            "priority_engine_version": "training-priority-v1",
            "alignment_engine_version": align.ENGINE_VERSION,
            "district": district,
            "role": role,
            "market_suppressed": bool(industry.get("evidence_suppressed", False)),
            "note": ("A curriculum proposal is a planning artifact and does "
                     "not modify curriculum data."),
        },
    }


# ---------------------------------------------------------------------------
# Orchestration (live projection — no persistence, no mutation)
# ---------------------------------------------------------------------------

def _district_institutions(district: str, state: Any, country: Any) -> Dict[str, Dict[str, Any]]:
    """District roster read mirroring district_training_service selection
    (same filters: district + state, then country). P1.1 intentionally omits
    roster data, so the read lives here rather than duplicating calculations.
    """
    rows = inst.list_institutions(district=str(district), state=state)
    if country:
        rows = [r for r in rows
                if str(r.get("country") or "").strip().lower() == str(country).strip().lower()]
    return {str(r.get("id")): r for r in rows}


def _resolve_modules(course_id: str, module_names: List[str]) -> List[Dict[str, Any]]:
    """Resolve alignment module names to real P0 #2 module rows.

    Unmatched names are dropped (never invented): an empty result simply
    steers declining-content cases to REVIEW_CONTENT instead of UPDATE_MODULE.
    """
    try:
        rows = inst.list_modules(str(course_id))
    except HTTPException:
        return []
    by_name = {str(r.get("name") or "").strip().lower(): r for r in rows}
    resolved = []
    for name in module_names or []:
        hit = by_name.get(str(name or "").strip().lower())
        if hit is not None:
            resolved.append({"id": str(hit.get("id")), "name": hit.get("name")})
    return resolved


def get_curriculum_proposals(
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
    action_type: Any = None,
    priority: Any = None,
    status: Any = None,
) -> Dict[str, Any]:
    """Proposals per course+skill: separate records, never a fake universal."""
    if action_type is not None and str(action_type) not in ACTION_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid action_type: {action_type!r}")
    if priority is not None and str(priority).upper() not in ("HIGH", "MEDIUM", "LOW", "INSUFFICIENT_EVIDENCE"):
        raise HTTPException(status_code=400, detail=f"Invalid priority filter: {priority!r}")
    if status is not None and str(status) not in KNOWN_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status filter: {status!r}")

    full = prio.get_training_priorities(
        district=district, role=role, state=state, country=country, city=city,
        region=region, start_date=start_date, end_date=end_date, provider_id=provider_id,
    )
    match_type = (full.get("market_context") or {}).get("match_type")
    prio_by_skill = {str(e.get("skill")): e for e in (full.get("priorities") or [])}
    canonical_role = full.get("canonical_role") or full.get("role")

    institutions = _district_institutions(district, state, country)
    if course_id is not None:
        course = inst.get_course(str(course_id))
        iid = str(course.get("institution_id"))
        if iid not in institutions:
            raise HTTPException(status_code=400, detail="Course does not belong to this district")
        courses = [course]
    else:
        courses = []
        for iid in institutions:
            try:
                for c in inst.list_courses(iid, status="active"):
                    courses.append(c)
            except HTTPException:
                continue
    courses.sort(key=lambda c: str(c.get("name") or ""))

    proposals = []
    for course in courses:
        cid = str(course.get("id"))
        institution = institutions.get(str(course.get("institution_id")), {})
        try:
            alignment = align.get_course_alignment(
                cid, full.get("role") or role, country=country,
                region=(region or state), city=city, start_date=start_date,
                end_date=end_date, provider_id=provider_id)
        except HTTPException:
            continue
        for row in alignment.get("skills") or []:
            slug = str(row.get("skill"))
            entry = prio_by_skill.get(slug)
            if entry is None:
                continue
            modules = _resolve_modules(cid, ((row.get("curriculum") or {}).get("modules") or []))
            proposal = build_proposal(
                course, institution, str(full.get("district")), str(full.get("role")),
                row, entry, modules, match_type)
            if proposal is None:
                continue
            proposals.append(proposal)

    if skill is not None:
        proposals = [p for p in proposals if p["skill"]["id"] == str(skill).strip().lower()]
    if action_type is not None:
        proposals = [p for p in proposals if p["action"]["type"] == str(action_type)]
    if priority is not None:
        proposals = [p for p in proposals if p["priority"]["level"] == str(priority).upper()]
    if status is not None:
        proposals = [p for p in proposals if p["action"]["status"] == str(status)]
    rank = {"HIGH": 0, "MEDIUM": 1}
    proposals.sort(key=lambda p: (rank.get(p["priority"]["level"], 2), p["skill"]["id"], p["course_id"]))

    counts: Dict[str, int] = {a: 0 for a in ACTION_TYPES}
    for p in proposals:
        counts[p["action"]["type"]] += 1
    return {
        "district": full.get("district"),
        "district_status": full.get("district_status"),
        "role": full.get("role"),
        "canonical_role": canonical_role,
        "role_mapping_status": full.get("role_mapping_status"),
        "market_context": full.get("market_context"),
        "proposals": proposals,
        "summary": {"total": len(proposals), "by_action": counts,
                    "high_priority": sum(1 for p in proposals if p["priority"]["level"] == "HIGH")},
        "provenance": {
            "engine_version": ENGINE_VERSION,
            "computed_at": _now(),
            "priority_engine_version": "training-priority-v1",
            "note": ("Live projection over P1.1 priorities and per-course P0 #4 "
                     "alignments. Proposals change nothing; all start PENDING_REVIEW."),
        },
        "note": full.get("note", ""),
    }


def get_curriculum_proposal(proposal_id: str, **kwargs) -> Dict[str, Any]:
    """Single-proposal lookup (detail for review views)."""
    if not proposal_id or not str(proposal_id).strip():
        raise HTTPException(status_code=400, detail="proposal_id is required")
    full = get_curriculum_proposals(**kwargs)
    for p in full["proposals"]:
        if p["proposal_id"] == str(proposal_id).strip():
            return {**p, "market_context": full["market_context"],
                    "provenance": full["provenance"]}
    raise HTTPException(status_code=404, detail=f"No proposal {proposal_id!r} in this context")
