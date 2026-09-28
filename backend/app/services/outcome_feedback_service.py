"""P1.6: outcome feedback loop (observational read-only layer).

Aggregates existing outcome records — applications, employer feedback,
skill-level feedback, qualification alignments, placement outcomes — into
per-skill feedback signals with explicit sample sizes, time periods, and
limitations. This layer observes; it never writes skill_assessments,
skill_signals, learner proficiency, or gap mathematics (no write paths
exist in this module — statically asserted in tests).

Anti-causality contract (enforced in copy, tested by scan):
  - "Placement outcomes among observed candidates with X evidence were N."
  - "Employer feedback mentions X in N observed cases."
  - "Observed outcome data is insufficient to evaluate this signal."
  Never: "Adding X caused ...", never placement/certainty promises.

Joins use canonical IDs only (skill_id, requirement role_key, student_id
-> cohort -> course -> institution). No name-based inference. Student cohort
membership is ever-membership (any enrollment status), documented as an
approximation: outcomes cannot be timestamp-matched to active enrollment.

Minimum-n gates reuse the outcome-service skill-level convention (>= 5):
per-skill detail requires >= 5 feedback observations for a directional
signal; counts below 5 are nulled with suppression (privacy), and the
signal is INSUFFICIENT_OUTCOME_EVIDENCE.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from supabase import Client

from ..core.supabase import get_supabase_client
from .industry_roles import canonicalize_role_name
from . import training_priority_service as prio_svc
from . import curriculum_proposal_service as prop_svc

ENGINE_VERSION = "outcome-feedback-v1"
TABLES_MIGRATION_HINT = "Outcome tables missing — run backend/supabase/026_employers.sql and 027_outcomes.sql"

SIGNAL_SUPPORTIVE = "SUPPORTIVE_SIGNAL"
SIGNAL_MIXED = "MIXED_SIGNAL"
SIGNAL_CONTRADICTORY = "CONTRADICTORY_SIGNAL"
SIGNAL_INSUFFICIENT = "INSUFFICIENT_OUTCOME_EVIDENCE"

# Minimum observations for a directional per-skill signal. Reuses the
# outcome-service skill-level convention (applied>=5 and feedback>=5):
# feedback depth is the binding constraint here.
MIN_FEEDBACK_OBSERVATIONS = 5
MIN_PLACEMENT_OBSERVATIONS = 5
# Presentation band for "meets expectations on average": |gap| within this
# is reported as mixed rather than contradictory. Named, documented, and not
# psychometrics — it only labels the observed mean gap.
OUTCOME_GAP_TOLERANCE = 0.10

SUCCESSFUL_PLACEMENT_STATUSES = frozenset({"joined", "selected", "offer_accepted"})


def _ensure_client() -> Client:
    client = get_supabase_client()
    if client is None:
        raise HTTPException(
            status_code=503,
            detail="Supabase not configured — set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in backend/.env",
        )
    return client


def _table_missing_msg(e: Exception) -> bool:
    m = str(e).lower()
    return "could not find table" in m or "pgrst205" in m


def _missing_table() -> HTTPException:
    return HTTPException(status_code=503, detail=TABLES_MIGRATION_HINT)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        text = str(value).strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except Exception:
        return None


def _in_window(value: Any, start: Optional[datetime], end: Optional[datetime],
               allow_undated: bool = True) -> bool:
    if start is None and end is None:
        return True
    dt = _parse_dt(value)
    if dt is None:
        return allow_undated
    if start and dt < start:
        return False
    if end and dt > end:
        return False
    return True


def _load(client: Client, table: str) -> List[Dict[str, Any]]:
    try:
        resp = client.table(table).select("*").execute()
    except Exception as e:
        if _table_missing_msg(e):
            raise _missing_table()
        raise HTTPException(status_code=500, detail=f"Failed to load {table}")
    return resp.data or []


# ---------------------------------------------------------------------------
# Signal determination (pure, observational only)
# ---------------------------------------------------------------------------

def _signal_for(feedback_n: int, avg_gap: Optional[float]) -> tuple[str, str]:
    if feedback_n < MIN_FEEDBACK_OBSERVATIONS or avg_gap is None:
        return (SIGNAL_INSUFFICIENT,
                "Observed outcome data is insufficient to evaluate this signal.")
    if avg_gap >= 0:
        return (SIGNAL_SUPPORTIVE,
                "Observed employer ratings meet expectations on average; "
                "this describes past observations, not a causal effect.")
    if avg_gap > -OUTCOME_GAP_TOLERANCE:
        return (SIGNAL_MIXED,
                "Observed employer ratings fall slightly below expectations on "
                "average; this describes past observations, not a causal effect.")
    return (SIGNAL_CONTRADICTORY,
            "Observed employer ratings fall below expectations on average; "
            "this describes past observations, not a causal effect.")


# ---------------------------------------------------------------------------
# Orchestration (live read-only projection — no persistence, no writes)
# ---------------------------------------------------------------------------

def get_outcome_feedback(
    district: Optional[str] = None,
    role: Optional[str] = None,
    course_id: Optional[str] = None,
    institution_id: Optional[str] = None,
    skill: Optional[str] = None,
    proposal_id: Optional[str] = None,
    start_date: Any = None,
    end_date: Any = None,
    state: Any = None,
    country: Any = None,
    city: Any = None,
    region: Any = None,
) -> Dict[str, Any]:
    """Outcome feedback signals: aggregates with periods and limitations."""
    canonical_role = None
    if role is not None:
        if not str(role).strip():
            raise HTTPException(status_code=400, detail="role must not be blank")
        canonical_role = canonicalize_role_name(str(role))
        if canonical_role is None:
            return _empty_envelope(district, str(role).strip(), None, start_date, end_date,
                                   "Role does not map to a known INAURA role.")
    start = _parse_dt(start_date) if start_date else None
    end = _parse_dt(end_date) if end_date else None

    proposal_course: Optional[str] = None
    proposal_skill: Optional[str] = None
    if proposal_id is not None:
        # Proposal context resolves through P1.2 to course + skill filters.
        # The lookup reuses this call's market context, because proposal ids
        # bind the context they were computed under.
        try:
            resolved = prop_svc.get_curriculum_proposal(
                str(proposal_id), district=district or "", role=role or "",
                state=state, country=country, city=city, region=region,
                start_date=start_date, end_date=end_date)
        except HTTPException as e:
            if e.status_code == 404:
                raise HTTPException(status_code=404,
                                    detail=f"No proposal {proposal_id!r} in this context")
            raise
        proposal_course = str(resolved.get("course_id"))
        proposal_skill = str((resolved.get("skill") or {}).get("id"))
    if course_id is not None:
        proposal_course = str(course_id)
    skill_filter = str(skill).strip().lower() if skill is not None else (
        proposal_skill.lower() if proposal_skill else None)

    client = _ensure_client()
    skills_lookup = {str(r.get("id")): {
        "slug": str(r.get("canonical_name") or ""),
        "display": str(r.get("display_name") or r.get("canonical_name") or "")}
        for r in _load(client, "skills")}
    slug_by_id = {sid: info["slug"] for sid, info in skills_lookup.items() if info["slug"]}

    requirements = {str(r.get("id")): r for r in _load(client, "hiring_requirements")}
    applications = _load(client, "applications")
    feedbacks = _load(client, "employer_feedback")
    skill_feedbacks = _load(client, "employer_skill_feedback")
    alignments = _load(client, "qualification_alignments")
    placements = _load(client, "placement_outcomes")

    # Student -> course/district via ever-membership (documented approximation).
    # Institution districts are preloaded once (no per-member service calls).
    members = _load(client, "cohort_members")
    cohorts = {str(r.get("id")): r for r in _load(client, "cohorts")}
    courses = {str(r.get("id")): r for r in _load(client, "courses")}
    try:
        institutions = {str(r.get("id")): r for r in _load(client, "institutions")}
    except HTTPException:
        institutions = {}
    wanted_district = str(district).strip().lower() if district else None
    student_courses: Dict[str, set] = {}
    student_districts: Dict[str, set] = {}
    for m in members:
        uid = str(m.get("user_id") or "")
        ch = cohorts.get(str(m.get("cohort_id") or ""))
        if not uid or not ch:
            continue
        cid = str(ch.get("course_id") or "")
        course = courses.get(cid, {})
        inst_id = str(course.get("institution_id") or ch.get("institution_id") or "")
        student_courses.setdefault(uid, set()).add(cid)
        if wanted_district:
            prow = institutions.get(inst_id)
            if prow and str(prow.get("district") or "").strip().lower() == wanted_district:
                student_districts.setdefault(uid, set()).add(wanted_district)
        else:
            student_districts.setdefault(uid, set()).add("*")

    def _student_in_scope(uid: str) -> bool:
        if district and not student_districts.get(str(uid)):
            return False
        if institution_id and not any(
                str(courses.get(c, {}).get("institution_id") or "") == str(institution_id)
                for c in student_courses.get(str(uid), set())):
            return False
        if (proposal_course or course_id) and str(proposal_course or course_id) not in \
                student_courses.get(str(uid), set()):
            # Course scope without cohort history cannot attribute outcomes;
            # such students are excluded rather than misattributed.
            return False
        return True

    def _role_ok_requirement(req_id: Any) -> bool:
        if canonical_role is None:
            return True
        req = requirements.get(str(req_id or ""))
        if not req:
            return False
        key = str(req.get("role_key") or req.get("title") or "")
        return (canonicalize_role_name(key) or key.strip()).strip().lower() == canonical_role.lower()

    def _role_ok_placement(row: Dict[str, Any]) -> bool:
        if canonical_role is None:
            return True
        title = str(row.get("role_title") or "")
        return (canonicalize_role_name(title) or title.strip()).strip().lower() == canonical_role.lower()

    # Feedback observations joined to skill + filters.
    fb_by_id = {str(r.get("id")): r for r in feedbacks}
    observations: List[Dict[str, Any]] = []
    for sf in skill_feedbacks:
        fb = fb_by_id.get(str(sf.get("employer_feedback_id") or ""))
        if not fb:
            continue
        uid = str(fb.get("student_id") or "")
        if not _student_in_scope(uid):
            continue
        app = next((a for a in applications if str(a.get("id")) == str(fb.get("application_id") or "")), None)
        if canonical_role is not None and (not app or not _role_ok_requirement(app.get("hiring_requirement_id"))):
            continue
        if not _in_window(fb.get("created_at"), start, end):
            continue
        slug = slug_by_id.get(str(sf.get("skill_id") or ""))
        if not slug:
            continue
        if skill_filter and slug.lower() != skill_filter:
            continue
        try:
            exp = float(sf["expected_level"]) if sf.get("expected_level") is not None else None
            obs = float(sf["observed_level"]) if sf.get("observed_level") is not None else None
        except (TypeError, ValueError):
            exp, obs = None, None
        observations.append({"slug": slug, "expected": exp, "observed": obs})

    # Placement observations joined to student scope + role + window.
    placement_rows = []
    for p in placements:
        uid = str(p.get("student_id") or "")
        if not _student_in_scope(uid):
            continue
        if not _role_ok_placement(p):
            continue
        if not _in_window(p.get("joining_date") or p.get("created_at"), start, end):
            continue
        placement_rows.append(p)

    # Qualification alignments joined to skill (+ course scope where known).
    # Alignments are requirement-side observations (no student link), so they
    # join the universe except under an explicit course filter, which means
    # "outcomes attributable to this course's learners" — a bar unattributed
    # rows cannot meet.
    alignment_rows = []
    for a in alignments:
        slug = slug_by_id.get(str(a.get("skill_id") or ""))
        if not slug:
            continue
        if skill_filter and slug.lower() != skill_filter:
            continue
        if not _in_window(a.get("created_at"), start, end):
            continue
        if course_id is not None:
            continue
        alignment_rows.append({"slug": slug, "coverage": a.get("coverage")})

    # P1.1 priority levels for mismatch description (district + role only).
    prio_by_skill: Dict[str, str] = {}
    if district and canonical_role:
        try:
            prios = prio_svc.get_training_priorities(
                district=str(district), role=canonical_role,
                state=state, country=country, city=city, region=region,
                start_date=start_date, end_date=end_date)
            prio_by_skill = {str(e.get("skill")): str(e.get("priority") or "")
                             for e in (prios.get("priorities") or [])}
        except HTTPException:
            prio_by_skill = {}

    # Placements carry no skill column; they contribute volume + role context
    # and are attributed per skill only through feedback/alignments above.
    skills = sorted({o["slug"] for o in observations}
                    | {a["slug"] for a in alignment_rows})
    rows = []
    for slug in [s for s in skills if s]:
        obs = [o for o in observations if o["slug"] == slug]
        gaps = [o["observed"] - o["expected"] for o in obs
                if o["observed"] is not None and o["expected"] is not None]
        avg_gap = round(sum(gaps) / len(gaps), 4) if gaps else None
        aligned = [a for a in alignment_rows if a["slug"] == slug]
        covs = [float(a["coverage"]) for a in aligned
                if a.get("coverage") is not None]
        try:
            avg_cov = round(sum(covs) / len(covs), 4) if covs else None
        except (TypeError, ValueError):
            avg_cov = None
        successful = [p for p in placement_rows
                      if str(p.get("status") or "") in SUCCESSFUL_PLACEMENT_STATUSES]
        signal, limitation = _signal_for(len(obs), avg_gap)
        prio = prio_by_skill.get(slug)
        mismatch = bool(prio in ("HIGH", "MEDIUM") and signal == SIGNAL_CONTRADICTORY)
        info = next((v for v in skills_lookup.values() if v["slug"] == slug),
                    {"display": slug})
        rows.append({
            "skill": slug,
            "display_name": info["display"],
            "signal": signal,
            "limitation": limitation,
            "sample": {
                "feedback_count": len(obs) if len(obs) >= MIN_FEEDBACK_OBSERVATIONS else None,
                "feedback_suppressed": len(obs) < MIN_FEEDBACK_OBSERVATIONS,
                "placement_count": len(placement_rows) if len(placement_rows) >= MIN_PLACEMENT_OBSERVATIONS else None,
                "placements_suppressed": len(placement_rows) < MIN_PLACEMENT_OBSERVATIONS,
                "successful_placements": (len(successful)
                                          if len(placement_rows) >= MIN_PLACEMENT_OBSERVATIONS else None),
                "alignment_count": len(aligned),
            },
            "employer_feedback": {
                "observations": len(obs),
                "average_observed_minus_expected": avg_gap,
                "average_coverage": avg_cov,
            },
            "training_priority": prio,
            "observed_mismatch": mismatch,
        })
    rows.sort(key=lambda r: r["skill"])
    return {
        "district": district,
        "role": canonical_role or role,
        "canonical_role": canonical_role,
        "role_mapping_status": "mapped" if canonical_role or role is None else "unmapped",
        "course_id": proposal_course or (str(course_id) if course_id else None),
        "institution_id": str(institution_id) if institution_id else None,
        "proposal_id": str(proposal_id) if proposal_id else None,
        "observation_period": {
            "start": start.isoformat() if start else None,
            "end": end.isoformat() if end else None,
        },
        "skills": rows,
        "summary": {
            "skills_observed": len(rows),
            "supportive": sum(1 for r in rows if r["signal"] == SIGNAL_SUPPORTIVE),
            "mixed": sum(1 for r in rows if r["signal"] == SIGNAL_MIXED),
            "contradictory": sum(1 for r in rows if r["signal"] == SIGNAL_CONTRADICTORY),
            "insufficient": sum(1 for r in rows if r["signal"] == SIGNAL_INSUFFICIENT),
            "observed_mismatches": sum(1 for r in rows if r["observed_mismatch"]),
        },
        "provenance": {
            "engine_version": ENGINE_VERSION,
            "computed_at": _now(),
            "outcome_tables": ["applications", "employer_feedback",
                               "employer_skill_feedback", "qualification_alignments",
                               "placement_outcomes"],
            "min_feedback_observations": MIN_FEEDBACK_OBSERVATIONS,
            "min_placement_observations": MIN_PLACEMENT_OBSERVATIONS,
            "membership_basis": ("ever-membership in district cohorts; outcomes are "
                                 "not timestamp-matched to active enrollment"),
            "note": ("Observed aggregates only. No causal claims: co-occurrence of "
                     "training signals and outcomes does not imply impact."),
        },
        "note": "",
    }


def _empty_envelope(district: Any, role: str, canonical: Optional[str],
                    start: Any, end: Any, note: str) -> Dict[str, Any]:
    return {
        "district": district, "role": role, "canonical_role": canonical,
        "role_mapping_status": "unmapped", "course_id": None, "institution_id": None,
        "proposal_id": None,
        "observation_period": {"start": start, "end": end},
        "skills": [], "summary": {"skills_observed": 0, "supportive": 0, "mixed": 0,
                                  "contradictory": 0, "insufficient": 0,
                                  "observed_mismatches": 0},
        "provenance": {"engine_version": ENGINE_VERSION, "computed_at": _now(),
                       "note": "No evaluable role context."},
        "note": note,
    }


def get_skill_outcome_feedback(skill: str, **kwargs) -> Dict[str, Any]:
    """Single-skill feedback lookup."""
    if not skill or not str(skill).strip():
        raise HTTPException(status_code=400, detail="skill is required")
    full = get_outcome_feedback(skill=str(skill).strip().lower(), **kwargs)
    for row in full["skills"]:
        if row["skill"] == str(skill).strip().lower():
            return {**row, "district": full["district"], "role": full["role"],
                    "observation_period": full["observation_period"],
                    "provenance": full["provenance"]}
    raise HTTPException(status_code=404, detail=f"No outcome observations for skill {skill!r}")


def get_training_outcome_summary(**kwargs) -> Dict[str, Any]:
    """Counts-only slice for planning overviews."""
    full = get_outcome_feedback(**kwargs)
    return {"district": full["district"], "role": full["role"],
            "observation_period": full["observation_period"],
            "summary": full["summary"], "provenance": full["provenance"],
            "note": full["note"]}
