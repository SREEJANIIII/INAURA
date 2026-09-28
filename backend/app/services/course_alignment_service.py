"""P0 #4: course / industry alignment engine.

Deterministic, explainable join of three sources of truth (nothing
recomputed, nothing duplicated):

  P0 #1 labour-market demand  -> industry required skills + trend + provenance
  P0 #2 course coverage       -> skills taught + coverage + modules
  P0 #3 cohort skill supply   -> demonstrated learner supply aggregates

No LLM anywhere in the calculation. No opaque overall score: every skill row
preserves industry, curriculum, and cohort dimensions side by side, plus
three transparent status axes (curriculum / attainment / demand) and a
rule-based priority with structured reasons.

Named policy constants (single location, documented — no magic numbers):
  attainment bands use verified_coverage; demand descriptors use skill_share.
  Threshold choice is documented here because the existing architecture has
  no cohort-attainment bands to reuse (proficiency there is continuous 0..1).
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from .industry_roles import canonicalize_role_name
from . import industry_intelligence as intel
from .skill_taxonomy import get_canonical_skill
from . import labour_market_service as lm
from . import institution_service as inst
from . import cohort_supply_service as cohort

ENGINE_VERSION = "course-alignment-v1"

# --- Named alignment policy (documented deterministic thresholds) ---
# Attainment bands over cohort verified_coverage.
MIN_VERIFIED_COVERAGE_FOR_STRONG_ATTAINMENT = 0.50
MIN_VERIFIED_COVERAGE_FOR_MODERATE_ATTAINMENT = 0.20
# Demand descriptors over observed skill_share (flags only, never "obsolete").
HIGH_OBSERVED_SHARE = 0.40
MODERATE_OBSERVED_SHARE = 0.25
LOW_OBSERVED_SHARE = 0.15

# Curriculum coverage levels that count as firmly taught (P0 #2 scale).
FIRM_COVERAGE_LEVELS = frozenset({"intermediate", "advanced"})

# Overall-status precedence is encoded in _overall_status(); priority rules in
# _priority(). Both are pure functions of the three status axes + demand size.


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _taxonomy_display(slug: str, fallback: Optional[str] = None) -> str:
    try:
        canon = get_canonical_skill(slug)
        if canon is not None:
            return canon.display_name
    except Exception:
        pass
    return fallback or slug


# ---------------------------------------------------------------------------
# Demand selection (P0 #1 is the source of truth; never recalculated here)
# ---------------------------------------------------------------------------

def _select_demand(role: str, country: Optional[str], region: Optional[str],
                   city: Optional[str], start_date: Any, end_date: Any,
                   provider_id: Optional[str]) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Fetch canonical demand rows and apply P0 #1 location semantics.

    Global-scope rows apply to every request; scoped rows apply only on exact
    location match (industry_intelligence.location_matches). City demand is
    therefore never fabricated: a global query over city-only rows yields no
    demand, and a city query over global-only rows falls back explicitly.
    Returns (per-skill latest rows, market_context).
    """
    requested = intel.normalize_location({"country": country, "region": region, "city": city})
    rows = lm.get_demand_signals(
        role=role, start_date=start_date, end_date=end_date,
        provider_id=provider_id, include_raw_concepts=True,
    )
    applicable = []
    unmapped_labour = 0
    for r in rows:
        row_loc = {"scope": r.get("location_scope") or "global",
                   "country": r.get("country"), "region": r.get("region"), "city": r.get("city")}
        if not intel.location_matches(row_loc, requested):
            continue
        # Canonical join only: unmapped labour concepts are preserved in the
        # source system, counted here, and excluded from alignment rows.
        if r.get("mapping_status") == "unmapped" or not r.get("skill_slug"):
            unmapped_labour += 1
            continue
        applicable.append(r)
    exact = any(not ({"scope": r.get("location_scope") or "global",
                      "country": r.get("country"), "region": r.get("region"),
                      "city": r.get("city")}.get("scope") == "global")
                for r in applicable)
    by_skill: Dict[str, List[Dict[str, Any]]] = {}
    for r in applicable:
        by_skill.setdefault(str(r.get("skill_slug") or ""), []).append(r)
    latest = []
    for slug, group in by_skill.items():
        if not slug:
            continue
        group.sort(key=lambda r: (str(r.get("period_start") or ""),
                                  float(r.get("posting_count") or 0),
                                  str(r.get("provider_id") or "")))
        # Latest period wins; ties break toward the largest sample, then
        # provider id — fully deterministic.
        latest.append(group[-1])
    latest.sort(key=lambda r: str(r.get("skill_slug") or ""))
    periods = [(r.get("period_start"), r.get("period_end")) for r in applicable if r.get("period_start")]
    context = {
        "country": requested.get("country"), "region": requested.get("region"),
        "city": requested.get("city"), "scope": requested.get("scope"),
        "label": requested.get("label"),
        "location_match": "exact" if exact else "fallback_global",
        "period_start": min((p[0] for p in periods), default=None),
        "period_end": max((p[1] for p in periods), default=None),
        "providers": sorted({str(r.get("provider_id") or "") for r in applicable if r.get("provider_id")}),
        "data_origins": sorted({str(r.get("data_origin") or "") for r in applicable if r.get("data_origin")}),
        "demand_row_count": len(applicable),
        "demand_sample_postings": sum(int(r.get("posting_count") or 0) for r in latest),
        "unmapped_labour_concepts_excluded": unmapped_labour,
    }
    return latest, context


# ---------------------------------------------------------------------------
# Status rules (pure functions — the deterministic engine core)
# ---------------------------------------------------------------------------

def _curriculum_status(taught: bool, coverage: Optional[str]) -> str:
    if not taught:
        return "missing"
    if coverage in FIRM_COVERAGE_LEVELS:
        return "covered"
    return "weakly_covered"


def _attainment_status(supply_available: bool, verified_coverage: Optional[float]) -> str:
    if not supply_available or verified_coverage is None:
        return "insufficient_evidence"
    if verified_coverage >= MIN_VERIFIED_COVERAGE_FOR_STRONG_ATTAINMENT:
        return "strong"
    if verified_coverage >= MIN_VERIFIED_COVERAGE_FOR_MODERATE_ATTAINMENT:
        return "moderate"
    return "weak"


def _demand_status(demand_row: Optional[Dict[str, Any]]) -> str:
    if demand_row is None:
        return "insufficient_market_evidence"
    trend = str(demand_row.get("trend") or "insufficient_data").strip().lower()
    if trend in ("rising", "stable", "declining", "emerging", "insufficient_data"):
        return trend
    return "insufficient_data"


def _overall_status(curriculum_status: str, attainment_status: str,
                    has_demand: bool) -> str:
    if not has_demand:
        return "insufficient_data"
    if curriculum_status == "missing":
        return "curriculum_gap"
    if attainment_status == "weak":
        return "attainment_gap"
    if attainment_status == "moderate":
        return "weak_supply"
    if attainment_status == "strong":
        return "aligned"
    return "insufficient_data"


def _priority(curriculum_status: str, attainment_status: str,
              demand_row: Optional[Dict[str, Any]]) -> tuple[str, List[str]]:
    """Rule-based priority with structured reasons (no weighted formula)."""
    reasons: List[str] = []
    share = float(demand_row.get("skill_share") or 0.0) if demand_row else 0.0
    trend = str((demand_row or {}).get("trend") or "insufficient_data")
    suppressed = bool((demand_row or {}).get("evidence_suppressed", True))
    rising = trend in ("rising", "emerging")

    if demand_row is not None and not suppressed:
        if rising:
            reasons.append(f"{trend} demand trend (share {share:.2f})")
        elif trend == "declining":
            reasons.append(f"declining demand signal (share {share:.2f}) — descriptive only")
        elif share >= HIGH_OBSERVED_SHARE:
            reasons.append(f"high observed labour-market demand (share {share:.2f})")
        elif share < LOW_OBSERVED_SHARE:
            reasons.append(f"low current observed demand (share {share:.2f})")
    if curriculum_status == "missing":
        reasons.append("skill absent from curriculum")
    if attainment_status == "weak":
        reasons.append("weak verified learner supply")

    high = (
        (curriculum_status == "missing" and not suppressed
         and (rising or share >= HIGH_OBSERVED_SHARE))
        or (attainment_status == "weak" and rising and not suppressed
            and share >= MODERATE_OBSERVED_SHARE)
    )
    if high:
        return "high", reasons
    medium = (
        curriculum_status == "missing"
        or attainment_status in ("weak", "moderate")
        or trend == "declining"
    )
    if medium:
        return "medium", reasons
    return "low", reasons


# ---------------------------------------------------------------------------
# Orchestration (live projection — no persistence, Phase 17)
# ---------------------------------------------------------------------------

def get_course_alignment(
    course_id: str,
    role: str,
    cohort_id: Optional[str] = None,
    country: Optional[str] = None,
    region: Optional[str] = None,
    city: Optional[str] = None,
    start_date: Any = None,
    end_date: Any = None,
    provider_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Align one course against industry demand for a role.

    Skill universe = demand slugs ∪ taught canonical slugs (canonical join
    only; unmapped concepts from any source are counted and excluded, never
    fabricated into mappings). Cohort supply joins where present.
    """
    if not role or not str(role).strip():
        raise HTTPException(status_code=400, detail="role is required")
    canonical_role = canonicalize_role_name(str(role))
    course = inst.get_course(course_id)
    institution = inst.get_institution(str(course.get("institution_id")))

    if canonical_role is None:
        return {
            "role": str(role).strip(), "canonical_role": None,
            "role_mapping_status": "unmapped",
            "course": {"id": course["id"], "name": course.get("name")},
            "institution": {"id": institution["id"], "name": institution.get("name")},
            "market_context": None, "cohort_context": None,
            "skills": [],
            "summary": {k: 0 for k in (
                "total_market_skills", "covered_market_skills",
                "weakly_covered_market_skills", "missing_market_skills",
                "strong_attainment_skills", "moderate_attainment_skills",
                "weak_attainment_skills", "insufficient_market_evidence_skills",
                "rising_demand_skills", "declining_demand_skills", "low_demand_skills")},
            "extra_cohort_skills": [],
            "unmapped_excluded": {"labour": 0, "course": 0, "cohort": 0},
            "provenance": {"engine_version": ENGINE_VERSION, "computed_at": _now()},
            "note": (f"Role {str(role).strip()!r} does not map to a known INAURA role; "
                     "alignment cannot be evaluated without inventing a mapping."),
        }

    demand_rows, market_context = _select_demand(
        canonical_role, country, region, city, start_date, end_date, provider_id)
    demand_by_slug = {str(r.get("skill_slug")): r for r in demand_rows}
    unmapped_labour = market_context.pop("unmapped_labour_concepts_excluded", 0)

    coverage = inst.get_course_coverage(course_id)
    taught: Dict[str, Dict[str, Any]] = {}
    unmapped_course = 0
    for group in (coverage.get("modules") or []) + [{"module_id": None, "module_name": None,
                                                     "skills": coverage.get("course_level_skills") or []}]:
        for s in group.get("skills") or []:
            if s.get("mapping_status") != "mapped" or not s.get("canonical_skill_slug"):
                unmapped_course += 1
                continue
            slug = str(s["canonical_skill_slug"])
            entry = taught.setdefault(slug, {
                "coverage": None, "importance": None, "modules": [],
                "mapping_status": "mapped", "source_concept": s.get("source_concept"),
            })
            entry["modules"].append(group.get("module_name"))
            # Firmest coverage wins when a skill spans modules.
            rank = {"introductory": 0, "intermediate": 1, "advanced": 2}
            if rank.get(str(s.get("coverage")), -1) > rank.get(str(entry["coverage"]), -1):
                entry["coverage"] = s.get("coverage")
                entry["importance"] = s.get("importance")

    if cohort_id:
        supply = cohort.get_cohort_skill_supply(str(cohort_id))
        if str((supply.get("course") or {}).get("id")) != str(course_id):
            raise HTTPException(status_code=400, detail="Cohort does not belong to this course")
        cohort_context: Optional[Dict[str, Any]] = {
            "mode": "single_cohort",
            "cohort": supply.get("cohort"), "member_count": supply.get("member_count"),
            "suppressed": supply.get("suppressed"),
        }
    else:
        supply = cohort.get_course_cohort_supply(course_id)
        cohort_context = {
            "mode": "course_combined",
            "cohorts": supply.get("cohorts"), "member_count": supply.get("member_count"),
            "suppressed": supply.get("suppressed"),
        }
    supply_by_slug = {str(s.get("skill")): s for s in (supply.get("skills") or [])}
    supply_available = bool(not supply.get("suppressed") and (supply.get("member_count") or 0) > 0)

    skill_slugs = sorted(set(demand_by_slug) | set(taught))
    rows = []
    for slug in skill_slugs:
        drow = demand_by_slug.get(slug)
        trow = taught.get(slug)
        srow = supply_by_slug.get(slug)
        taught_flag = trow is not None
        curriculum_status = _curriculum_status(taught_flag, (trow or {}).get("coverage"))
        verified_cov = srow.get("verified_coverage") if srow else None
        attainment_status = _attainment_status(supply_available and srow is not None, verified_cov)
        demand_status = _demand_status(drow)
        overall = _overall_status(curriculum_status, attainment_status, drow is not None)
        priority, reasons = _priority(curriculum_status, attainment_status, drow)
        display = _taxonomy_display(
            slug,
            (srow or {}).get("display_name") or (drow or {}).get("source_concept")
            or (trow or {}).get("source_concept") or slug)
        rows.append({
            "skill": slug,
            "display_name": display,
            "category": (srow or {}).get("category"),
            "industry": None if drow is None else {
                "required": True,
                "posting_count": drow.get("posting_count"),
                "skill_posting_count": drow.get("skill_posting_count"),
                "distinct_company_count": drow.get("distinct_company_count"),
                "skill_share": drow.get("skill_share"),
                "demand": drow.get("demand"),
                "required_level": drow.get("required_level"),
                "importance": drow.get("importance"),
                "trend": drow.get("trend"),
                "confidence": drow.get("confidence"),
                "evidence_suppressed": drow.get("evidence_suppressed"),
                "location": {"scope": drow.get("location_scope"), "country": drow.get("country"),
                             "region": drow.get("region"), "city": drow.get("city")},
                "period": {"start": drow.get("period_start"), "end": drow.get("period_end")},
                "provider_id": drow.get("provider_id"),
                "data_origin": drow.get("data_origin"),
                "source_version": drow.get("source_version"),
                "evidence_context": drow.get("evidence_context"),
            },
            "curriculum": None if trow is None else {
                "taught": True,
                "coverage": trow.get("coverage"),
                "importance": trow.get("importance"),
                "modules": sorted({m for m in trow.get("modules") or [] if m}),
                "mapping_status": trow.get("mapping_status"),
                "source_concept": trow.get("source_concept"),
                "data_origin": course.get("data_origin"),
            },
            "cohort": None if srow is None else {
                "member_count": srow.get("cohort_size"),
                "assessed_member_count": srow.get("assessed_member_count"),
                "evidenced_member_count": srow.get("evidenced_member_count"),
                "verified_member_count": srow.get("verified_member_count"),
                "skill_coverage": srow.get("skill_coverage"),
                "verified_coverage": srow.get("verified_coverage"),
                "average_proficiency": srow.get("average_proficiency"),
                "median_proficiency": srow.get("median_proficiency"),
                "average_confidence": srow.get("average_confidence"),
                "verification_rate": srow.get("verification_rate"),
                "qualifying_signal_count": srow.get("qualifying_signal_count"),
            },
            "alignment": {
                "curriculum_status": curriculum_status,
                "attainment_status": attainment_status,
                "demand_status": demand_status,
                "overall_status": overall,
                "priority": priority,
                "priority_reasons": reasons,
            },
        })

    demand_slugs = set(demand_by_slug)
    extra_cohort = sorted(set(supply_by_slug) - set(skill_slugs))
    # Attainment counts cover taught skills only: weak supply on an untaught
    # skill is expected, not a learner gap.
    taught_with_demand = [r for r in rows if r["industry"] and r["curriculum"]]
    summary = {
        "total_market_skills": len(demand_slugs),
        "covered_market_skills": sum(1 for r in rows if r["industry"] and r["alignment"]["curriculum_status"] == "covered"),
        "weakly_covered_market_skills": sum(1 for r in rows if r["industry"] and r["alignment"]["curriculum_status"] == "weakly_covered"),
        "missing_market_skills": sum(1 for r in rows if r["industry"] and r["alignment"]["curriculum_status"] == "missing"),
        "strong_attainment_skills": sum(1 for r in taught_with_demand if r["alignment"]["attainment_status"] == "strong"),
        "moderate_attainment_skills": sum(1 for r in taught_with_demand if r["alignment"]["attainment_status"] == "moderate"),
        "weak_attainment_skills": sum(1 for r in taught_with_demand if r["alignment"]["attainment_status"] == "weak"),
        "insufficient_market_evidence_skills": sum(1 for r in rows if not r["industry"]),
        "rising_demand_skills": sum(1 for r in rows if r["alignment"]["demand_status"] in ("rising", "emerging")),
        "declining_demand_skills": sum(1 for r in rows if r["alignment"]["demand_status"] == "declining"),
        "low_demand_skills": sum(1 for r in rows
                                 if r["industry"] and not r["industry"].get("evidence_suppressed", True)
                                 and float(r["industry"].get("skill_share") or 0.0) < LOW_OBSERVED_SHARE),
        "high_priority_skills": sum(1 for r in rows if r["alignment"]["priority"] == "high"),
    }
    return {
        "role": canonical_role,
        "canonical_role": canonical_role,
        "role_mapping_status": "mapped",
        "course": {"id": course["id"], "name": course.get("name"),
                   "data_origin": course.get("data_origin")},
        "institution": {"id": institution["id"], "name": institution.get("name")},
        "market_context": {**market_context, "role": canonical_role},
        "cohort_context": cohort_context,
        "skills": rows,
        "summary": summary,
        "extra_cohort_skills": extra_cohort,
        "unmapped_excluded": {
            "labour": unmapped_labour,
            "course": unmapped_course,
            "cohort": len(supply.get("unmapped_concepts") or []),
        },
        "provenance": {
            "engine_version": ENGINE_VERSION,
            "computed_at": _now(),
            "demand_providers": market_context["providers"],
            "demand_data_origins": market_context["data_origins"],
            "course_data_origin": course.get("data_origin"),
            "cohort_supply_source": (supply.get("provenance") or {}).get("source"),
            "note": ("Live projection over P0#1 demand rows, P0#2 course skills, and P0#3 "
                     "cohort supply. No persisted alignment records; no LLM judgments."),
        },
        "note": "",
    }
