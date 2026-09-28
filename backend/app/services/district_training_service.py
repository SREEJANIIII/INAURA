"""P0 #5: district training intelligence.

Live projection composing the four completed layers — nothing recalculated,
nothing duplicated:

  P0 #1 labour demand   -> consumed via P0 #4 alignment rows (demand blocks)
  P0 #2 institutions    -> district roster, courses, trainers (direct reads)
  P0 #3 cohort supply   -> per-cohort skill rows (direct reads, weighted here)
  P0 #4 alignment       -> per-course curriculum/attainment/demand statuses

District = geographic aggregation over institution.district (P0 #2 field).
No second location taxonomy: country/state/region/city reuse P0 #1
semantics, and district itself is never inferred from names or geocoding —
institutions without a matching district simply do not belong to it
(district_status "unknown" when nothing matches).

Learner-weighted aggregation (never averaged percentages):
  district verified_coverage = Σ verified learners / Σ learners.
Medians are not composable across cohorts, so the district exposes min/max
only and documents why no district median exists.

Privacy: P0 #3 suppression propagates — suppressed cohorts contribute
member counts but no per-skill detail; a district with no unsuppressed
learners suppresses all skill detail. Aggregate output never contains
user_ids or per-member evidence.

Capacity honesty: the repository contains no validated seat-capacity data,
so capacity_evidence_status is never "sufficient_data" and exact seat
recommendations are never produced (mandatory note states this).
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from .industry_roles import canonicalize_role_name
from . import institution_service as inst
from . import cohort_supply_service as cohort
from . import course_alignment_service as align

ENGINE_VERSION = "district-training-v1"

# Reused P0 #4 policy (imported, not duplicated): attainment bands and demand
# descriptors mean exactly what they mean at course level.
STRONG_ATTAINMENT = align.MIN_VERIFIED_COVERAGE_FOR_STRONG_ATTAINMENT
MODERATE_ATTAINMENT = align.MIN_VERIFIED_COVERAGE_FOR_MODERATE_ATTAINMENT
HIGH_SHARE = align.HIGH_OBSERVED_SHARE
MODERATE_SHARE = align.MODERATE_OBSERVED_SHARE
LOW_SHARE = align.LOW_OBSERVED_SHARE

SEAT_NOTE = ("Seat-capacity recommendation unavailable: "
             "no validated capacity data.")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _taxonomy_display(slug: str, fallback: Optional[str] = None) -> str:
    return align._taxonomy_display(slug, fallback)


# ---------------------------------------------------------------------------
# District roster (P0 #2 reads only)
# ---------------------------------------------------------------------------

def _district_institutions(district: str, state: Optional[str],
                           country: Optional[str]) -> List[Dict[str, Any]]:
    institutions = inst.list_institutions(district=district, state=state)
    if country:
        institutions = [i for i in institutions
                        if str(i.get("country") or "").strip().lower() == country.strip().lower()]
    return institutions


def _district_courses(institutions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Active courses across district institutions (with owner attached)."""
    courses = []
    for institution in institutions:
        try:
            rows = inst.list_courses(str(institution["id"]), status="active")
        except HTTPException:
            continue
        for c in rows:
            courses.append({**c, "institution_id": str(institution["id"]),
                            "institution_name": institution.get("name"),
                            "institution_type": institution.get("institution_type")})
    courses.sort(key=lambda c: str(c.get("name") or ""))
    return courses


def _district_cohort_supplies(courses: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], int]:
    """Per-cohort P0 #3 supply rows. Returns (supplies, suppressed_count)."""
    supplies = []
    suppressed = 0
    for course in courses:
        try:
            cohorts = cohort.list_cohorts(course_id=str(course["id"]))
        except HTTPException:
            continue
        for ch in cohorts:
            try:
                supply = cohort.get_cohort_skill_supply(str(ch["id"]))
            except HTTPException:
                continue
            supply["_course_id"] = str(course["id"])
            supply["_institution_id"] = str(course["institution_id"])
            supplies.append(supply)
            if supply.get("suppressed") or not (supply.get("member_count") or 0):
                suppressed += 1
    return supplies, suppressed


def _district_trainers(institutions: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Aggregate P0 #2 trainer skills: slug -> {trainer_count, institutions}."""
    agg: Dict[str, Dict[str, Any]] = {}
    for institution in institutions:
        try:
            trainers = inst.list_trainers(str(institution["id"]))
        except HTTPException:
            continue
        for tr in trainers:
            try:
                skills = inst.list_trainer_skills(str(tr["id"]))
            except HTTPException:
                continue
            for s in skills:
                slug = str(s.get("canonical_skill_slug") or "")
                if not slug:
                    continue
                entry = agg.setdefault(slug, {"trainer_count": 0, "institutions": set()})
                entry["trainer_count"] += 1
                entry["institutions"].add(str(institution["id"]))
    return agg


# ---------------------------------------------------------------------------
# Skill-level district aggregation (learner-weighted)
# ---------------------------------------------------------------------------

def _aggregate_district_skills(
    alignments: List[Dict[str, Any]],
    cohort_supplies: List[Dict[str, Any]],
    trainer_agg: Dict[str, Dict[str, Any]],
    institution_count: int,
    course_count: int,
) -> tuple[List[Dict[str, Any]], Dict[str, int]]:
    # Demand blocks deduped across courses (identical query context).
    demand_by_slug: Dict[str, Dict[str, Any]] = {}
    for al in alignments:
        for row in al.get("skills") or []:
            if row.get("industry") and str(row["skill"]) not in demand_by_slug:
                demand_by_slug[str(row["skill"])] = row["industry"]

    # Taught sets per course from alignment curriculum blocks.
    taught_by_course: List[set] = []
    coverage_by_skill: Dict[str, List[Optional[str]]] = {}
    course_by_skill: Dict[str, List[str]] = {}
    inst_by_skill: Dict[str, set] = {}
    for al in alignments:
        cid = str((al.get("course") or {}).get("id"))
        iid = str((al.get("institution") or {}).get("id"))
        taught_here = set()
        for row in al.get("skills") or []:
            if row.get("curriculum"):
                slug = str(row["skill"])
                taught_here.add(slug)
                coverage_by_skill.setdefault(slug, []).append(row["curriculum"].get("coverage"))
                course_by_skill.setdefault(slug, []).append(cid)
                inst_by_skill.setdefault(slug, set()).add(iid)
        taught_by_course.append(taught_here)

    # Learner-weighted sums over UNSUPPRESSED cohorts only.
    weighted: Dict[str, Dict[str, Any]] = {}
    unsuppressed_learners = 0
    seen_cohorts = set()
    for supply in cohort_supplies:
        if supply.get("suppressed") or not (supply.get("member_count") or 0):
            continue
        seen_cohorts.add(str((supply.get("cohort") or {}).get("id")))
        for s in supply.get("skills") or []:
            slug = str(s.get("skill"))
            e = weighted.setdefault(slug, {
                "learners": 0, "evidenced": 0, "verified": 0,
                "prof_num": 0.0, "prof_den": 0, "conf_num": 0.0, "conf_den": 0,
                "cohorts": set(), "qualifying_signals": 0,
                "display": s.get("display_name"), "category": s.get("category"),
            })
            n_ev = int(s.get("evidenced_member_count") or 0)
            e["learners"] += int(s.get("cohort_size") or 0)
            e["evidenced"] += n_ev
            e["verified"] += int(s.get("verified_member_count") or 0)
            e["cohorts"].add(str((supply.get("cohort") or {}).get("id")))
            e["qualifying_signals"] += int(s.get("qualifying_signal_count") or 0)
            if s.get("average_proficiency") is not None and n_ev:
                e["prof_num"] += float(s["average_proficiency"]) * n_ev
                e["prof_den"] += n_ev
            if s.get("average_confidence") is not None and n_ev:
                e["conf_num"] += float(s["average_confidence"]) * n_ev
                e["conf_den"] += n_ev
    unsuppressed_learners = sum(
        int(s.get("member_count") or 0) for s in cohort_supplies
        if not s.get("suppressed") and (s.get("member_count") or 0))

    skill_slugs = sorted(set(demand_by_slug) | set(coverage_by_skill) | set(weighted))
    rows = []
    unmapped_cohort = 0
    for supply in cohort_supplies:
        unmapped_cohort += len(supply.get("unmapped_concepts") or [])
    for slug in skill_slugs:
        drow = demand_by_slug.get(slug)
        teaching_courses = course_by_skill.get(slug, [])
        teaching_insts = inst_by_skill.get(slug, set())
        w = weighted.get(slug)
        learners = (w or {}).get("learners", 0)
        evidenced = (w or {}).get("evidenced", 0)
        verified = (w or {}).get("verified", 0)
        ev_cov = (evidenced / learners) if learners else None
        ver_cov = (verified / learners) if learners else None

        if drow is None:
            curriculum_gap: Optional[str] = None
        elif not teaching_courses:
            curriculum_gap = "district_curriculum_gap"
        elif len(teaching_courses) < course_count:
            curriculum_gap = "partially_covered"
        else:
            curriculum_gap = "fully_covered"

        if drow is None or not teaching_courses:
            # Attainment is only meaningful for taught, in-demand skills.
            attainment_gap = "not_applicable"
        elif w is None or ver_cov is None:
            attainment_gap = "insufficient_evidence"
        elif ver_cov >= STRONG_ATTAINMENT:
            attainment_gap = "strong"
        elif ver_cov >= MODERATE_ATTAINMENT:
            attainment_gap = "moderate"
        else:
            attainment_gap = "district_attainment_gap"

        if not teaching_courses:
            concentration = "absent"
        elif institution_count <= 1:
            concentration = "not_applicable"
        elif len(teaching_insts) <= 1:
            concentration = "concentrated"
        else:
            concentration = "distributed"

        trend = str((drow or {}).get("trend") or "insufficient_data")
        share = float((drow or {}).get("skill_share") or 0.0) if drow else 0.0
        suppressed_d = bool((drow or {}).get("evidence_suppressed", True))
        if drow is None:
            demand_status = "insufficient_market_evidence"
        else:
            demand_status = trend if trend in (
                "rising", "stable", "declining", "emerging", "insufficient_data") else "insufficient_data"

        reasons: List[str] = []
        if drow is not None and not suppressed_d:
            if trend in ("rising", "emerging"):
                reasons.append(f"{trend} demand trend (share {share:.2f})")
            elif trend == "declining":
                reasons.append(f"declining demand signal (share {share:.2f}) — descriptive only")
            elif share >= HIGH_SHARE:
                reasons.append(f"high observed labour-market demand (share {share:.2f})")
            elif share < LOW_SHARE:
                reasons.append(f"low current observed demand (share {share:.2f})")
        if curriculum_gap == "district_curriculum_gap":
            reasons.append("skill absent from district curriculum")
        elif curriculum_gap == "partially_covered":
            reasons.append(f"taught in {len(teaching_courses)} of {course_count} district courses")
        if attainment_gap == "district_attainment_gap" and learners:
            reasons.append(f"district verified coverage {ver_cov:.0%} across {verified} of {learners} learners")
        if concentration == "concentrated":
            reasons.append("training concentrated in a single district institution (descriptive)")

        if ((curriculum_gap == "district_curriculum_gap" and not suppressed_d
             and (trend in ("rising", "emerging") or share >= HIGH_SHARE))
                or (attainment_gap == "district_attainment_gap" and trend in ("rising", "emerging")
                    and not suppressed_d and share >= MODERATE_SHARE)):
            priority = "high"
        elif (curriculum_gap in ("district_curriculum_gap", "partially_covered")
              or attainment_gap in ("district_attainment_gap", "moderate")
              or trend == "declining"):
            priority = "medium"
        else:
            priority = "low"

        t = trainer_agg.get(slug, {"trainer_count": 0, "institutions": set()})
        t_insts = t["institutions"]
        trainer_signal = ("observed" if t["trainer_count"] > 0
                          else ("no_trainer_observed" if teaching_courses else "not_applicable"))

        rows.append({
            "skill": slug,
            "display_name": ((w or {}).get("display") or _taxonomy_display(slug, slug)),
            "category": (w or {}).get("category"),
            "market": None if drow is None else {
                "skill_share": drow.get("skill_share"),
                "demand": drow.get("demand"),
                "trend": drow.get("trend"),
                "confidence": drow.get("confidence"),
                "posting_count": drow.get("posting_count"),
                "skill_posting_count": drow.get("skill_posting_count"),
                "period": {"start": drow.get("period", {}).get("start") if isinstance(drow.get("period"), dict) else None,
                           "end": drow.get("period", {}).get("end") if isinstance(drow.get("period"), dict) else None},
                "provider_id": drow.get("provider_id"),
                "data_origin": drow.get("data_origin"),
                "evidence_suppressed": drow.get("evidence_suppressed"),
            },
            "training_supply": {
                "institution_count": institution_count,
                "institutions_teaching": len(teaching_insts),
                "course_count": course_count,
                "courses_teaching": len(teaching_courses),
                "cohort_count": len((w or {}).get("cohorts", set())),
                "learner_count": learners,
                "evidenced_learner_count": evidenced,
                "verified_learner_count": verified,
                "evidence_coverage": round(ev_cov, 4) if ev_cov is not None else None,
                "verified_coverage": round(ver_cov, 4) if ver_cov is not None else None,
                "average_proficiency": (round((w["prof_num"] / w["prof_den"]), 4)
                                        if w and w["prof_den"] else None),
                "average_confidence": (round((w["conf_num"] / w["conf_den"]), 4)
                                       if w and w["conf_den"] else None),
                "qualifying_signal_count": (w or {}).get("qualifying_signals", 0),
            },
            "curriculum": {
                "courses_teaching": len(teaching_courses),
                "courses_missing": max(0, course_count - len(teaching_courses)),
                "coverages": sorted({c for c in (coverage_by_skill.get(slug) or []) if c}),
            },
            "trainer": {
                "trainer_count": t["trainer_count"],
                "institutions_with_skill_trainers": len(t_insts),
                "trainer_skill_coverage": (round(len(t_insts) / institution_count, 4)
                                           if institution_count else None),
                "trainer_signal": trainer_signal,
                "capacity_status": "insufficient_data",
            },
            "gap": {
                "curriculum": curriculum_gap,
                "attainment": attainment_gap,
                "concentration": concentration,
            },
            "priority": {"level": priority, "reasons": reasons},
        })
    counts = {"unmapped_cohort_concepts": unmapped_cohort,
              "unsuppressed_learners": unsuppressed_learners}
    return rows, counts


# ---------------------------------------------------------------------------
# Orchestration (live projection — no persistence, Phase 16)
# ---------------------------------------------------------------------------

def _empty_envelope(district: str, state: Optional[str], country: Optional[str],
                    role: str, canonical: Optional[str], status: str, note: str) -> Dict[str, Any]:
    return {
        "district": district, "district_status": status, "state": state, "country": country,
        "role": role, "canonical_role": canonical,
        "role_mapping_status": "mapped" if canonical else "unmapped",
        "market_context": None, "institutions": [], "skills": [], "suppressed": False,
        "summary": {k: 0 for k in (
            "institution_count", "course_count", "cohort_count", "learner_count",
            "high_priority_skill_count", "curriculum_gap_count", "attainment_gap_count",
            "trainer_signal_count")},
        "capacity": {
            "current_course_count": 0, "current_cohort_count": 0, "current_learner_count": 0,
            "trainer_count": 0, "capacity_evidence_status": "insufficient_data",
            "seat_note": SEAT_NOTE,
        },
        "provenance": {"engine_version": ENGINE_VERSION, "computed_at": _now()},
        "note": note,
    }


def get_district_training(
    district: str,
    role: str,
    state: Optional[str] = None,
    country: Optional[str] = None,
    city: Optional[str] = None,
    region: Optional[str] = None,
    start_date: Any = None,
    end_date: Any = None,
    provider_id: Optional[str] = None,
) -> Dict[str, Any]:
    """District training intelligence: evidence-backed planning inputs."""
    if not district or not str(district).strip():
        raise HTTPException(status_code=400, detail="district is required")
    if not role or not str(role).strip():
        raise HTTPException(status_code=400, detail="role is required")
    district = str(district).strip()
    state = region or state  # region is the explicit override for state context
    canonical_role = canonicalize_role_name(str(role))
    if canonical_role is None:
        return _empty_envelope(district, state, country, str(role).strip(), None, "unknown",
                               f"Role {str(role).strip()!r} does not map to a known INAURA role.")

    institutions = _district_institutions(district, state, country)
    if not institutions:
        return _empty_envelope(district, state, country, str(role).strip(),
                               canonical_role, "unknown",
                               "No institutions recorded for this district; district not fabricated.")
    courses = _district_courses(institutions)

    alignments: List[Dict[str, Any]] = []
    for course in courses:
        try:
            alignments.append(align.get_course_alignment(
                str(course["id"]), canonical_role, country=country,
                region=state, city=city, start_date=start_date,
                end_date=end_date, provider_id=provider_id))
        except HTTPException:
            continue

    cohort_supplies, suppressed_cohorts = _district_cohort_supplies(courses)
    active_cohorts = [s for s in cohort_supplies if (s.get("member_count") or 0) > 0]
    learners = sum(int(s.get("member_count") or 0) for s in cohort_supplies)
    trainer_agg = _district_trainers(institutions)

    # Market context shared across district courses (identical query context).
    market = None
    match_type = "insufficient_data"
    for al in alignments:
        mc = al.get("market_context") or {}
        if (al.get("summary") or {}).get("total_market_skills"):
            market = mc
            match_type = mc.get("location_match", "fallback_global")
            break
    if market is None and alignments:
        market = alignments[0].get("market_context") or {}
        match_type = "insufficient_data" if not (market.get("demand_row_count") or 0) else market.get(
            "location_match", "fallback_global")

    skills, agg_counts = _aggregate_district_skills(
        alignments, cohort_supplies, trainer_agg, len(institutions), len(courses))
    unsuppressed_learners = agg_counts["unsuppressed_learners"]
    suppressed_detail = unsuppressed_learners == 0 and learners > 0
    if unsuppressed_learners == 0:
        skills = []

    by_type: Dict[str, int] = {}
    for i in institutions:
        key = str(i.get("institution_type") or "other")
        by_type[key] = by_type.get(key, 0) + 1
    by_mode: Dict[str, int] = {}
    for c in courses:
        key = str(c.get("delivery_mode") or "unspecified")
        by_mode[key] = by_mode.get(key, 0) + 1

    unmapped = {"course": 0, "cohort": agg_counts["unmapped_cohort_concepts"], "labour": 0}
    for al in alignments:
        for k in ("labour", "course"):
            unmapped[k] += int((al.get("unmapped_excluded") or {}).get(k) or 0)

    summary = {
        "institution_count": len(institutions),
        "course_count": len(courses),
        "cohort_count": sum(1 for s in cohort_supplies if (s.get("member_count") or 0) > 0),
        "learner_count": learners,
        "suppressed_cohort_count": suppressed_cohorts,
        "suppressed_learner_count": learners - unsuppressed_learners,
        "institution_count_by_type": by_type,
        "course_count_by_delivery_mode": by_mode,
        "high_priority_skill_count": sum(1 for s in skills if s["priority"]["level"] == "high"),
        "curriculum_gap_count": sum(1 for s in skills if s["gap"]["curriculum"] == "district_curriculum_gap"),
        "attainment_gap_count": sum(1 for s in skills if s["gap"]["attainment"] == "district_attainment_gap"),
        "trainer_signal_count": sum(1 for s in skills if s["trainer"]["trainer_signal"] == "observed"),
    }
    trainer_total = sum(v["trainer_count"] for v in trainer_agg.values())
    capacity_status = "partial_data" if (institutions or courses) else "insufficient_data"
    return {
        "district": district, "district_status": "known", "state": state, "country": country,
        "role": canonical_role, "canonical_role": canonical_role,
        "role_mapping_status": "mapped",
        "market_context": {
            "role": canonical_role, "country": country, "region": state, "city": city,
            "match_type": ("fallback_global" if match_type == "fallback_global"
                           else ("exact" if match_type == "exact" else "insufficient_data")),
            "period_start": (market or {}).get("period_start"),
            "period_end": (market or {}).get("period_end"),
            "providers": (market or {}).get("providers", []),
            "data_origins": (market or {}).get("data_origins", []),
            "demand_row_count": (market or {}).get("demand_row_count", 0),
        },
        "institutions": [{"id": i["id"], "name": i.get("name"),
                          "institution_type": i.get("institution_type")} for i in institutions],
        "skills": skills,
        "suppressed": suppressed_detail,
        "summary": summary,
        "capacity": {
            "current_course_count": len(courses),
            "current_cohort_count": summary["cohort_count"],
            "current_learner_count": learners,
            "trainer_count": trainer_total,
            "capacity_evidence_status": capacity_status,
            "seat_note": SEAT_NOTE,
        },
        "unmapped_excluded": unmapped,
        "provenance": {
            "engine_version": ENGINE_VERSION,
            "computed_at": _now(),
            "course_alignment_version": align.ENGINE_VERSION,
            "cohort_supply_version": cohort.SUPPLY_VERSION,
            "demand_source": "p0_1_labour_market_via_p0_4_alignment",
            "note": ("Live projection over district institutions/courses/cohorts. "
                     "No persisted district records; no seat recommendations; no LLM judgments."),
        },
        "note": ("Demand evidence is global fallback, not district-measured demand."
                 if match_type == "fallback_global" else ""),
    }


# --- Spec Phase 17 service surface (projections over the orchestrator) ---

def get_district_summary(**kwargs) -> Dict[str, Any]:
    full = get_district_training(**kwargs)
    return {k: full[k] for k in (
        "district", "district_status", "state", "country", "role",
        "market_context", "summary", "capacity", "provenance", "note")}


def get_district_skill_intelligence(**kwargs) -> Dict[str, Any]:
    full = get_district_training(**kwargs)
    return {k: full[k] for k in (
        "district", "district_status", "role", "market_context", "skills",
        "suppressed", "unmapped_excluded", "provenance", "note")}


def get_district_training_gaps(**kwargs) -> Dict[str, Any]:
    full = get_district_training(**kwargs)
    gaps = [s for s in full["skills"]
            if s["gap"]["curriculum"] == "district_curriculum_gap"
            or s["gap"]["attainment"] == "district_attainment_gap"]
    return {"district": full["district"], "role": full["role"],
            "market_context": full["market_context"], "gaps": gaps,
            "provenance": full["provenance"]}


def get_district_priority_signals(**kwargs) -> Dict[str, Any]:
    full = get_district_training(**kwargs)
    ordered = {"high": 0, "medium": 1, "low": 2}
    signals = sorted(
        ({"skill": s["skill"], "display_name": s["display_name"],
          "priority": s["priority"]} for s in full["skills"]
         if s["priority"]["level"] in ("high", "medium")),
        key=lambda r: (ordered[r["priority"]["level"]], r["skill"]))
    return {"district": full["district"], "role": full["role"],
            "market_context": full["market_context"], "signals": signals,
            "provenance": full["provenance"]}
