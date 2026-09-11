
from fastapi import HTTPException
from supabase import Client
from typing import Optional
from datetime import datetime, timezone
from ..core.supabase import get_supabase_client
from . import industry_service, retrieval_service
from . import profile_service, evidence_service

TABLE = "analysis_state"
VALID_STATUSES = {"not_started", "ready", "processing", "completed", "failed"}


def _client() -> Client:
    c = get_supabase_client()
    if c is None:
        raise HTTPException(status_code=503, detail="Supabase not configured")
    return c


def get_state(user_id: str) -> Optional[dict]:
    c = _client()
    try:
        r = c.table(TABLE).select("*").eq("user_id", user_id).single().execute()
        if r.data:
            return r.data
        return None
    except Exception as e:
        m = str(e).lower()
        if "no rows" in m or "not found" in m or "0 rows" in m:
            return None
        if "could not find the table" in m or "pgrst205" in m or "relation" in m:
            raise HTTPException(status_code=503, detail="Analysis state table not found — run backend/supabase/004_analysis_state.sql")
        if "permission denied" in m:
            raise HTTPException(status_code=503, detail="Database permission denied for analysis_state")
        raise HTTPException(status_code=500, detail="Failed to fetch analysis state")


def upsert_state(user_id: str, target_role: Optional[str], status: str, last_retrieval: Optional[dict] = None) -> dict:
    if status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status {status}")
    c = _client()
    now = datetime.now(timezone.utc).isoformat()
    existing = get_state(user_id)
    data = {
        "user_id": user_id,
        "target_role": target_role,
        "status": status,
        "last_retrieval": last_retrieval,
        "updated_at": now,
    }
    if not existing:
        data["created_at"] = now
        try:
            r = c.table(TABLE).insert(data).execute()
            if r.data and len(r.data) > 0:
                return r.data[0]
            return data
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to create analysis state: {str(e)[:200]}")
    else:
        data["created_at"] = existing.get("created_at", now)
        try:
            r = c.table(TABLE).update(data).eq("user_id", user_id).execute()
            if r.data and len(r.data) > 0:
                return r.data[0]
            return data
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to update analysis state: {str(e)[:200]}")


async def prepare(user_id: str, target_role: Optional[str]) -> dict:
    # Validate profile exists
    try:
        profile = profile_service.get_profile(user_id)
    except HTTPException as e:
        if e.status_code == 404:
            raise HTTPException(status_code=400, detail="Profile not found — complete /profile/setup first")
        raise
    if not profile:
        raise HTTPException(status_code=400, detail="Profile not found — complete setup")

    # Determine target role: explicit or from profile career_interests or stored state
    role = target_role
    if not role:
        # Try from analysis_state
        state = get_state(user_id)
        if state and state.get("target_role"):
            role = state["target_role"]
        elif profile.get("career_interests"):
            # Use first interest as candidate
            interests = profile["career_interests"]
            if interests and len(interests) > 0:
                role = interests[0]
    if not role:
        raise HTTPException(status_code=400, detail="No target role — select a primary career goal")

    # Validate role exists in industry knowledge (allow "Other" to pass)
    if role != "Other":
        try:
            roles = industry_service.list_roles()
            if role not in roles:
                # Allow custom role but warn — still try retrieval, but will return empty
                pass
        except HTTPException:
            raise
        except Exception:
            pass

    # Validate at least one evidence
    try:
        ev = evidence_service.list_evidence(user_id)
        pr = evidence_service.list_projects(user_id)
        ce = evidence_service.list_certs(user_id)
        if len(ev) == 0 and len(pr) == 0 and len(ce) == 0:
            raise HTTPException(status_code=400, detail="No evidence found — add at least one source in /analysis")
    except HTTPException as e:
        if e.status_code == 503:
            # If evidence tables not found, treat as not ready but still allow preparation?
            # For now, raise with clear message
            raise HTTPException(status_code=503, detail="Evidence tables not configured — run 002_create_evidence.sql")
        raise
    # If we reach here, ready to retrieve
    # Do retrieval (RAG)
    retrieval = await retrieval_service.retrieve(role, None, top_k=10)

    # Update state to ready (not processing, since we don't do heavy LLM now)
    # For Phase 4B, we set status to "ready" with last_retrieval
    new_state = upsert_state(user_id, role, "ready", retrieval)

    return {
        "status": new_state["status"],
        "target_role": new_state["target_role"],
        "message": "INAURA analysis is ready — industry context retrieved. Scoring and roadmap are next phase.",
        "retrieval": retrieval,
    }
