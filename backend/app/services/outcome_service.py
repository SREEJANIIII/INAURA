"""Person 2: outcome service — applications, events, feedback, placements,
alignments, dashboard, industry signals.

Isolated from INAURA core. Reads skills/evidence/certifications for validation
and skill_gaps/assessments for dashboard display only. Never writes core tables.
"""

from fastapi import HTTPException
from supabase import Client
from datetime import datetime, timezone
from . import employer_service as emp
from ..core.supabase import get_supabase_client


def _ensure_client() -> Client:
    client = get_supabase_client()
    if client is None:
        raise HTTPException(
            status_code=503,
            detail="Supabase not configured — set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in backend/.env",
        )
    return client


def _missing(e: Exception) -> bool:
    m = str(e).lower()
    return "could not find table" in m or "pgrst205" in m


# ---------------------------------------------------------------------------
# Application lifecycle matrix: from_status -> {to_status: actor_type}
# actor_type: "student" | "employer"
# ---------------------------------------------------------------------------
TRANSITIONS: dict[str, dict[str, str]] = {
    "saved": {"applied": "student", "withdrawn": "student"},
    "applied": {"screening": "employer", "rejected": "employer", "withdrawn": "student"},
    "screening": {"interview": "employer", "rejected": "employer", "withdrawn": "student"},
    "interview": {
        "offer_received": "employer",
        "selected": "employer",
        "rejected": "employer",
        "withdrawn": "student",
    },
    "offer_received": {"selected": "employer", "rejected": "employer", "withdrawn": "student"},
    "selected": {},
    "rejected": {},
    "withdrawn": {},
}

TERMINAL = {"selected", "rejected", "withdrawn"}


def _outcome_for(from_status: str, to_status: str) -> tuple[str | None, bool]:
    """Returns (outcome, decided). Terminal outcomes set decided_at."""
    if to_status == "selected":
        return "selected", True
    if to_status == "rejected":
        return "rejected", True
    if to_status == "withdrawn":
        if from_status == "offer_received":
            return "declined_offer", True
        return "withdrawn", True
    return "pending", False


def _get_application(app_id: str) -> dict:
    client = _ensure_client()
    try:
        resp = client.table("applications").select("*").eq("id", app_id).execute()
    except Exception as e:
        if _missing(e):
            raise HTTPException(status_code=503, detail="Person 2 tables missing — run backend/supabase/027_outcomes.sql")
        raise HTTPException(status_code=500, detail="Failed to fetch application")
    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Application not found")
    return rows[0]


def _actor_type_for(app: dict, actor_id: str) -> str | None:
    if app.get("student_id") == actor_id:
        return "student"
    req = emp._requirement_employer(app["hiring_requirement_id"])
    m = emp.get_membership(actor_id, req["employer_id"])
    if m:
        return "employer"
    return None


def _attach_employer_ids(apps: list) -> list:
    """Derive employer_id via hiring_requirements join (no stored duplicate)."""
    if not apps:
        return apps
    client = _ensure_client()
    req_ids = list({a["hiring_requirement_id"] for a in apps})
    try:
        rresp = client.table("hiring_requirements").select("id,employer_id,title").in_("id", req_ids).execute()
    except Exception:
        return apps
    req_map = {r["id"]: r for r in (rresp.data or [])}
    emp_ids = list({r["employer_id"] for r in (rresp.data or []) if r.get("employer_id")})
    emp_name_map = {}
    if emp_ids:
        try:
            eresp = client.table("employers").select("id,name").in_("id", emp_ids).execute()
            emp_name_map = {e["id"]: e["name"] for e in (eresp.data or [])}
        except Exception:
            pass
    for a in apps:
        r = req_map.get(a["hiring_requirement_id"])
        if r:
            a["employer_id"] = r.get("employer_id")
            a["requirement_title"] = r.get("title")
            if r.get("employer_id"):
                a["employer_name"] = emp_name_map.get(r["employer_id"])
    return apps


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

def create_application(student_id: str, hiring_requirement_id: str, initial_status: str = "applied", note: str | None = None) -> dict:
    client = _ensure_client()
    req = emp._requirement_employer(hiring_requirement_id)
    if req.get("status") != "open":
        raise HTTPException(status_code=400, detail="Requirement is not open for applications")
    if initial_status not in ("saved", "applied"):
        raise HTTPException(status_code=400, detail="initial_status must be 'saved' or 'applied'")
    now = datetime.now(timezone.utc).isoformat()
    try:
        existing = client.table("applications").select("*").eq("student_id", student_id).eq(
            "hiring_requirement_id", hiring_requirement_id).execute()
        if existing.data:
            existing_row = existing.data[0]
            if existing_row.get("status") == "saved" and initial_status == "applied":
                return transition_status(existing_row["id"], student_id, "applied", note=note or "Applied")
            raise HTTPException(status_code=400, detail="Already applied to this requirement")
        is_applied = (initial_status == "applied")
        resp = client.table("applications").insert({
            "student_id": student_id,
            "hiring_requirement_id": hiring_requirement_id,
            "status": initial_status,
            "outcome": "pending" if is_applied else None,
            "applied_at": now if is_applied else None,
            "created_at": now,
            "updated_at": now,
        }).execute()
    except HTTPException:
        raise
    except Exception as e:
        if _missing(e):
            raise HTTPException(status_code=503, detail="Person 2 tables missing — run backend/supabase/027_outcomes.sql")
        raise HTTPException(status_code=500, detail=f"Failed to create application: {str(e)[:200]}")
    row = (resp.data or [None])[0]
    if not row:
        raise HTTPException(status_code=500, detail="Failed to create application")
    try:
        ev_note = note or ("Applied" if initial_status == "applied" else "Saved")
        client.table("application_events").insert({
            "application_id": row["id"], "from_status": None,
            "to_status": initial_status, "actor": student_id, "note": ev_note,
        }).execute()
    except Exception:
        pass
    row["employer_id"] = req["employer_id"]
    row["requirement_title"] = req.get("title")
    return row


def list_applications(student_id: str, status: str | None = None) -> list:
    client = _ensure_client()
    try:
        q = client.table("applications").select("*").eq("student_id", student_id)
        if status:
            q = q.eq("status", status)
        resp = q.execute()
    except Exception as e:
        if _missing(e):
            raise HTTPException(status_code=503, detail="Person 2 tables missing — run backend/supabase/027_outcomes.sql")
        raise HTTPException(status_code=500, detail="Failed to list applications")
    return _attach_employer_ids(resp.data or [])


def list_applications_for_employer(user_id: str, employer_id: str) -> list:
    emp.require_employer_access(user_id, employer_id, roles=("owner", "member"))
    client = _ensure_client()
    try:
        rresp = client.table("hiring_requirements").select("id,title").eq("employer_id", employer_id).execute()
        reqs = rresp.data or []
        if not reqs:
            return []
        req_map = {r["id"]: r.get("title") for r in reqs}
        req_ids = list(req_map.keys())
        aresp = client.table("applications").select("*").in_("hiring_requirement_id", req_ids).execute()
        rows = aresp.data or []
        for r in rows:
            r["employer_id"] = employer_id
            r["requirement_title"] = req_map.get(r["hiring_requirement_id"])
        return rows
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to list employer applications")


def list_applications_for_requirement(user_id: str, requirement_id: str) -> list:
    req = emp._requirement_employer(requirement_id)
    emp.require_employer_access(user_id, req["employer_id"], roles=("owner", "member"))
    client = _ensure_client()
    try:
        aresp = client.table("applications").select("*").eq("hiring_requirement_id", requirement_id).execute()
        rows = aresp.data or []
        for r in rows:
            r["employer_id"] = req["employer_id"]
            r["requirement_title"] = req.get("title")
        return rows
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to list requirement applications")


def get_application_detail(user_id: str, app_id: str) -> dict:
    app = _get_application(app_id)
    actor = _actor_type_for(app, user_id)
    if not actor:
        raise HTTPException(status_code=404, detail="Application not found")
    client = _ensure_client()
    try:
        eresp = client.table("application_events").select("*").eq("application_id", app_id).order("created_at").execute()
    except Exception:
        eresp = None
    req = emp._requirement_employer(app["hiring_requirement_id"])
    app["employer_id"] = req["employer_id"]
    app["requirement_title"] = req.get("title")
    app["events"] = (eresp.data if eresp else []) or []
    return app



def transition_status(app_id: str, actor_id: str, to_status: str, note: str | None = None) -> dict:
    app = _get_application(app_id)
    from_status = app["status"]
    if from_status in TERMINAL:
        raise HTTPException(status_code=400, detail=f"Application is terminal ({from_status}) and cannot transition")
    allowed = TRANSITIONS.get(from_status, {})
    if to_status not in allowed:
        raise HTTPException(status_code=400, detail=f"Invalid transition {from_status} -> {to_status}")
    required_actor = allowed[to_status]
    actual_actor = _actor_type_for(app, actor_id)
    if not actual_actor:
        raise HTTPException(status_code=404, detail="Application not found")
    if actual_actor != required_actor:
        raise HTTPException(
            status_code=403,
            detail=f"Transition {from_status} -> {to_status} is {required_actor}-controlled",
        )
    outcome, decided = _outcome_for(from_status, to_status)
    now = datetime.now(timezone.utc).isoformat()
    update: dict = {"status": to_status, "updated_at": now}
    if to_status == "applied" and not app.get("applied_at"):
        update["applied_at"] = now
    if decided:
        update["outcome"] = outcome
        update["outcome_decided_at"] = now
    elif outcome == "pending" and not app.get("outcome"):
        update["outcome"] = "pending"
    client = _ensure_client()
    try:
        client.table("application_events").insert({
            "application_id": app_id, "from_status": from_status,
            "to_status": to_status, "actor": actor_id, "note": note,
        }).execute()
        resp = client.table("applications").update(update).eq("id", app_id).execute()
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to transition application")
    rows = resp.data or []
    row = rows[0] if rows else {**app, **update}
    req = emp._requirement_employer(row["hiring_requirement_id"])
    row["employer_id"] = req["employer_id"]
    return row


# ---------------------------------------------------------------------------
# Employer feedback (one summative record per application)
# ---------------------------------------------------------------------------

def _feedback_access(app: dict, user_id: str) -> str:
    """Returns 'employer' or 'student' if access granted, else raises 404."""
    if app.get("student_id") == user_id:
        return "student"
    req = emp._requirement_employer(app["hiring_requirement_id"])
    m = emp.get_membership(user_id, req["employer_id"])
    if m:
        return "employer"
    raise HTTPException(status_code=404, detail="Application not found")


def submit_feedback(user_id: str, app_id: str, payload: dict) -> dict:
    app = _get_application(app_id)
    req = emp._requirement_employer(app["hiring_requirement_id"])
    emp.require_employer_access(user_id, req["employer_id"], roles=("owner", "member"))
    if app["status"] not in ("interview", "offer_received", "selected", "rejected"):
        raise HTTPException(status_code=400, detail="Feedback requires an interview interaction first")
    ratings = [payload.get(k) for k in (
        "technical_ability", "communication", "problem_solving",
        "project_readiness", "role_readiness", "overall_rating")]
    skills = payload.get("skills") or []
    if not any(r is not None for r in ratings) and not skills and not payload.get("overall_comment") and not payload.get("interview_summary"):
        raise HTTPException(status_code=400, detail="Feedback is empty — provide a rating, skill observation, or comment")
    client = _ensure_client()
    try:
        erecheck = client.table("employer_feedback").select("id").eq("application_id", app_id).execute()
        if erecheck.data:
            raise HTTPException(status_code=400, detail="Feedback already submitted for this application")
        # Proficiency validation
        for s in skills:
            exp = s.get("expected_level")
            obs = s.get("observed_level")
            if exp is not None and not (0.0 <= float(exp) <= 1.0):
                raise HTTPException(status_code=400, detail="expected_level must be between 0.0 and 1.0")
            if obs is not None and not (0.0 <= float(obs) <= 1.0):
                raise HTTPException(status_code=400, detail="observed_level must be between 0.0 and 1.0")
        # Canonical skills validation & skill name mapping
        skill_name_map = {}
        for s in skills:
            sresp = client.table("skills").select("id,display_name,canonical_name").eq("id", str(s["skill_id"])).execute()
            sdata = sresp.data or []
            if not sdata:
                raise HTTPException(status_code=400, detail=f"Unknown skill_id: {s['skill_id']}")
            skill_name_map[str(s["skill_id"])] = sdata[0].get("display_name") or sdata[0].get("canonical_name") or str(s["skill_id"])
        # Requirement-skills linkage: if requirement has specific attached skills, validate linkage
        try:
            req_skills_resp = client.table("hiring_requirement_skills").select("skill_id").eq("hiring_requirement_id", app["hiring_requirement_id"]).execute()
            req_skill_ids = {str(r["skill_id"]) for r in (req_skills_resp.data or []) if r.get("skill_id")}
            if req_skill_ids:
                for s in skills:
                    if str(s["skill_id"]) not in req_skill_ids:
                        raise HTTPException(status_code=400, detail=f"Skill {s['skill_id']} is not linked to this hiring requirement")
        except HTTPException:
            raise
        except Exception:
            pass
        now = datetime.now(timezone.utc).isoformat()
        fresp = client.table("employer_feedback").insert({
            "employer_id": req["employer_id"],
            "application_id": app_id,
            "student_id": app["student_id"],
            "technical_ability": payload.get("technical_ability"),
            "communication": payload.get("communication"),
            "problem_solving": payload.get("problem_solving"),
            "project_readiness": payload.get("project_readiness"),
            "role_readiness": payload.get("role_readiness"),
            "overall_rating": payload.get("overall_rating"),
            "interview_summary": payload.get("interview_summary"),
            "overall_comment": payload.get("overall_comment"),
            "status": "submitted",
            "created_by": user_id,
            "created_at": now,
            "updated_at": now,
        }).execute()
    except HTTPException:
        raise
    except Exception as e:
        if _missing(e):
            raise HTTPException(status_code=503, detail="Person 2 tables missing — run backend/supabase/027_outcomes.sql")
        raise HTTPException(status_code=500, detail=f"Failed to submit feedback: {str(e)[:200]}")
    frows = fresp.data or []
    if not frows:
        raise HTTPException(status_code=500, detail="Failed to submit feedback")
    fb = frows[0]
    skill_rows = []
    if skills:
        try:
            to_insert = [{
                "employer_feedback_id": fb["id"],
                "skill_id": str(s["skill_id"]),
                "expected_level": s.get("expected_level"),
                "observed_level": s.get("observed_level"),
                "comment": s.get("comment"),
            } for s in skills]
            sresp = client.table("employer_skill_feedback").insert(to_insert).execute()
            skill_rows = sresp.data or []
        except Exception:
            raise HTTPException(status_code=500, detail="Feedback saved but skill rows failed — retry with skills omitted")
    for r in skill_rows:
        exp, obs = r.get("expected_level"), r.get("observed_level")
        r["skill_gap"] = (exp - obs) if exp is not None and obs is not None else None
        r["skill_name"] = skill_name_map.get(str(r.get("skill_id")))
    fb["skills"] = skill_rows
    return fb


def get_feedback(user_id: str, app_id: str) -> dict:
    app = _get_application(app_id)
    _feedback_access(app, user_id)
    client = _ensure_client()
    try:
        fresp = client.table("employer_feedback").select("*").eq("application_id", app_id).execute()
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to fetch feedback")
    frows = fresp.data or []
    if not frows:
        raise HTTPException(status_code=404, detail="No feedback for this application")
    fb = frows[0]
    try:
        sresp = client.table("employer_skill_feedback").select("*").eq("employer_feedback_id", fb["id"]).execute()
        skill_rows = sresp.data or []
    except Exception:
        skill_rows = []
    skill_ids = list({str(r["skill_id"]) for r in skill_rows if r.get("skill_id")})
    skill_name_map = {}
    if skill_ids:
        try:
            snames = client.table("skills").select("id,display_name,canonical_name").in_("id", skill_ids).execute()
            for s in (snames.data or []):
                skill_name_map[str(s["id"])] = s.get("display_name") or s.get("canonical_name") or str(s["id"])
        except Exception:
            pass
    for r in skill_rows:
        exp, obs = r.get("expected_level"), r.get("observed_level")
        r["skill_gap"] = (exp - obs) if exp is not None and obs is not None else None
        r["skill_name"] = skill_name_map.get(str(r.get("skill_id")))
    fb["skills"] = skill_rows
    return fb


# ---------------------------------------------------------------------------
# Placements & Joining Tracking
# ---------------------------------------------------------------------------

PLACEMENT_TRANSITIONS: dict[str, dict[str, str]] = {
    "offer_accepted": {
        "joined": "any",          # student or employer can record joining
        "declined": "student",     # student declines offer
        "not_joined": "employer",  # employer marks no-show
    },
    "selected": {
        "offer_accepted": "student", # student accepts offer
        "joined": "any",             # joined directly
        "declined": "student",        # student declines
        "not_joined": "employer",     # employer marks candidate didn't join
    },
    "joined": {},      # terminal
    "declined": {},    # terminal
    "not_joined": {},  # terminal
}

PLACEMENT_TERMINAL = {"joined", "declined", "not_joined"}


def _attach_placement_metadata(rows: list) -> list:
    """Attach employer_name and requirement_title to placement rows."""
    if not rows:
        return rows
    client = _ensure_client()
    emp_ids = list({str(r["employer_id"]) for r in rows if r.get("employer_id")})
    app_ids = list({str(r["application_id"]) for r in rows if r.get("application_id")})
    emp_map = {}
    if emp_ids:
        try:
            eresp = client.table("employers").select("id,name").in_("id", emp_ids).execute()
            emp_map = {str(e["id"]): e.get("name") for e in (eresp.data or [])}
        except Exception:
            pass
    req_map = {}
    if app_ids:
        try:
            aresp = client.table("applications").select("id,hiring_requirement_id").in_("id", app_ids).execute()
            req_ids = list({str(a["hiring_requirement_id"]) for a in (aresp.data or []) if a.get("hiring_requirement_id")})
            if req_ids:
                rresp = client.table("hiring_requirements").select("id,title").in_("id", req_ids).execute()
                rtitles = {str(r["id"]): r.get("title") for r in (rresp.data or [])}
                for a in (aresp.data or []):
                    req_map[str(a["id"])] = rtitles.get(str(a.get("hiring_requirement_id")))
        except Exception:
            pass
    for r in rows:
        if r.get("employer_id"):
            r["employer_name"] = emp_map.get(str(r["employer_id"]))
        if r.get("application_id"):
            r["requirement_title"] = req_map.get(str(r["application_id"]))
    return rows


def create_placement(student_id: str, payload: dict) -> dict:
    client = _ensure_client()
    app_id = payload.get("application_id")
    if app_id:
        app = _get_application(str(app_id))
        if app.get("student_id") != student_id:
            raise HTTPException(status_code=400, detail="Application belongs to a different student")
        req = emp._requirement_employer(app["hiring_requirement_id"])
        derived_emp_id = str(req["employer_id"])
        if payload.get("employer_id") and str(payload["employer_id"]) != derived_emp_id:
            raise HTTPException(status_code=400, detail="employer_id does not match the application requirement")
        target_employer_id = derived_emp_id
        try:
            pre = client.table("placement_outcomes").select("id").eq("application_id", str(app_id)).execute()
            if pre.data:
                raise HTTPException(status_code=400, detail="Placement already recorded for this application")
        except HTTPException:
            raise
        except Exception:
            pass
    else:
        target_employer_id = payload.get("employer_id")
        if not target_employer_id:
            raise HTTPException(status_code=400, detail="employer_id is required for unlinked placement")
        eresp = client.table("employers").select("id").eq("id", str(target_employer_id)).execute()
        if not (eresp.data or []):
            raise HTTPException(status_code=400, detail="Invalid employer_id: employer does not exist")
        target_employer_id = str(target_employer_id)

    status = payload.get("status", "selected")
    if status not in ("offer_accepted", "selected", "joined", "declined", "not_joined"):
        raise HTTPException(status_code=400, detail=f"Invalid placement status: {status}")

    joining_val = payload.get("joining_date") or payload.get("joined_at")
    if status == "joined":
        if "joining_date" in payload and not joining_val:
            raise HTTPException(status_code=400, detail="joining_date is required when status is joined")
        if not joining_val and payload.get("require_joining_date"):
            raise HTTPException(status_code=400, detail="joining_date is required when status is joined")

    role_title = payload.get("role_title")
    if not role_title or len(role_title.strip()) < 2:
        raise HTTPException(status_code=400, detail="role_title must be between 2 and 200 characters")

    now = datetime.now(timezone.utc).isoformat()
    try:
        resp = client.table("placement_outcomes").insert({
            "student_id": student_id,
            "employer_id": target_employer_id,
            "application_id": str(app_id) if app_id else None,
            "role_title": role_title.strip(),
            "location": payload.get("location"),
            "joining_date": str(joining_val) if joining_val else None,
            "status": status,
            "outcome_source": "student_reported",
            "verification_status": "unverified",
            "created_at": now,
            "updated_at": now,
        }).execute()
    except HTTPException:
        raise
    except Exception as e:
        if _missing(e):
            raise HTTPException(status_code=503, detail="Person 2 tables missing — run backend/supabase/027_outcomes.sql")
        raise HTTPException(status_code=500, detail=f"Failed to create placement: {str(e)[:200]}")
    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=500, detail="Failed to create placement")
    return _attach_placement_metadata(rows)[0]


def list_placements(student_id: str) -> list:
    client = _ensure_client()
    try:
        resp = client.table("placement_outcomes").select("*").eq("student_id", student_id).execute()
    except Exception as e:
        if _missing(e):
            raise HTTPException(status_code=503, detail="Person 2 tables missing — run backend/supabase/027_outcomes.sql")
        raise HTTPException(status_code=500, detail="Failed to list placements")
    return _attach_placement_metadata(resp.data or [])


def list_placements_for_employer(user_id: str, employer_id: str) -> list:
    emp.require_employer_access(user_id, employer_id, roles=("owner", "member"))
    client = _ensure_client()
    try:
        resp = client.table("placement_outcomes").select("*").eq("employer_id", employer_id).execute()
    except Exception as e:
        if _missing(e):
            raise HTTPException(status_code=503, detail="Person 2 tables missing — run backend/supabase/027_outcomes.sql")
        raise HTTPException(status_code=500, detail="Failed to list employer placements")
    return _attach_placement_metadata(resp.data or [])


def get_placement_detail(user_id: str, placement_id: str) -> dict:
    client = _ensure_client()
    try:
        resp = client.table("placement_outcomes").select("*").eq("id", placement_id).execute()
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to fetch placement")
    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Placement not found")
    row = rows[0]
    if row.get("student_id") != user_id:
        m = emp.get_membership(user_id, row["employer_id"])
        if not m:
            raise HTTPException(status_code=404, detail="Placement not found")
    return _attach_placement_metadata([row])[0]


def update_placement(user_id: str, placement_id: str, payload: dict) -> dict:
    if "verification_status" in payload or "outcome_source" in payload:
        raise HTTPException(status_code=403, detail="Verification is employer-confirmed only")

    client = _ensure_client()
    try:
        existing = client.table("placement_outcomes").select("*").eq("id", placement_id).execute()
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to fetch placement")
    rows0 = existing.data or []
    if not rows0:
        raise HTTPException(status_code=404, detail="Placement not found")
    row0 = rows0[0]

    actor = None
    if row0.get("student_id") == user_id:
        actor = "student"
    else:
        m = emp.get_membership(user_id, row0["employer_id"])
        if m:
            actor = "employer"
        else:
            raise HTTPException(status_code=404, detail="Placement not found")

    allowed_fields = {"role_title", "location", "joining_date", "joined_at", "status"}

    clean = {k: v for k, v in payload.items() if k in allowed_fields}
    if not clean:
        raise HTTPException(status_code=400, detail="No fields to update")

    if "status" in clean:
        from_status = row0.get("status")
        to_status = clean["status"]
        if to_status != from_status:
            if from_status in PLACEMENT_TERMINAL:
                raise HTTPException(status_code=400, detail=f"Placement is terminal ({from_status}) and cannot transition")
            allowed_next = PLACEMENT_TRANSITIONS.get(from_status, {})
            if to_status not in allowed_next:
                raise HTTPException(status_code=400, detail=f"Invalid placement transition {from_status} -> {to_status}")
            required_actor = allowed_next[to_status]
            if required_actor != "any" and required_actor != actor:
                raise HTTPException(status_code=403, detail=f"Transition {from_status} -> {to_status} is {required_actor}-controlled")
            if to_status == "joined":
                jdate = clean.get("joining_date") or clean.get("joined_at") or row0.get("joining_date")
                if not jdate:
                    raise HTTPException(status_code=400, detail="joining_date is required when status is joined")

    if "joined_at" in clean:
        if "joining_date" not in clean or not clean["joining_date"]:
            clean["joining_date"] = clean.pop("joined_at")
        else:
            clean.pop("joined_at", None)

    if "joining_date" in clean and clean["joining_date"] is not None:
        clean["joining_date"] = str(clean["joining_date"])

    now = datetime.now(timezone.utc).isoformat()
    clean["updated_at"] = now

    try:
        resp = client.table("placement_outcomes").update(clean).eq("id", placement_id).execute()
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to update placement")
    rows = resp.data or []
    return _attach_placement_metadata(rows)[0] if rows else {**row0, **clean}


def confirm_placement(user_id: str, placement_id: str, verified: bool = True) -> dict:
    client = _ensure_client()
    try:
        existing = client.table("placement_outcomes").select("*").eq("id", placement_id).execute()
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to fetch placement")
    rows0 = existing.data or []
    if not rows0:
        raise HTTPException(status_code=404, detail="Placement not found")
    emp.require_employer_access(user_id, rows0[0]["employer_id"], roles=("owner", "member"))
    now = datetime.now(timezone.utc).isoformat()
    update_data = {
        "verification_status": "verified" if verified else "disputed",
        "outcome_source": "employer_confirmed",
        "updated_at": now,
    }
    try:
        resp = client.table("placement_outcomes").update(update_data).eq("id", placement_id).execute()
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to confirm placement")
    rows = resp.data or []
    return _attach_placement_metadata(rows)[0] if rows else {**rows0[0], **update_data}


# ---------------------------------------------------------------------------
# Qualification alignments
# ---------------------------------------------------------------------------

def create_alignment(user_id: str, payload: dict) -> dict:
    req = emp._requirement_employer(str(payload["hiring_requirement_id"]))
    emp.require_employer_access(user_id, req["employer_id"], roles=("owner", "member"))
    evidence_id = payload.get("evidence_id")
    certification_id = payload.get("certification_id")
    if evidence_id and certification_id:
        raise HTTPException(status_code=400, detail="Set at most one of evidence_id or certification_id")
    client = _ensure_client()
    # Grounding ownership: may only cite own evidence/certification rows
    if evidence_id:
        try:
            eresp = client.table("evidence").select("id,user_id").eq("id", str(evidence_id)).execute()
            erows = eresp.data or []
            if not erows:
                raise HTTPException(status_code=400, detail="Unknown evidence_id")
            if erows[0].get("user_id") != user_id:
                raise HTTPException(status_code=403, detail="Can only ground in your own evidence")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=500, detail="Failed to validate evidence_id")
    if certification_id:
        try:
            cresp = client.table("certifications").select("id,user_id").eq("id", str(certification_id)).execute()
            crows = cresp.data or []
            if not crows:
                raise HTTPException(status_code=400, detail="Unknown certification_id")
            if crows[0].get("user_id") != user_id:
                raise HTTPException(status_code=403, detail="Can only ground in your own certification")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=500, detail="Failed to validate certification_id")
    if payload.get("skill_id"):
        try:
            sresp = client.table("skills").select("id").eq("id", str(payload["skill_id"])).execute()
            if not (sresp.data or []):
                raise HTTPException(status_code=400, detail="Unknown skill_id")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=500, detail="Failed to validate skill_id")
    now = datetime.now(timezone.utc).isoformat()
    try:
        resp = client.table("qualification_alignments").insert({
            "hiring_requirement_id": str(payload["hiring_requirement_id"]),
            "course_name": payload["course_name"],
            "qualification_name": payload.get("qualification_name"),
            "skill_id": str(payload["skill_id"]) if payload.get("skill_id") else None,
            "coverage": payload.get("coverage"),
            "evidence_note": payload.get("evidence_note"),
            "evidence_id": str(evidence_id) if evidence_id else None,
            "certification_id": str(certification_id) if certification_id else None,
            "created_by": user_id,
            "created_at": now,
            "updated_at": now,
        }).execute()
    except Exception as e:
        if _missing(e):
            raise HTTPException(status_code=503, detail="Person 2 tables missing — run backend/supabase/027_outcomes.sql")
        raise HTTPException(status_code=500, detail=f"Failed to create alignment: {str(e)[:200]}")
    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=500, detail="Failed to create alignment")
    return rows[0]


def list_alignments(user_id: str, hiring_requirement_id: str | None = None) -> list:
    client = _ensure_client()
    try:
        if hiring_requirement_id:
            req = emp._requirement_employer(hiring_requirement_id)
            m = emp.get_membership(user_id, req["employer_id"])
            if not m:
                aresp = client.table("applications").select("id").eq("student_id", user_id).eq(
                    "hiring_requirement_id", hiring_requirement_id).execute()
                if not (aresp.data or []):
                    raise HTTPException(status_code=404, detail="Requirement not found")
            resp = client.table("qualification_alignments").select("*").eq(
                "hiring_requirement_id", hiring_requirement_id).execute()
            return resp.data or []
        # All alignments for requirements the user can see (member or applicant)
        mresp = client.table("employer_members").select("employer_id").eq("user_id", user_id).execute()
        emp_ids = [m["employer_id"] for m in (mresp.data or [])]
        req_ids: set[str] = set()
        if emp_ids:
            rresp = client.table("hiring_requirements").select("id").in_("employer_id", emp_ids).execute()
            req_ids.update(r["id"] for r in (rresp.data or []))
        aresp = client.table("applications").select("hiring_requirement_id").eq("student_id", user_id).execute()
        req_ids.update(r["hiring_requirement_id"] for r in (aresp.data or []))
        if not req_ids:
            return []
        resp = client.table("qualification_alignments").select("*").in_(
            "hiring_requirement_id", list(req_ids)).execute()
        return resp.data or []
    except HTTPException:
        raise
    except Exception as e:
        if _missing(e):
            raise HTTPException(status_code=503, detail="Person 2 tables missing — run backend/supabase/027_outcomes.sql")
        raise HTTPException(status_code=500, detail="Failed to list alignments")


# ---------------------------------------------------------------------------
# Dashboard + industry signals (descriptive only, no prediction)
# ---------------------------------------------------------------------------

def _parse_window(from_s: str | None, to_s: str | None) -> tuple[datetime | None, datetime | None]:
    try:
        f = datetime.fromisoformat(from_s.replace("Z", "+00:00")) if from_s else None
        t = datetime.fromisoformat(to_s.replace("Z", "+00:00")) if to_s else None
        if f and f.tzinfo is None:
            f = f.replace(tzinfo=timezone.utc)
        if t and t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        if f and t and f > t:
            raise HTTPException(status_code=400, detail="Invalid time window: from_date cannot be after to_date")
        return f, t
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid time window (use ISO dates)")


def _in_window(ts: str | None, f: datetime | None, t: datetime | None) -> bool:
    if not ts:
        return False
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        if f and d < f:
            return False
        if t and d > t:
            return False
        return True
    except Exception:
        return False



def get_dashboard(user_id: str, employer_id: str | None = None,
                  from_s: str | None = None, to_s: str | None = None) -> dict:
    f, t = _parse_window(from_s, to_s)
    client = _ensure_client()
    # Scope: employer scope if employer_id given (+ membership), else student's own
    if employer_id:
        emp.require_employer_access(user_id, employer_id, roles=("owner", "member"))
        try:
            rresp = client.table("hiring_requirements").select("id").eq("employer_id", employer_id).execute()
            req_ids = [r["id"] for r in (rresp.data or [])]
            aresp = client.table("applications").select("*").in_(
                "hiring_requirement_id", req_ids).execute() if req_ids else None
            apps = (aresp.data if aresp else []) or []
            for a in apps:
                a["employer_id"] = employer_id
            placements: list = []
            if apps:
                app_ids = [a["id"] for a in apps]
                presp = client.table("placement_outcomes").select("*").in_("application_id", app_ids).execute()
                placements = presp.data or []
            upresp = client.table("placement_outcomes").select("*").eq("employer_id", employer_id).execute()
            all_emp_pl = upresp.data or []
            unlinked = len([p for p in all_emp_pl if not p.get("application_id")])
        except Exception:
            raise HTTPException(status_code=500, detail="Failed to build dashboard")
    else:
        try:
            aresp = client.table("applications").select("*").eq("student_id", user_id).execute()
            apps = _attach_employer_ids(aresp.data or [])
            presp = client.table("placement_outcomes").select("*").eq("student_id", user_id).execute()
            placements = presp.data or []
            unlinked = len([p for p in placements if not p.get("application_id")])
        except Exception as e:
            if _missing(e):
                raise HTTPException(status_code=503, detail="Person 2 tables missing — run backend/supabase/027_outcomes.sql")
            raise HTTPException(status_code=500, detail="Failed to build dashboard")
    scoped = [a for a in apps if a.get("applied_at") and (not f and not t or _in_window(a["applied_at"], f, t))]
    applied_n = len(scoped)
    st = [a["status"] for a in scoped]
    funnel = {s: st.count(s) for s in ("saved", "applied", "screening", "interview", "offer_received", "selected", "rejected", "withdrawn")}
    n_interview = sum(1 for s in st if s in ("interview", "offer_received", "selected"))
    n_offer = sum(1 for s in st if s in ("offer_received", "selected"))
    n_selected = sum(1 for a in scoped if a.get("status") == "selected" or a.get("outcome") == "selected")
    linked_joined = [p for p in placements if p.get("status") == "joined" and p.get("application_id")]
    n_joined_linked = len(linked_joined)
    selection_to_joining = (n_joined_linked / n_selected) if n_selected else 0.0
    application_to_joining = (n_joined_linked / applied_n) if applied_n else 0.0
    rates = {
        "interview_rate": (n_interview / applied_n) if applied_n else 0.0,
        "offer_rate": (n_offer / applied_n) if applied_n else 0.0,
        "selection_rate": (n_selected / applied_n) if applied_n else 0.0,
        "joining_rate_selection_base": selection_to_joining,
        "joining_rate_application_base": application_to_joining,
        "selection_to_joining_rate": selection_to_joining,
        "application_to_joining_rate": application_to_joining,
        "application_to_interview_rate": (n_interview / applied_n) if applied_n else 0.0,
        "application_to_offer_rate": (n_offer / applied_n) if applied_n else 0.0,
        "application_to_selection_rate": (n_selected / applied_n) if applied_n else 0.0,
    }
    # Top required skills in scope
    top_required: list = []
    try:
        scope_req_ids = list({a["hiring_requirement_id"] for a in scoped}) or list({a["hiring_requirement_id"] for a in apps})
        if scope_req_ids:
            sresp = client.table("hiring_requirement_skills").select("skill_id").in_(
                "hiring_requirement_id", scope_req_ids).execute()
            counts: dict[str, int] = {}
            for r in (sresp.data or []):
                counts[r["skill_id"]] = counts.get(r["skill_id"], 0) + 1
            top_required = sorted(({"skill_id": k, "count": v} for k, v in counts.items()),
                                  key=lambda d: d["count"], reverse=True)[:10]
    except Exception:
        top_required = []
    # Top observed gaps in scope
    top_gaps: list = []
    try:
        scope_app_ids = [a["id"] for a in apps]
        if scope_app_ids:
            fresp = client.table("employer_feedback").select("id").in_("application_id", scope_app_ids).execute()
            fb_ids = [r["id"] for r in (fresp.data or [])]
            if fb_ids:
                sresp = client.table("employer_skill_feedback").select(
                    "skill_id,expected_level,observed_level").in_("employer_feedback_id", fb_ids).execute()
                agg: dict[str, dict] = {}
                for r in (sresp.data or []):
                    exp, obs = r.get("expected_level"), r.get("observed_level")
                    if exp is None or obs is None:
                        continue
                    e = agg.setdefault(r["skill_id"], {"total": 0.0, "n": 0})
                    e["total"] += exp - obs
                    e["n"] += 1
                top_gaps = sorted(({"skill_id": k, "avg_gap": v["total"] / v["n"], "feedback_count": v["n"]}
                                   for k, v in agg.items()),
                                  key=lambda d: d["avg_gap"], reverse=True)[:10]
    except Exception:
        top_gaps = []
    return {
        "funnel": funnel,
        "rates": rates,
        "denominators": {"applied_n": applied_n, "selected_n": n_selected},
        "applied_count": applied_n,
        "interview_count": n_interview,
        "offer_count": n_offer,
        "selected_count": n_selected,
        "joined_count": n_joined_linked,
        "unlinked_placement_count": unlinked,
        "top_required_skills": top_required,
        "top_observed_gaps": top_gaps,
        "unlinked_placements_n": unlinked,
        "window": {"from": from_s, "to": to_s},
    }


def get_industry_signals(role: str | None = None, location: str | None = None,
                         from_s: str | None = None, to_s: str | None = None) -> dict:
    """Aggregated PII-free signal for Person 1. No user/employer/application IDs,
    no names, emails, or comments cross this boundary."""
    f, t = _parse_window(from_s, to_s)
    client = _ensure_client()
    try:
        q = client.table("hiring_requirements").select("id,role_key,location")
        if role:
            q = q.eq("role_key", role)
        if location:
            q = q.eq("location", location)
        rresp = q.execute()
        reqs = rresp.data or []
        req_ids = list(dict.fromkeys(r["id"] for r in reqs if r.get("id")))
        requirements_n = len(req_ids)

        apps = []
        if req_ids:
            aresp = client.table("applications").select("id,status,applied_at,hiring_requirement_id").in_(
                "hiring_requirement_id", req_ids).execute()
            seen_app_ids = set()
            for a in ((aresp.data if aresp else []) or []):
                aid = a.get("id")
                if not aid or aid in seen_app_ids:
                    continue
                if not a.get("applied_at"):
                    continue
                if (f or t) and not _in_window(a["applied_at"], f, t):
                    continue
                seen_app_ids.add(aid)
                apps.append(a)

        applied_n = len(apps)
        st = [str(a.get("status") or "") for a in apps]
        interview_n = sum(1 for s in st if s in ("interview", "offer_received", "selected"))
        selection_n = sum(1 for s in st if s == "selected")
        app_ids = [a["id"] for a in apps]

        placement_n = 0
        if app_ids:
            presp = client.table("placement_outcomes").select("id,application_id,status").in_(
                "application_id", app_ids).eq("status", "joined").execute()
            valid_placements = {
                p["id"] for p in (presp.data or [])
                if p.get("id")
                and p.get("application_id")
                and p["application_id"] in set(app_ids)
                and p.get("status") == "joined"
            }
            placement_n = len(valid_placements)

        feedback_n = 0
        skill_gap: float | None = None
        demand: float | None = None
        if app_ids:
            fresp = client.table("employer_feedback").select("id,application_id,created_at").in_(
                "application_id", app_ids).execute()
            valid_fbs = [
                x for x in (fresp.data or [])
                if x.get("id")
                and x.get("application_id") in set(app_ids)
                and (not f and not t or _in_window(x.get("created_at"), f, t))
            ]
            unique_fb_ids = list(dict.fromkeys(x["id"] for x in valid_fbs))
            feedback_n = len(unique_fb_ids)
            if unique_fb_ids:
                sresp = client.table("employer_skill_feedback").select(
                    "employer_feedback_id,expected_level,observed_level").in_(
                    "employer_feedback_id", unique_fb_ids).execute()
                gaps = [
                    float(r["expected_level"]) - float(r["observed_level"])
                    for r in (sresp.data or [])
                    if r.get("expected_level") is not None and r.get("observed_level") is not None
                ]
                skill_gap = round(sum(gaps) / len(gaps), 4) if gaps else None

        # observed_demand is skill-specific; without ?skill param this is role-level volume only.
        min_n_met = applied_n >= 10 and feedback_n >= 5
        if not min_n_met:
            skill_gap = None
            demand = None

        return {
            "signal_version": "industry-outcome-signal-v1",
            "role": role,
            "location": location,
            "skill": None,
            "time_window": {
                "from": from_s,
                "to": to_s,
                "basis": "applied_at for counts; feedback created_at for gap",
            },
            "denominators": {"requirements_n": requirements_n, "applied_n": applied_n},
            "application_count": applied_n,
            "interview_count": interview_n,
            "selection_count": selection_n,
            "placement_count": placement_n,
            "feedback_count": feedback_n,
            "observed_demand": demand,
            "observed_skill_gap": skill_gap,
            "min_n_met": min_n_met,
        }
    except HTTPException:
        raise
    except Exception as e:
        if _missing(e):
            raise HTTPException(status_code=503, detail="Person 2 tables missing — run migrations 026/027")
        raise HTTPException(status_code=500, detail="Failed to build industry signals")


def get_industry_skill_signal(skill_id: str, role: str | None = None,
                              location: str | None = None,
                              from_s: str | None = None, to_s: str | None = None) -> dict:
    """Skill-level variant: observed_demand = requirements requesting skill / requirements_n."""
    base = get_industry_signals(role=role, location=location, from_s=from_s, to_s=to_s)
    client = _ensure_client()
    try:
        try:
            s_rows = client.table("skills").select("id,canonical_name").execute().data or []
        except Exception:
            s_rows = []

        target_skill_ids = {str(skill_id).strip()}
        skill_display = str(skill_id).strip()

        for sr in s_rows:
            sid = str(sr.get("id") or "").strip()
            cname = str(sr.get("canonical_name") or "").strip()
            if sid.lower() == str(skill_id).strip().lower():
                if cname:
                    skill_display = cname
                    target_skill_ids.add(cname)
            if cname.lower() == str(skill_id).strip().lower():
                if sid:
                    target_skill_ids.add(sid)
                skill_display = cname

        q = client.table("hiring_requirements").select("id,role_key,location")
        if role:
            q = q.eq("role_key", role)
        if location:
            q = q.eq("location", location)
        reqs = q.execute().data or []
        req_ids = list(dict.fromkeys(r["id"] for r in reqs if r.get("id")))
        requirements_n = len(req_ids)

        demand: float | None = None
        if req_ids:
            sresp = client.table("hiring_requirement_skills").select(
                "hiring_requirement_id,skill_id").in_("hiring_requirement_id", req_ids).execute()
            matching_reqs = {
                r["hiring_requirement_id"]
                for r in (sresp.data or [])
                if str(r.get("skill_id") or "").strip() in target_skill_ids
                and r.get("hiring_requirement_id") in set(req_ids)
            }
            demand = round(len(matching_reqs) / requirements_n, 4) if requirements_n > 0 else None

        f, t = _parse_window(from_s, to_s)
        aresp = client.table("applications").select("id,applied_at,hiring_requirement_id").in_(
            "hiring_requirement_id", req_ids).execute() if req_ids else None
        apps = [
            a for a in ((aresp.data if aresp else []) or [])
            if a.get("applied_at") and (not f and not t or _in_window(a["applied_at"], f, t))
        ]
        app_ids = list(dict.fromkeys(a["id"] for a in apps if a.get("id")))

        fbn = 0
        gap: float | None = None
        if app_ids:
            fresp = client.table("employer_feedback").select("id,created_at,application_id").in_(
                "application_id", app_ids).execute()
            fbs = [
                x for x in (fresp.data or [])
                if x.get("application_id") in set(app_ids)
                and (not f and not t or _in_window(x.get("created_at"), f, t))
            ]
            fb_ids = list(dict.fromkeys(x["id"] for x in fbs if x.get("id")))
            if fb_ids:
                sresp = client.table("employer_skill_feedback").select(
                    "employer_feedback_id,skill_id,expected_level,observed_level").in_(
                    "employer_feedback_id", fb_ids).execute()
                valid_skill_fb = [
                    r for r in (sresp.data or [])
                    if str(r.get("skill_id") or "").strip() in target_skill_ids
                    and r.get("expected_level") is not None
                    and r.get("observed_level") is not None
                ]
                gaps = [float(r["expected_level"]) - float(r["observed_level"]) for r in valid_skill_fb]
                fbn = len({r["employer_feedback_id"] for r in valid_skill_fb})
                gap = round(sum(gaps) / len(gaps), 4) if gaps else None

        min_n = base["denominators"]["applied_n"] >= 5 and fbn >= 5
        base.update({
            "skill": skill_display,
            "feedback_count": fbn,
            "observed_demand": demand if min_n else None,
            "observed_skill_gap": gap if min_n else None,
            "min_n_met": min_n,
        })
        return base
    except HTTPException:
        raise
    except Exception as e:
        if _missing(e):
            raise HTTPException(status_code=503, detail="Person 2 tables missing — run migrations 026/027")
        raise HTTPException(status_code=500, detail="Failed to build skill signal")
