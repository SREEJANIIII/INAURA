from fastapi import HTTPException
from supabase import Client
from typing import List, Optional
from ..core.supabase import get_supabase_client

TABLE = "industry_requirements"


def _client() -> Client:
    c = get_supabase_client()
    if c is None:
        raise HTTPException(status_code=503, detail="Supabase not configured")
    return c


def list_roles() -> List[str]:
    c = _client()
    try:
        # Distinct roles
        r = c.table(TABLE).select("role").execute()
        if not r.data:
            return []
        roles = sorted({row["role"] for row in r.data if row.get("role")})
        return roles
    except Exception as e:
        m = str(e).lower()
        if "could not find the table" in m or "pgrst205" in m or "relation" in m:
            raise HTTPException(status_code=503, detail="Industry knowledge not found — run backend/supabase/003_industry_knowledge.sql")
        if "permission denied" in m:
            raise HTTPException(status_code=503, detail="Database permission denied for industry_requirements")
        raise HTTPException(status_code=500, detail="Failed to list roles")


def list_by_role(role: str) -> List[dict]:
    c = _client()
    try:
        r = c.table(TABLE).select("*").eq("role", role).order("importance", desc=True).execute()
        return r.data or []
    except Exception as e:
        m = str(e).lower()
        if "could not find the table" in m or "pgrst205" in m:
            raise HTTPException(status_code=503, detail="Industry knowledge not found — run 003_industry_knowledge.sql")
        raise HTTPException(status_code=500, detail="Failed to list industry requirements")


def get_all(limit: int = 100) -> List[dict]:
    c = _client()
    try:
        r = c.table(TABLE).select("*").order("role").limit(limit).execute()
        return r.data or []
    except Exception as e:
        m = str(e).lower()
        if "could not find the table" in m:
            raise HTTPException(status_code=503, detail="Industry knowledge not configured")
        raise HTTPException(status_code=500, detail="Failed to fetch industry requirements")
