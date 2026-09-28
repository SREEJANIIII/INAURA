"""P0 #3: cohort skill supply.

Aggregates EXISTING verified learner skill evidence (skill_signals /
skill_assessments, keyed by the canonical student identifier auth.users.id)
over cohort rosters (cohorts / cohort_members). There is deliberately NO
demand comparison, scoring, ranking, or recommendation logic here — that is
P0 #4 territory.

Source-of-truth decisions (Phase 3):
  - Student skill state is NEVER duplicated. Per-member proficiency and
    confidence reuse skill_engine.proficiency_with_prior and
    skill_engine.confidence_from_signals — the exact pipeline functions.
  - Evidence tiers reuse evidence_weights.RELIABILITY_TIERS via tier_of().
  - Only cohorts + cohort_members are persisted (new roster data, not a
    skill projection). Supply is derived live on every read, so there is no
    refresh/invalidation mechanism to document beyond "reads are live".

Qualifying-evidence definitions (Phase 5, reusing existing semantics):
  - assessed member: >= 1 signal of any tier for the skill, or a
    skill_assessments row (the pipeline once estimated this skill).
  - evidenced member: >= 1 signal from a tier INAURA treats as evidence
    (supporting / medium / high / very_high — i.e. NOT low-tier
    resume/linkedin/self_declared alone), or a skill_assessments row.
    Self-reported-only members are therefore never counted as supply.
  - verified member: >= 1 assessment-source signal for the skill
    (evidence_weights.has_direct_validation — the same "validated by
    assessment" contract as analysis_run_service.evidence_state).

Privacy: per-skill detail requires >= MIN_ACTIVE_MEMBERS_FOR_SKILL_DETAIL
active members (5, mirroring the existing skill-level min-n convention in
outcome analytics). Smaller cohorts return counts only. Aggregate responses
never contain user_ids or per-member evidence.
"""

from fastapi import HTTPException
from supabase import Client
from datetime import datetime, timezone
from statistics import median
from uuid import uuid5, NAMESPACE_DNS

from ..core.supabase import get_supabase_client
from . import skill_engine as engine
from . import evidence_weights as ew

TABLES_MIGRATION_HINT = "Cohort tables missing — run backend/supabase/032_cohort_skill_supply.sql"

COHORT_STATUSES = frozenset({"draft", "active", "completed", "archived"})
ENROLLMENT_STATUSES = frozenset({"active", "completed", "withdrawn"})

# Tiers that qualify as evidence (everything except self-reported "low").
QUALIFYING_TIERS = frozenset({"supporting", "medium", "high", "very_high"})

# Minimum active members before per-skill detail is exposed. Mirrors the
# existing skill-level min-n convention (outcome analytics suppress below 5).
MIN_ACTIVE_MEMBERS_FOR_SKILL_DETAIL = 5

SUPPLY_VERSION = "cohort-skill-supply-v1"
DEMO_ORIGIN = "demo_seeded"
DEMO_INSTITUTION_CODE = "INAURA-DEMO-TC"
DEMO_COURSE_CODE = "DEMO-FSWD"
DEMO_COHORT_CODE = "DEMO-FSWD-2026A"


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


def _is_unique_violation(e: Exception) -> bool:
    m = str(e).lower()
    return "duplicate key" in m or "23505" in m or "already exists" in m


def _duplicate(detail: str) -> HTTPException:
    return HTTPException(status_code=409, detail=detail)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_enum(value, allowed: frozenset, field: str) -> None:
    if value is not None and value not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {field}: {value!r}. Allowed: {sorted(allowed)}",
        )


# ---------------------------------------------------------------------------
# Cohorts
# ---------------------------------------------------------------------------

def _get_course(client: Client, course_id: str) -> dict:
    try:
        resp = client.table("courses").select("id,institution_id,name").eq("id", course_id).execute()
    except Exception as e:
        if _table_missing_msg(e):
            raise _missing_table()
        raise HTTPException(status_code=500, detail="Failed to validate course")
    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Course not found")
    return rows[0]


def create_cohort(payload: dict) -> dict:
    client = _ensure_client()
    institution_id = payload.get("institution_id")
    course_id = payload.get("course_id")
    if not institution_id or not course_id:
        raise HTTPException(status_code=400, detail="institution_id and course_id are required")
    course = _get_course(client, str(course_id))
    # Course/cohort consistency: the course must belong to the institution.
    if str(course.get("institution_id")) != str(institution_id):
        raise HTTPException(
            status_code=400,
            detail="Course does not belong to the given institution",
        )
    name = str(payload.get("name") or "").strip()
    if len(name) < 2 or len(name) > 200:
        raise HTTPException(status_code=400, detail="Cohort name must be 2–200 characters")
    _validate_enum(payload.get("status", "draft"), COHORT_STATUSES, "status")
    start, end = payload.get("start_date"), payload.get("end_date")
    if start and end and str(end) < str(start):
        raise HTTPException(status_code=400, detail="end_date must be on or after start_date")
    now = _now()
    row = {
        "institution_id": str(institution_id),
        "course_id": str(course_id),
        "name": name,
        "code": payload.get("code"),
        "start_date": start,
        "end_date": end,
        "academic_year": payload.get("academic_year"),
        "status": payload.get("status", "draft"),
        "data_origin": payload.get("data_origin", "source_data"),
        "created_at": now,
        "updated_at": now,
    }
    if row["data_origin"] not in ("source_data", "inaura_derived", "demo_seeded"):
        raise HTTPException(status_code=400, detail="Invalid data_origin")
    try:
        names = client.table("cohorts").select("id,name").eq("course_id", str(course_id)).execute()
    except Exception as e:
        if _table_missing_msg(e):
            raise _missing_table()
        raise HTTPException(status_code=500, detail="Failed to check duplicate cohort")
    for other in names.data or []:
        if str(other.get("name") or "").strip().lower() == name.lower():
            raise _duplicate("Duplicate cohort name in this course")
    try:
        resp = client.table("cohorts").insert(row).execute()
    except Exception as e:
        if _table_missing_msg(e):
            raise _missing_table()
        if _is_unique_violation(e):
            raise _duplicate("Duplicate cohort in this course")
        raise HTTPException(status_code=500, detail=f"Failed to create cohort: {str(e)[:200]}")
    created = (resp.data or [None])[0]
    if not created:
        raise HTTPException(status_code=500, detail="Failed to create cohort")
    return created


def get_cohort(cohort_id: str) -> dict:
    client = _ensure_client()
    try:
        resp = client.table("cohorts").select("*").eq("id", cohort_id).execute()
    except Exception as e:
        if _table_missing_msg(e):
            raise _missing_table()
        raise HTTPException(status_code=500, detail="Failed to fetch cohort")
    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Cohort not found")
    return rows[0]


def update_cohort(cohort_id: str, patch: dict) -> dict:
    client = _ensure_client()
    cohort = get_cohort(cohort_id)
    allowed = {"name", "code", "start_date", "end_date", "academic_year", "status"}
    clean = {k: v for k, v in (patch or {}).items() if k in allowed}
    if "name" in clean and not (2 <= len(str(clean["name"]).strip()) <= 200):
        raise HTTPException(status_code=400, detail="Cohort name must be 2–200 characters")
    _validate_enum(clean.get("status"), COHORT_STATUSES, "status")
    start = clean.get("start_date", cohort.get("start_date"))
    end = clean.get("end_date", cohort.get("end_date"))
    if start and end and str(end) < str(start):
        raise HTTPException(status_code=400, detail="end_date must be on or after start_date")
    if "name" in clean:
        try:
            siblings = client.table("cohorts").select("id,name").eq("course_id", cohort["course_id"]).execute()
        except Exception as e:
            if _table_missing_msg(e):
                raise _missing_table()
            raise HTTPException(status_code=500, detail="Failed to check duplicate cohort")
        for other in siblings.data or []:
            if str(other.get("id")) != str(cohort_id) and \
                    str(other.get("name") or "").strip().lower() == str(clean["name"]).strip().lower():
                raise _duplicate("Duplicate cohort name in this course")
    if not clean:
        return cohort
    clean["updated_at"] = _now()
    try:
        resp = client.table("cohorts").update(clean).eq("id", cohort_id).execute()
    except Exception as e:
        if _is_unique_violation(e):
            raise _duplicate("Duplicate cohort in this course")
        raise HTTPException(status_code=500, detail="Failed to update cohort")
    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Cohort not found")
    return rows[0]


def list_cohorts(course_id: str | None = None, institution_id: str | None = None,
                 status: str | None = None) -> list:
    client = _ensure_client()
    _validate_enum(status, COHORT_STATUSES, "status")
    try:
        query = client.table("cohorts").select("*")
        if course_id:
            query = query.eq("course_id", course_id)
        if institution_id:
            query = query.eq("institution_id", institution_id)
        if status:
            query = query.eq("status", status)
        resp = query.order("name").execute()
    except Exception as e:
        if _table_missing_msg(e):
            raise _missing_table()
        raise HTTPException(status_code=500, detail="Failed to list cohorts")
    return resp.data or []


# ---------------------------------------------------------------------------
# Membership (history-retained; leaving withdraws, never hard-deletes)
# ---------------------------------------------------------------------------

def add_member(cohort_id: str, user_id: str) -> dict:
    client = _ensure_client()
    get_cohort(cohort_id)
    user_id = str(user_id or "").strip()
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
    try:
        existing = client.table("cohort_members").select("id,enrollment_status").eq(
            "cohort_id", cohort_id).eq("user_id", user_id).execute()
    except Exception as e:
        if _table_missing_msg(e):
            raise _missing_table()
        raise HTTPException(status_code=500, detail="Failed to check duplicate membership")
    for row in existing.data or []:
        if row.get("enrollment_status") == "active":
            raise _duplicate("Student already has an active membership in this cohort")
    now = _now()
    try:
        resp = client.table("cohort_members").insert({
            "cohort_id": cohort_id,
            "user_id": user_id,
            "enrollment_status": "active",
            "joined_at": now,
            "created_at": now,
            "updated_at": now,
        }).execute()
    except Exception as e:
        if _table_missing_msg(e):
            raise _missing_table()
        if _is_unique_violation(e):
            raise _duplicate("Student already has an active membership in this cohort")
        raise HTTPException(status_code=500, detail=f"Failed to add member: {str(e)[:200]}")
    created = (resp.data or [None])[0]
    if not created:
        raise HTTPException(status_code=500, detail="Failed to add member")
    return created


def list_members(cohort_id: str, enrollment_status: str | None = None) -> list:
    client = _ensure_client()
    get_cohort(cohort_id)
    _validate_enum(enrollment_status, ENROLLMENT_STATUSES, "enrollment_status")
    try:
        query = client.table("cohort_members").select("*").eq("cohort_id", cohort_id)
        if enrollment_status:
            query = query.eq("enrollment_status", enrollment_status)
        resp = query.order("joined_at").execute()
    except Exception as e:
        if _table_missing_msg(e):
            raise _missing_table()
        raise HTTPException(status_code=500, detail="Failed to list members")
    return resp.data or []


def update_member(cohort_id: str, member_id: str, enrollment_status: str) -> dict:
    """Lifecycle transition (active/completed/withdrawn). History is retained."""
    client = _ensure_client()
    get_cohort(cohort_id)
    _validate_enum(enrollment_status, ENROLLMENT_STATUSES, "enrollment_status")
    if not enrollment_status:
        raise HTTPException(status_code=400, detail="enrollment_status is required")
    try:
        resp = client.table("cohort_members").select("*").eq("id", member_id).eq(
            "cohort_id", cohort_id).execute()
    except Exception as e:
        if _table_missing_msg(e):
            raise _missing_table()
        raise HTTPException(status_code=500, detail="Failed to fetch member")
    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Cohort member not found")
    patch: dict = {"enrollment_status": enrollment_status, "updated_at": _now()}
    if enrollment_status in ("completed", "withdrawn") and not rows[0].get("exited_at"):
        patch["exited_at"] = _now()
    if enrollment_status == "active":
        patch["exited_at"] = None
        try:
            dupes = client.table("cohort_members").select("id").eq(
                "cohort_id", cohort_id).eq("user_id", rows[0]["user_id"]).eq(
                "enrollment_status", "active").execute()
        except Exception as e:
            if _table_missing_msg(e):
                raise _missing_table()
            raise HTTPException(status_code=500, detail="Failed to check duplicate membership")
        if [d for d in (dupes.data or []) if str(d.get("id")) != str(member_id)]:
            raise _duplicate("Student already has an active membership in this cohort")
    try:
        updated = client.table("cohort_members").update(patch).eq("id", member_id).execute()
    except Exception as e:
        if _is_unique_violation(e):
            raise _duplicate("Student already has an active membership in this cohort")
        raise HTTPException(status_code=500, detail="Failed to update member")
    out = (updated.data or [None])[0]
    if not out:
        raise HTTPException(status_code=404, detail="Cohort member not found")
    return out


def remove_member(cohort_id: str, member_id: str) -> None:
    """Withdraw a member (soft). History rows are never hard-deleted by the API."""
    update_member(cohort_id, member_id, "withdrawn")


# ---------------------------------------------------------------------------
# Skill-supply aggregation over existing evidence
# ---------------------------------------------------------------------------

def _load_skills_lookup(client: Client) -> dict:
    try:
        resp = client.table("skills").select("id,canonical_name,display_name,category").execute()
    except Exception as e:
        if _table_missing_msg(e):
            raise _missing_table()
        raise HTTPException(status_code=500, detail="Failed to load skill taxonomy")
    lookup = {}
    for row in resp.data or []:
        lookup[str(row.get("id"))] = {
            "slug": str(row.get("canonical_name") or ""),
            "display": str(row.get("display_name") or row.get("canonical_name") or ""),
            "category": row.get("category"),
        }
    return lookup


def _load_member_skill_data(client: Client, user_ids: list) -> tuple[dict, dict]:
    """Load existing skill_signals + skill_assessments rows for members.

    Returns (signals_by_user, assessments_by_user). Raises 503/500 like the
    rest of the service; never synthesizes skill state.
    """
    signals_by_user: dict[str, list] = {u: [] for u in user_ids}
    assessments_by_user: dict[str, list] = {u: [] for u in user_ids}
    if not user_ids:
        return signals_by_user, assessments_by_user
    try:
        sresp = client.table("skill_signals").select("*").in_("user_id", user_ids).execute()
    except Exception as e:
        if _table_missing_msg(e):
            raise _missing_table()
        raise HTTPException(status_code=500, detail="Failed to load member skill signals")
    for row in sresp.data or []:
        signals_by_user.setdefault(str(row.get("user_id")), []).append(row)
    try:
        aresp = client.table("skill_assessments").select("*").in_("user_id", user_ids).execute()
    except Exception as e:
        if _table_missing_msg(e):
            raise _missing_table()
        raise HTTPException(status_code=500, detail="Failed to load member skill assessments")
    for row in aresp.data or []:
        assessments_by_user.setdefault(str(row.get("user_id")), []).append(row)
    return signals_by_user, assessments_by_user


def _signal_source_key(row: dict) -> str:
    return str(row.get("source") or row.get("source_type") or "unknown").strip().lower()


def _signal_strength(row: dict) -> float:
    try:
        return max(0.0, min(1.0, float(row.get("signal_strength", row.get("signal_value", 0.0)) or 0.0)))
    except (TypeError, ValueError):
        return 0.0


def _aggregate_skills(active_user_ids: list, signals_by_user: dict,
                      assessments_by_user: dict, lookup: dict) -> tuple[list, list]:
    """Aggregate per-member skill state into cohort supply rows.

    Returns (skills, unmapped_concepts). Deterministic: sorted by
    evidenced_member_count desc, slug asc. No user_ids or per-member evidence
    leak into the output.
    """
    per_skill: dict[str, dict] = {}
    unmapped: dict[str, dict] = {}

    def _skill_entry(slug: str, display: str, category) -> dict:
        entry = per_skill.get(slug)
        if entry is None:
            entry = per_skill[slug] = {
                "slug": slug, "display": display, "category": category,
                "assessed": set(), "evidenced": {}, "verified": set(),
                "source_members": {}, "tier_members": {},
                "qualifying_signals": 0, "evidence_counts": [],
            }
        return entry

    for uid in active_user_ids:
        member_signals: dict[str, list] = {}
        for sig in signals_by_user.get(uid, []):
            sid = str(sig.get("skill_id") or "")
            info = lookup.get(sid)
            if info is None or not info["slug"]:
                bucket = unmapped.setdefault(sid or "unknown", {"members": set(), "signals": 0})
                bucket["members"].add(uid)
                bucket["signals"] += 1
                continue
            member_signals.setdefault(info["slug"], []).append(sig)
        member_assessments: dict[str, dict] = {}
        for arow in assessments_by_user.get(uid, []):
            sid = str(arow.get("skill_id") or "")
            info = lookup.get(sid)
            if info is None or not info["slug"]:
                bucket = unmapped.setdefault(sid or "unknown", {"members": set(), "signals": 0})
                bucket["members"].add(uid)
                continue
            member_assessments[info["slug"]] = arow

        for slug, sigs in member_signals.items():
            info = next((lookup[sid] for sid in lookup if lookup[sid]["slug"] == slug),
                        {"display": slug, "category": None})
            entry = _skill_entry(slug, info["display"], info["category"])
            entry["assessed"].add(uid)
            qualifying = [s for s in sigs if ew.tier_of(_signal_source_key(s)) in QUALIFYING_TIERS]
            has_row = slug in member_assessments
            if qualifying or has_row:
                entry["evidenced"][uid] = (sigs, member_assessments.get(slug))
                entry["qualifying_signals"] += len(qualifying)
            if ew.has_direct_validation(sigs):
                entry["verified"].add(uid)
            for s in sigs:
                src = _signal_source_key(s)
                entry["source_members"].setdefault(src, set()).add(uid)
                entry["tier_members"].setdefault(ew.tier_of(src), set()).add(uid)
        for slug, arow in member_assessments.items():
            if slug not in member_signals:
                info = next((lookup[sid] for sid in lookup if lookup[sid]["slug"] == slug),
                            {"display": slug, "category": None})
                entry = _skill_entry(slug, info["display"], info["category"])
                entry["assessed"].add(uid)
                entry["evidenced"][uid] = ([], arow)

    n = len(active_user_ids)
    skills = []
    for slug, e in per_skill.items():
        profs, confs = [], []
        for uid, (sigs, arow) in e["evidenced"].items():
            if sigs:
                prof, _, _, _, _ = engine.proficiency_with_prior(sigs)
                conf, _, _, _ = engine.confidence_from_signals(sigs)
            else:
                try:
                    prof = max(0.0, min(1.0, float(arow.get("proficiency", 0.0) or 0.0)))
                except (TypeError, ValueError):
                    prof = 0.0
                try:
                    conf = max(0.0, min(1.0, float(arow.get("confidence", 0.0) or 0.0)))
                except (TypeError, ValueError):
                    conf = 0.0
            profs.append(prof)
            confs.append(conf)
            if arow is not None:
                try:
                    e["evidence_counts"].append(int(arow.get("evidence_count", 0) or 0))
                except (TypeError, ValueError):
                    pass
        evidenced_n = len(e["evidenced"])
        verified_n = len(e["verified"])
        skills.append({
            "skill": slug,
            "display_name": e["display"],
            "category": e["category"],
            "cohort_size": n,
            "assessed_member_count": len(e["assessed"]),
            "evidenced_member_count": evidenced_n,
            "verified_member_count": verified_n,
            "skill_coverage": round(evidenced_n / n, 4) if n else 0.0,
            "verified_coverage": round(verified_n / n, 4) if n else 0.0,
            "average_proficiency": round(sum(profs) / len(profs), 4) if profs else None,
            "median_proficiency": round(median(profs), 4) if profs else None,
            "min_proficiency": round(min(profs), 4) if profs else None,
            "max_proficiency": round(max(profs), 4) if profs else None,
            "average_confidence": round(sum(confs) / len(confs), 4) if confs else None,
            "verification_rate": round(verified_n / evidenced_n, 4) if evidenced_n else None,
            "qualifying_signal_count": e["qualifying_signals"],
            "average_evidence_count": (
                round(sum(e["evidence_counts"]) / len(e["evidence_counts"]), 2)
                if e["evidence_counts"] else None),
            "source_distribution": {k: len(v) for k, v in sorted(e["source_members"].items())},
            "tier_distribution": {k: len(v) for k, v in sorted(e["tier_members"].items())},
        })
    skills.sort(key=lambda s: (-s["evidenced_member_count"], s["skill"]))

    unmapped_list = [
        {"skill_id": sid, "member_count": len(b["members"]), "signal_count": b["signals"]}
        for sid, b in sorted(unmapped.items())
    ]
    return skills, unmapped_list


def get_cohort_skill_supply(cohort_id: str) -> dict:
    """Cohort skill supply: aggregates only, never per-member evidence."""
    client = _ensure_client()
    cohort = get_cohort(cohort_id)
    members = list_members(cohort_id)
    counts = {"active": 0, "completed": 0, "withdrawn": 0}
    for m in members:
        st = str(m.get("enrollment_status") or "")
        if st in counts:
            counts[st] += 1
    active_ids = [str(m.get("user_id")) for m in members if m.get("enrollment_status") == "active"]

    course = _get_course(client, str(cohort["course_id"]))
    institution_name = None
    try:
        iresp = client.table("institutions").select("id,name").eq("id", cohort["institution_id"]).execute()
        if iresp.data:
            institution_name = iresp.data[0].get("name")
    except Exception as e:
        if _table_missing_msg(e):
            raise _missing_table()

    base = {
        "cohort": {"id": cohort["id"], "name": cohort.get("name"), "code": cohort.get("code"),
                   "status": cohort.get("status"), "data_origin": cohort.get("data_origin")},
        "course": {"id": course["id"], "name": course.get("name")},
        "institution": {"id": cohort["institution_id"], "name": institution_name},
        "member_count": len(active_ids),
        "membership_counts": counts,
        "min_members_for_detail": MIN_ACTIVE_MEMBERS_FOR_SKILL_DETAIL,
    }
    if not active_ids:
        return {**base, "suppressed": False, "skills": [], "unmapped_concepts": [],
                "provenance": _provenance(0, 0),
                "note": "Cohort has no active members; no supply to aggregate."}
    if len(active_ids) < MIN_ACTIVE_MEMBERS_FOR_SKILL_DETAIL:
        return {**base, "suppressed": True, "skills": [], "unmapped_concepts": [],
                "provenance": _provenance(len(active_ids), 0),
                "note": (f"Per-skill detail suppressed: {len(active_ids)} active members is below "
                         f"the minimum of {MIN_ACTIVE_MEMBERS_FOR_SKILL_DETAIL} for aggregate analytics.")}

    lookup = _load_skills_lookup(client)
    signals_by_user, assessments_by_user = _load_member_skill_data(client, active_ids)
    skills, unmapped = _aggregate_skills(active_ids, signals_by_user, assessments_by_user, lookup)
    total_signals = sum(len(v) for v in signals_by_user.values())
    total_assessments = sum(len(v) for v in assessments_by_user.values())
    return {**base, "suppressed": False, "skills": skills, "unmapped_concepts": unmapped,
            "provenance": _provenance(total_signals, total_assessments), "note": ""}


def get_course_cohort_supply(course_id: str) -> dict:
    """Combined supply across all cohorts of a course (members deduped)."""
    client = _ensure_client()
    course = _get_course(client, str(course_id))
    cohorts = list_cohorts(course_id=str(course_id))
    member_ids: list[str] = []
    seen: set[str] = set()
    cohort_summaries = []
    for c in cohorts:
        members = list_members(str(c.get("id")), enrollment_status="active")
        ids = [str(m.get("user_id")) for m in members]
        cohort_summaries.append({"cohort_id": c.get("id"), "cohort_name": c.get("name"),
                                 "member_count": len(ids)})
        for uid in ids:
            if uid not in seen:
                seen.add(uid)
                member_ids.append(uid)
    base = {
        "course": {"id": course["id"], "name": course.get("name")},
        "cohorts": cohort_summaries,
        "member_count": len(member_ids),
        "min_members_for_detail": MIN_ACTIVE_MEMBERS_FOR_SKILL_DETAIL,
    }
    if not member_ids:
        return {**base, "suppressed": False, "skills": [], "unmapped_concepts": [],
                "provenance": _provenance(0, 0),
                "note": "No active cohort members in this course."}
    if len(member_ids) < MIN_ACTIVE_MEMBERS_FOR_SKILL_DETAIL:
        return {**base, "suppressed": True, "skills": [], "unmapped_concepts": [],
                "provenance": _provenance(len(member_ids), 0),
                "note": "Per-skill detail suppressed below the minimum cohort size."}
    lookup = _load_skills_lookup(client)
    signals_by_user, assessments_by_user = _load_member_skill_data(client, member_ids)
    skills, unmapped = _aggregate_skills(member_ids, signals_by_user, assessments_by_user, lookup)
    return {**base, "suppressed": False, "skills": skills, "unmapped_concepts": unmapped,
            "provenance": _provenance(
                sum(len(v) for v in signals_by_user.values()),
                sum(len(v) for v in assessments_by_user.values())), "note": ""}


def _provenance(signal_count: int, assessment_count: int) -> dict:
    return {
        "source": SUPPLY_VERSION,
        "supply_type": "verified_learner_supply",
        "member_signal_rows": signal_count,
        "member_assessment_rows": assessment_count,
        "note": ("Derived live from existing student evidence (skill_signals / "
                 "skill_assessments). Not demand; self-reported-only skills excluded."),
    }


# ---------------------------------------------------------------------------
# Deterministic demo seed (synthetic — never real students or cohorts)
# ---------------------------------------------------------------------------

def _demo_user(n: int) -> str:
    return str(uuid5(NAMESPACE_DNS, f"demo-student-{n}@example.invalid"))


def build_demo_seed() -> dict:
    """Pure deterministic demo graph: one cohort under the P0#2 demo course,
    six synthetic members, and skill signals across real evidence tiers
    (github/project/leetcode/kaggle/certification/assessment plus
    self-reported-only controls). No assessment rows are fabricated."""
    from .evidence_weights import SOURCE_RELIABILITY

    def _sig(user_n: int, slug: str, source: str, value: float) -> dict:
        return {"demo_user_n": user_n, "skill_slug": slug, "source_type": source,
                "signal_value": value, "source_reliability": SOURCE_RELIABILITY[source],
                "metadata": {"demo_seeded": True}}

    return {
        "cohort": {
            "code": DEMO_COHORT_CODE,
            "name": "Full Stack Web Development — Batch 2026-A",
            "academic_year": "2026",
            "status": "active",
            "data_origin": DEMO_ORIGIN,
        },
        "member_ns": [1, 2, 3, 4, 5, 6],
        "signals": [
            _sig(1, "react", "github", 0.70), _sig(1, "react", "project", 0.60),
            _sig(2, "react", "github", 0.80), _sig(2, "react", "assessment", 0.85),
            _sig(3, "react", "leetcode", 0.70),
            _sig(4, "react", "assessment", 0.90),
            _sig(5, "react", "self_declared", 0.60),
            _sig(6, "react", "resume", 0.50),
            _sig(1, "python", "assessment", 0.80),
            _sig(2, "python", "kaggle", 0.75),
            _sig(3, "python", "github", 0.60),
            _sig(4, "python", "self_declared", 0.50),
            _sig(6, "python", "certification", 0.60),
            _sig(2, "sql", "project", 0.50),
            _sig(3, "sql", "project", 0.55),
            _sig(5, "sql", "github", 0.40),
        ],
    }


def seed_demo_data() -> dict:
    """Idempotent demo import. Requires the P0#2 demo institution/course;
    synthetic member user_ids are uuid5 (cannot collide with real users)."""
    client = _ensure_client()
    try:
        iresp = client.table("institutions").select("id").eq("code", DEMO_INSTITUTION_CODE).execute()
        cresp = client.table("courses").select("id,institution_id").eq("code", DEMO_COURSE_CODE).execute()
    except Exception as e:
        if _table_missing_msg(e):
            raise _missing_table()
        raise HTTPException(status_code=500, detail="Failed to locate P0#2 demo data")
    if not (iresp.data and cresp.data):
        raise HTTPException(
            status_code=404,
            detail="P0#2 demo institution/course not found — seed the institution demo first",
        )
    institution_id = iresp.data[0]["id"]
    course = cresp.data[0]
    if str(course.get("institution_id")) != str(institution_id):
        raise HTTPException(status_code=500, detail="P0#2 demo course/institution mismatch")

    seed = build_demo_seed()
    created = {"cohorts": 0, "members": 0, "signals": 0}
    skipped = {"cohorts": 0, "members": 0, "signals": 0}

    try:
        cfound = client.table("cohorts").select("*").eq("code", DEMO_COHORT_CODE).execute()
    except Exception as e:
        if _table_missing_msg(e):
            raise _missing_table()
        raise HTTPException(status_code=500, detail="Failed to check demo cohort")
    if cfound.data:
        cohort = cfound.data[0]
        skipped["cohorts"] += 1
    else:
        cohort = create_cohort({
            "institution_id": institution_id, "course_id": course["id"],
            **seed["cohort"],
        })
        created["cohorts"] += 1

    try:
        slookup = client.table("skills").select("id,canonical_name").execute()
    except Exception as e:
        if _table_missing_msg(e):
            raise _missing_table()
        raise HTTPException(status_code=500, detail="Failed to load skill taxonomy")
    slug_to_id = {str(r.get("canonical_name")): str(r.get("id")) for r in (slookup.data or [])}

    user_ids = [_demo_user(n) for n in seed["member_ns"]]
    for uid in user_ids:
        try:
            add_member(str(cohort["id"]), uid)
            created["members"] += 1
        except HTTPException as e:
            if e.status_code == 409:
                skipped["members"] += 1
            else:
                raise
    try:
        existing = client.table("skill_signals").select(
            "user_id,skill_id,source_type").in_("user_id", user_ids).execute()
    except Exception as e:
        if _table_missing_msg(e):
            raise _missing_table()
        raise HTTPException(status_code=500, detail="Failed to check demo signals")
    have = {(str(r.get("user_id")), str(r.get("skill_id")),
             str(r.get("source_type") or "").lower()) for r in (existing.data or [])}
    new_rows = []
    for sig in seed["signals"]:
        uid = _demo_user(sig["demo_user_n"])
        sid = slug_to_id.get(sig["skill_slug"])
        if sid is None:
            continue
        key = (uid, sid, sig["source_type"])
        if key in have:
            skipped["signals"] += 1
            continue
        have.add(key)
        meta = dict(sig.get("metadata") or {})
        meta["demo_seeded"] = True
        new_rows.append({
            "user_id": uid, "skill_id": sid, "source_type": sig["source_type"],
            "signal_value": sig["signal_value"],
            "source_reliability": sig["source_reliability"],
            "explanation": "Synthetic demo evidence for cohort-supply plumbing; not a real learner.",
            "metadata": meta,
        })
    if new_rows:
        try:
            client.table("skill_signals").insert(new_rows).execute()
        except Exception as e:
            if _table_missing_msg(e):
                raise _missing_table()
            raise HTTPException(status_code=500, detail="Failed to seed demo signals")
        created["signals"] += len(new_rows)
    return {"created": created, "skipped": skipped, "cohort_id": cohort["id"],
            "data_origin": DEMO_ORIGIN}
