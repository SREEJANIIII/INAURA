"""Person 2: employer service — employers, members, hiring requirements.

Isolated from INAURA core. Reads public.skills for FK validation only.
Never writes to core tables.
"""

from fastapi import HTTPException
from supabase import Client
from datetime import datetime, timezone
from ..core.supabase import get_supabase_client


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


# ---------------------------------------------------------------------------
# Membership / authorization
# ---------------------------------------------------------------------------

def get_membership(user_id: str, employer_id: str) -> dict | None:
    client = _ensure_client()
    try:
        resp = (
            client.table("employer_members")
            .select("*")
            .eq("employer_id", employer_id)
            .eq("user_id", user_id)
            .execute()
        )
    except Exception as e:
        if _table_missing_msg(e):
            raise HTTPException(status_code=503, detail="Person 2 tables missing — run backend/supabase/026_employers.sql")
        raise HTTPException(status_code=500, detail="Failed to check employer membership")
    rows = resp.data or []
    return rows[0] if rows else None


def require_employer_access(user_id: str, employer_id: str, roles=("owner", "member")) -> dict:
    """404 for non-members to avoid employer enumeration; 403 for members with insufficient role."""
    m = get_membership(user_id, employer_id)
    if not m:
        raise HTTPException(status_code=404, detail="Employer not found")
    if m.get("role") not in roles:
        raise HTTPException(status_code=403, detail="Forbidden — insufficient employer role")
    return m


def _strip_contact_for_non_owner(employer: dict, membership: dict | None) -> dict:
    if membership and membership.get("role") == "owner":
        return employer
    out = dict(employer)
    out.pop("contact_email", None)
    return out


# ---------------------------------------------------------------------------
# Employers
# ---------------------------------------------------------------------------

def create_employer(user_id: str, payload: dict) -> dict:
    client = _ensure_client()
    now = datetime.now(timezone.utc).isoformat()
    try:
        resp = client.table("employers").insert({
            "name": payload["name"],
            "description": payload.get("description"),
            "industry": payload.get("industry"),
            "website": payload.get("website"),
            "location": payload.get("location"),
            "contact_email": payload.get("contact_email"),
            "status": "active",
            "created_by": user_id,
            "created_at": now,
            "updated_at": now,
        }).execute()
    except Exception as e:
        if _table_missing_msg(e):
            raise HTTPException(status_code=503, detail="Person 2 tables missing — run backend/supabase/026_employers.sql")
        raise HTTPException(status_code=500, detail=f"Failed to create employer: {str(e)[:200]}")
    row = (resp.data or [None])[0]
    if not row:
        raise HTTPException(status_code=500, detail="Failed to create employer")
    # Bootstrap owner membership in same flow
    try:
        client.table("employer_members").insert({
            "employer_id": row["id"],
            "user_id": user_id,
            "role": "owner",
        }).execute()
    except Exception:
        # Roll back employer to avoid orphan without owner
        try:
            client.table("employers").delete().eq("id", row["id"]).execute()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail="Failed to initialize employer ownership")
    return row


def list_employers(user_id: str) -> list:
    client = _ensure_client()
    try:
        mresp = client.table("employer_members").select("employer_id,role").eq("user_id", user_id).execute()
    except Exception as e:
        if _table_missing_msg(e):
            raise HTTPException(status_code=503, detail="Person 2 tables missing — run backend/supabase/026_employers.sql")
        raise HTTPException(status_code=500, detail="Failed to list employers")
    memberships = mresp.data or []
    if not memberships:
        # Also include employers created by user before membership backfill
        try:
            cresp = client.table("employers").select("*").eq("created_by", user_id).execute()
            return cresp.data or []
        except Exception:
            return []
    ids = [m["employer_id"] for m in memberships]
    role_by_id = {m["employer_id"]: m["role"] for m in memberships}
    try:
        resp = client.table("employers").select("*").in_("id", ids).execute()
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to list employers")
    out = []
    for row in resp.data or []:
        out.append(_strip_contact_for_non_owner(row, {"role": role_by_id.get(row["id"])}))
    return out


def get_employer(user_id: str, employer_id: str) -> dict:
    client = _ensure_client()
    m = get_membership(user_id, employer_id)
    try:
        resp = client.table("employers").select("*").eq("id", employer_id).execute()
    except Exception as e:
        if _table_missing_msg(e):
            raise HTTPException(status_code=503, detail="Person 2 tables missing — run backend/supabase/026_employers.sql")
        raise HTTPException(status_code=500, detail="Failed to fetch employer")
    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Employer not found")
    row = rows[0]
    # Creator without a membership row yet (bootstrap edge) sees full row;
    # otherwise strip contact_email for non-owners.
    if row.get("created_by") == user_id and not m:
        return row
    if not m:
        raise HTTPException(status_code=404, detail="Employer not found")
    return _strip_contact_for_non_owner(row, m)


def update_employer(user_id: str, employer_id: str, payload: dict) -> dict:
    require_employer_access(user_id, employer_id, roles=("owner",))
    if not payload:
        raise HTTPException(status_code=400, detail="No fields to update")
    allowed = {"name", "description", "industry", "website", "location", "contact_email", "status"}
    clean = {k: v for k, v in payload.items() if k in allowed}
    if not clean:
        raise HTTPException(status_code=400, detail="No fields to update")
    client = _ensure_client()
    try:
        resp = client.table("employers").update(clean).eq("id", employer_id).execute()
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to update employer")
    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Employer not found")
    return rows[0]


def delete_employer(user_id: str, employer_id: str) -> None:
    require_employer_access(user_id, employer_id, roles=("owner",))
    client = _ensure_client()
    try:
        client.table("employers").delete().eq("id", employer_id).execute()
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to delete employer")


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------

def list_members(user_id: str, employer_id: str) -> list:
    require_employer_access(user_id, employer_id, roles=("owner", "member"))
    client = _ensure_client()
    try:
        resp = client.table("employer_members").select("*").eq("employer_id", employer_id).execute()
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to list members")
    return resp.data or []


def add_member(user_id: str, employer_id: str, new_user_id: str, role: str = "member") -> dict:
    require_employer_access(user_id, employer_id, roles=("owner",))
    if role not in ("owner", "member"):
        raise HTTPException(status_code=400, detail="Invalid role")
    client = _ensure_client()
    try:
        resp = client.table("employer_members").upsert(
            {"employer_id": employer_id, "user_id": new_user_id, "role": role},
            on_conflict="employer_id,user_id",
        ).execute()
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to add member")
    rows = resp.data or []
    return rows[0] if rows else {"employer_id": employer_id, "user_id": new_user_id, "role": role}


def remove_member(user_id: str, employer_id: str, target_user_id: str) -> None:
    require_employer_access(user_id, employer_id, roles=("owner",))
    client = _ensure_client()
    # Prevent removing the last owner
    try:
        existing = client.table("employer_members").select("*").eq("employer_id", employer_id).execute()
        owners = [r for r in (existing.data or []) if r.get("role") == "owner"]
        target = [r for r in (existing.data or []) if r.get("user_id") == target_user_id]
        if target and target[0].get("role") == "owner" and len(owners) <= 1:
            raise HTTPException(status_code=400, detail="Cannot remove the last owner")
        client.table("employer_members").delete().eq("employer_id", employer_id).eq("user_id", target_user_id).execute()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to remove member")


# ---------------------------------------------------------------------------
# Hiring requirements
# ---------------------------------------------------------------------------

def create_requirement(user_id: str, employer_id: str, payload: dict) -> dict:
    require_employer_access(user_id, employer_id, roles=("owner", "member"))
    client = _ensure_client()
    now = datetime.now(timezone.utc).isoformat()
    try:
        resp = client.table("hiring_requirements").insert({
            "employer_id": employer_id,
            "title": payload["title"],
            "role_key": payload.get("role_key"),
            "location": payload.get("location"),
            "employment_type": payload.get("employment_type"),
            "description": payload.get("description"),
            "experience_min_years": payload.get("experience_min_years"),
            "qualification_text": payload.get("qualification_text"),
            "status": "open",
            "created_by": user_id,
            "created_at": now,
            "updated_at": now,
        }).execute()
    except Exception as e:
        if _table_missing_msg(e):
            raise HTTPException(status_code=503, detail="Person 2 tables missing — run backend/supabase/026_employers.sql")
        raise HTTPException(status_code=500, detail=f"Failed to create requirement: {str(e)[:200]}")
    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=500, detail="Failed to create requirement")
    return rows[0]


def _requirement_employer(requirement_id: str) -> dict:
    client = _ensure_client()
    try:
        resp = client.table("hiring_requirements").select("*").eq("id", requirement_id).execute()
    except Exception as e:
        if _table_missing_msg(e):
            raise HTTPException(status_code=503, detail="Person 2 tables missing — run backend/supabase/026_employers.sql")
        raise HTTPException(status_code=500, detail="Failed to fetch requirement")
    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Requirement not found")
    return rows[0]


def get_requirement(user_id: str, requirement_id: str) -> dict:
    req = _requirement_employer(requirement_id)
    m = get_membership(user_id, req["employer_id"])
    if not m:
        client = _ensure_client()
        try:
            aresp = client.table("applications").select("id").eq("student_id", user_id).eq(
                "hiring_requirement_id", requirement_id).execute()
        except Exception:
            raise HTTPException(status_code=404, detail="Requirement not found")
        if not (aresp.data or []):
            raise HTTPException(status_code=404, detail="Requirement not found")
    return req


def list_requirements(user_id: str, employer_id: str) -> list:
    require_employer_access(user_id, employer_id, roles=("owner", "member"))
    client = _ensure_client()
    try:
        resp = client.table("hiring_requirements").select("*").eq("employer_id", employer_id).execute()
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to list requirements")
    return resp.data or []


def update_requirement(user_id: str, requirement_id: str, payload: dict) -> dict:
    req = _requirement_employer(requirement_id)
    require_employer_access(user_id, req["employer_id"], roles=("owner", "member"))
    allowed = {"title", "role_key", "location", "employment_type", "description",
               "experience_min_years", "qualification_text", "status"}
    clean = {k: v for k, v in payload.items() if k in allowed}
    if not clean:
        raise HTTPException(status_code=400, detail="No fields to update")
    client = _ensure_client()
    try:
        resp = client.table("hiring_requirements").update(clean).eq("id", requirement_id).execute()
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to update requirement")
    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Requirement not found")
    return rows[0]


def delete_requirement(user_id: str, requirement_id: str) -> None:
    req = _requirement_employer(requirement_id)
    require_employer_access(user_id, req["employer_id"], roles=("owner", "member"))
    client = _ensure_client()
    try:
        client.table("hiring_requirements").delete().eq("id", requirement_id).execute()
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to delete requirement")


def list_canonical_skills() -> list:
    client = _ensure_client()
    try:
        resp = client.table("skills").select("id,canonical_name,display_name,category").order("display_name").execute()
        return resp.data or []
    except Exception as e:
        if _table_missing_msg(e):
            raise HTTPException(status_code=503, detail="Skills table missing — run canonical taxonomy migrations")
        raise HTTPException(status_code=500, detail="Failed to list canonical skills")


def _assert_skill_exists(skill_id: str) -> None:
    client = _ensure_client()
    try:
        resp = client.table("skills").select("id").eq("id", skill_id).execute()
    except Exception as e:
        if _table_missing_msg(e):
            raise HTTPException(status_code=503, detail="Skills table missing — run canonical taxonomy migrations")
        raise HTTPException(status_code=500, detail="Failed to validate skill")
    if not (resp.data or []):
        raise HTTPException(status_code=400, detail=f"Unknown skill_id: {skill_id}")


def _enrich_skills_with_metadata(client: Client, rows: list) -> list:
    if not rows:
        return rows
    skill_ids = [str(r["skill_id"]) for r in rows if r.get("skill_id")]
    if not skill_ids:
        return rows
    try:
        sresp = client.table("skills").select("id,canonical_name,display_name,category").in_("id", skill_ids).execute()
        smap = {str(s.get("id")): s for s in (sresp.data or [])}
        for r in rows:
            sk = smap.get(str(r.get("skill_id")))
            if sk:
                r["skill_name"] = sk.get("display_name") or sk.get("canonical_name")
                r["skill_category"] = sk.get("category")
    except Exception:
        pass
    return rows


def set_requirement_skills(user_id: str, requirement_id: str, skills: list) -> list:
    req = _requirement_employer(requirement_id)
    require_employer_access(user_id, req["employer_id"], roles=("owner", "member"))
    for s in skills:
        _assert_skill_exists(str(s["skill_id"]))
        if s.get("importance") not in ("required", "preferred"):
            raise HTTPException(status_code=400, detail="importance must be required or preferred")
    client = _ensure_client()
    try:
        # Replace set atomically (delete then insert)
        client.table("hiring_requirement_skills").delete().eq("hiring_requirement_id", requirement_id).execute()
        rows = [{
            "hiring_requirement_id": requirement_id,
            "skill_id": str(s["skill_id"]),
            "importance": s["importance"],
            "required_level": s.get("required_level"),
            "note": s.get("note"),
        } for s in skills]
        if not rows:
            return []
        resp = client.table("hiring_requirement_skills").insert(rows).execute()
        inserted = resp.data or []
        return _enrich_skills_with_metadata(client, inserted)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to set requirement skills: {str(e)[:200]}")


def list_requirement_skills(user_id: str, requirement_id: str) -> list:
    req = _requirement_employer(requirement_id)
    # Members of the employer OR students who applied may view (checked by caller for students)
    m = get_membership(user_id, req["employer_id"])
    if not m:
        # Allow students with an application to view (verified via applications table)
        client = _ensure_client()
        try:
            aresp = client.table("applications").select("id").eq("student_id", user_id).eq(
                "hiring_requirement_id", requirement_id).execute()
        except Exception:
            raise HTTPException(status_code=404, detail="Requirement not found")
        if not (aresp.data or []):
            raise HTTPException(status_code=404, detail="Requirement not found")
    else:
        client = _ensure_client()
    try:
        resp = client.table("hiring_requirement_skills").select("*").eq(
            "hiring_requirement_id", requirement_id).execute()
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to list requirement skills")
    rows = resp.data or []
    return _enrich_skills_with_metadata(client, rows)

