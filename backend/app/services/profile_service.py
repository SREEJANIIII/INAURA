from fastapi import HTTPException
from supabase import Client
from typing import Optional
from datetime import datetime, timezone
from ..core.supabase import get_supabase_client

TABLE = "profiles"

# Service layer — no DB logic in route handlers

def _ensure_client() -> Client:
    client = get_supabase_client()
    if client is None:
        raise HTTPException(
            status_code=503,
            detail="Supabase not configured — set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in backend/.env",
        )
    return client


def get_profile(user_id: str) -> Optional[dict]:
    client = _ensure_client()
    try:
        resp = client.table(TABLE).select("*").eq("user_id", user_id).single().execute()
        # supabase-py returns data in resp.data
        if resp.data:
            return resp.data
        return None
    except Exception as e:
        # .single() throws if no row; check message
        msg = str(e).lower()
        if "permission denied" in msg:
            raise HTTPException(
                status_code=503,
                detail="Database permission denied — run GRANT SELECT, INSERT, UPDATE, DELETE ON public.profiles TO anon, authenticated, service_role; in Supabase SQL Editor (see backend/supabase/001_create_profiles.sql)",
            )
        if "no rows" in msg or "not found" in msg or "0 rows" in msg:
            return None
        # fallback list query
        try:
            resp2 = client.table(TABLE).select("*").eq("user_id", user_id).execute()
            if resp2.data and len(resp2.data) > 0:
                return resp2.data[0]
            return None
        except Exception as e2:
            m2 = str(e2).lower()
            if "permission denied" in m2:
                raise HTTPException(
                    status_code=503,
                    detail="Database permission denied — run GRANTs in Supabase SQL Editor",
                )
            raise HTTPException(status_code=500, detail="Failed to fetch profile")


def upsert_profile(user_id: str, payload: dict) -> dict:
    client = _ensure_client()
    now = datetime.now(timezone.utc).isoformat()
    # Ensure profile_completed true on upsert via setup
    data = {
        "user_id": user_id,
        "profile_completed": True,
        "updated_at": now,
        **payload,
    }
    # Check existing to preserve created_at
    existing = get_profile(user_id)
    if not existing:
        data["created_at"] = now
        try:
            resp = client.table(TABLE).insert(data).execute()
            if resp.data and len(resp.data) > 0:
                return resp.data[0]
            return data
        except Exception as e:
            m = str(e).lower()
            if "permission denied" in m:
                raise HTTPException(status_code=503, detail="Database permission denied — run GRANTs in Supabase SQL Editor")
            raise HTTPException(status_code=500, detail=f"Failed to create profile: {str(e)[:200]}")
    else:
        # keep created_at
        data["created_at"] = existing.get("created_at", now)
        try:
            resp = client.table(TABLE).update(data).eq("user_id", user_id).execute()
            if resp.data and len(resp.data) > 0:
                return resp.data[0]
            # fallback fetch
            return get_profile(user_id) or data
        except Exception as e:
            m = str(e).lower()
            if "permission denied" in m:
                raise HTTPException(status_code=503, detail="Database permission denied — run GRANTs in Supabase SQL Editor")
            raise HTTPException(status_code=500, detail=f"Failed to update profile: {str(e)[:200]}")


def update_profile_partial(user_id: str, payload: dict) -> dict:
    # payload may be partial
    existing = get_profile(user_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Profile not found — complete setup first")
    # merge
    merged = {**existing, **{k: v for k, v in payload.items() if v is not None}}
    # ensure updated_at
    merged["updated_at"] = datetime.now(timezone.utc).isoformat()
    # ensure profile stays completed if it was
    if existing.get("profile_completed"):
        merged["profile_completed"] = True
    client = _ensure_client()
    try:
        resp = client.table(TABLE).update(merged).eq("user_id", user_id).execute()
        if resp.data and len(resp.data) > 0:
            return resp.data[0]
        return merged
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update profile: {str(e)[:200]}")
