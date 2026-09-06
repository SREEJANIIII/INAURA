from fastapi import APIRouter, Depends, HTTPException
from ....schemas.analysis import AnalysisStateResponse, SetTargetRoleRequest, PrepareAnalysisRequest, PrepareAnalysisResponse
from ....services import analysis_service
from ....services.analysis_run_service import run_analysis
from ....core.security import get_current_user, CurrentUser
from ....core.supabase import get_supabase_client
from typing import List

router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.get("/state", response_model=AnalysisStateResponse)
async def get_analysis_state(current_user: CurrentUser = Depends(get_current_user)):
    data = analysis_service.get_state(current_user.id)
    if not data:
        # Return not_started with no target
        return {
            "user_id": current_user.id,
            "target_role": None,
            "status": "not_started",
            "last_retrieval": None,
            "created_at": "1970-01-01T00:00:00Z",
            "updated_at": "1970-01-01T00:00:00Z",
        }
    return data


@router.post("/target", response_model=AnalysisStateResponse)
async def set_target_role(
    payload: SetTargetRoleRequest, current_user: CurrentUser = Depends(get_current_user)
):
    # Validate target role is non-empty; allow "Other"
    role = payload.target_role.strip()
    if not role:
        raise HTTPException(status_code=400, detail="Target role required")
    # Upsert state with status ready (or keep existing status but update role)
    existing = analysis_service.get_state(current_user.id)
    status = existing["status"] if existing else "not_started"
    # If not_started, move to ready after setting role (if profile/evidence will be validated on prepare)
    # Keep current status unless not_started -> ready if role set
    if status == "not_started":
        status = "ready"
    data = analysis_service.upsert_state(current_user.id, role, status, existing.get("last_retrieval") if existing else None)
    return data


@router.post("/prepare", response_model=PrepareAnalysisResponse)
async def prepare_analysis(
    payload: PrepareAnalysisRequest, current_user: CurrentUser = Depends(get_current_user)
):
    # Validate and do retrieval, update state to ready
    result = await analysis_service.prepare(current_user.id, payload.target_role)
    return result


# Phase 4C — Skill Engine
@router.post("/run")
async def run_skill_analysis(
    payload: PrepareAnalysisRequest, current_user: CurrentUser = Depends(get_current_user)
):
    # Uses same payload as prepare (target_role optional)
    result = await run_analysis(current_user.id, payload.target_role)
    return result


@router.get("/latest")
async def get_latest_analysis(current_user: CurrentUser = Depends(get_current_user)):
    c = get_supabase_client()
    if c is None:
        raise HTTPException(status_code=503, detail="Supabase not configured")
    try:
        r = c.table("analysis_results").select("*").eq("user_id", current_user.id).order("created_at", desc=True).limit(1).execute()
        if not r.data or len(r.data) == 0:
            raise HTTPException(status_code=404, detail="No analysis found — run analysis first")
        return r.data[0]
    except HTTPException:
        raise
    except Exception as e:
        m = str(e).lower()
        if "could not find the table" in m or "pgrst205" in m:
            raise HTTPException(status_code=503, detail="Analysis tables not found — run 005_skill_engine.sql")
        raise HTTPException(status_code=500, detail="Failed to fetch latest analysis")


@router.get("/skills")
async def get_latest_skills(current_user: CurrentUser = Depends(get_current_user)):
    c = get_supabase_client()
    if c is None:
        raise HTTPException(status_code=503, detail="Supabase not configured")
    # Get latest analysis id
    try:
        r = c.table("analysis_results").select("id").eq("user_id", current_user.id).order("created_at", desc=True).limit(1).execute()
        if not r.data or len(r.data) == 0:
            raise HTTPException(status_code=404, detail="No analysis found")
        analysis_id = r.data[0]["id"]
        # Get assessments for this analysis — but we stored assessments without analysis_id, just user_id
        # For now, get all assessments for user, ordered by created_at
        # In future, link via analysis_id, but for prototype we get latest
        r2 = c.table("skill_assessments").select("*, skills(canonical_name, display_name, category)").eq("user_id", current_user.id).order("created_at", desc=True).limit(50).execute()
        return r2.data or []
    except HTTPException:
        raise
    except Exception as e:
        m = str(e).lower()
        if "could not find the table" in m:
            raise HTTPException(status_code=503, detail="Skill tables not found")
        raise HTTPException(status_code=500, detail="Failed to fetch skills")


@router.get("/gaps")
async def get_latest_gaps(current_user: CurrentUser = Depends(get_current_user)):
    c = get_supabase_client()
    if c is None:
        raise HTTPException(status_code=503, detail="Supabase not configured")
    try:
        r = c.table("analysis_results").select("id").eq("user_id", current_user.id).order("created_at", desc=True).limit(1).execute()
        if not r.data or len(r.data) == 0:
            raise HTTPException(status_code=404, detail="No analysis found")
        analysis_id = r.data[0]["id"]
        r2 = c.table("skill_gaps").select("*, skills(canonical_name, display_name, category)").eq("user_id", current_user.id).eq("analysis_result_id", analysis_id).order("priority_score", desc=True).execute()
        return r2.data or []
    except HTTPException:
        raise
    except Exception as e:
        m = str(e).lower()
        if "could not find the table" in m:
            raise HTTPException(status_code=503, detail="Skill gaps table not found")
        raise HTTPException(status_code=500, detail="Failed to fetch gaps")
