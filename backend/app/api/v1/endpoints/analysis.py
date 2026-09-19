from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel
from ....schemas.analysis import AnalysisStateResponse, SetTargetRoleRequest, PrepareAnalysisRequest, PrepareAnalysisResponse
from ....services import analysis_service, evidence_service, skill_engine
from ....services.analysis_run_service import run_analysis
from ....core.security import get_current_user, CurrentUser
from ....core.supabase import get_supabase_client
from typing import List, Optional

router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.get("/state", response_model=AnalysisStateResponse)
def get_analysis_state(current_user: CurrentUser = Depends(get_current_user)):
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


def with_freshness(row: dict, user_id: str) -> dict:
    """Add whether a saved analysis still reflects the student's evidence and the current scoring.

    evidence_changed: True/False when the run recorded what it was based on; None for older
    runs that didn't. scoring_outdated: the run used an older version of the readiness formula.
    """
    recorded = (row.get("metadata") or {}).get("evidence_fingerprint")
    changed = None
    if recorded:
        current = evidence_service.current_evidence_fingerprint(user_id)
        changed = None if current is None else current != recorded
    return {
        **row,
        "evidence_changed": changed,
        "scoring_outdated": bool(row.get("engine_version")) and row.get("engine_version") != skill_engine.ENGINE_VERSION,
    }


@router.get("/latest")
def get_latest_analysis(current_user: CurrentUser = Depends(get_current_user)):
    c = get_supabase_client()
    if c is None:
        raise HTTPException(status_code=503, detail="Supabase not configured")
    try:
        r = c.table("analysis_results").select("*").eq("user_id", current_user.id).order("created_at", desc=True).limit(1).execute()
        if not r.data or len(r.data) == 0:
            raise HTTPException(status_code=404, detail="No analysis found — run analysis first")
        return with_freshness(r.data[0], current_user.id)
    except HTTPException:
        raise
    except Exception as e:
        m = str(e).lower()
        if "could not find the table" in m or "pgrst205" in m:
            raise HTTPException(status_code=503, detail="Analysis tables not found — run 005_skill_engine.sql")
        raise HTTPException(status_code=500, detail="Failed to fetch latest analysis")


@router.get("/skills")
def get_latest_skills(current_user: CurrentUser = Depends(get_current_user)):
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
def get_latest_gaps(current_user: CurrentUser = Depends(get_current_user)):
    c = get_supabase_client()
    if c is None:
        raise HTTPException(status_code=503, detail="Supabase not configured")
    try:
        r = c.table("analysis_results").select("id").eq("user_id", current_user.id).order("created_at", desc=True).limit(1).execute()
        if not r.data or len(r.data) == 0:
            raise HTTPException(status_code=404, detail="No analysis found")
        analysis_id = r.data[0]["id"]
        r2 = c.table("skill_gaps").select("*, skills(canonical_name, display_name, category)").eq("user_id", current_user.id).eq("analysis_result_id", analysis_id).order("priority_score", desc=True).execute()
        gaps = r2.data or []
        # Enrich gaps with provenance from skill_assessments (same analysis run)
        try:
            r3 = c.table("skill_assessments").select("*").eq("user_id", current_user.id).order("created_at", desc=True).limit(100).execute()
            assess_map = {}
            for a in (r3.data or []):
                # Use skill_id as key
                sid = a.get("skill_id")
                if sid and sid not in assess_map:
                    assess_map[sid] = a
            for g in gaps:
                sid = g.get("skill_id")
                a = assess_map.get(sid)
                if a:
                    meta = a.get("metadata") or {}
                    g["evidence_sources"] = meta.get("evidence_sources", [])
                    g["evidence_state"] = meta.get("evidence_state", g.get("evidence_state", "no_evidence"))
                    g["evidence_state_label"] = meta.get("evidence_state_label", "No evidence")
                    g["is_portfolio"] = meta.get("is_portfolio", False)
                    g["is_overridden"] = meta.get("is_overridden", False)
                    g["has_assessment"] = a.get("has_assessment", False)
                    g["assessment_score"] = a.get("assessment_score")
                    g["evidence_count"] = a.get("evidence_count", 0)
                    g["source_diversity"] = a.get("source_diversity", 0)
                else:
                    # Fallback defaults for older analyses
                    g["evidence_sources"] = []
                    g["evidence_state"] = "no_evidence" if g.get("current_proficiency", 0) == 0 else "evidence_estimate"
                    g["evidence_state_label"] = "No evidence" if g.get("current_proficiency", 0) == 0 else "Evidence-based estimate"
                    g["is_portfolio"] = False
                    g["is_overridden"] = False
        except Exception:
            pass
        return gaps
    except HTTPException:
        raise
    except Exception as e:
        m = str(e).lower()
        if "could not find the table" in m:
            raise HTTPException(status_code=503, detail="Skill gaps table not found")
        raise HTTPException(status_code=500, detail="Failed to fetch gaps")


# ---------------------------------------------------------------------------
# Skill overrides & personalization (downward only)
# ---------------------------------------------------------------------------
class SkillOverrideRequest(BaseModel):
    skill: str

class SkillOverrideResponse(BaseModel):
    skill_name: str
    skill_key: str
    is_zero_override: bool
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

@router.get("/skill-overrides")
def list_skill_overrides(current_user: CurrentUser = Depends(get_current_user)):
    return evidence_service.list_skill_overrides(current_user.id)

@router.post("/skill-overrides", response_model=SkillOverrideResponse, status_code=201)
async def create_skill_override(
    payload: SkillOverrideRequest, current_user: CurrentUser = Depends(get_current_user)
):
    """
    Safe downward personalization: 'I don't actually know this yet'.
    Forces effective proficiency to 0, preserves history, excludes evidence.
    Requires explicit skill name, no arbitrary proficiency values.
    """
    result = evidence_service.set_skill_override(current_user.id, payload.skill, True)
    # Trigger recalculation so readiness/gaps update immediately
    try:
        from ....services import analysis_service as _as
        state = _as.get_state(current_user.id)
        if state and state.get("target_role"):
            await run_analysis(current_user.id, state["target_role"])
    except Exception:
        pass
    return {
        "skill_name": result.get("skill_name"),
        "skill_key": result.get("skill_key"),
        "is_zero_override": True,
        "created_at": result.get("created_at"),
        "updated_at": result.get("updated_at"),
    }

@router.delete("/skill-overrides/{skill_key}", status_code=204)
async def delete_skill_override(
    skill_key: str, current_user: CurrentUser = Depends(get_current_user)
):
    """
    Remove an override. Not exposed as 'manual increase' in UI; only via new
    evidence or assessment flow, or for testing. Frontend does not offer a
    generic 'increase proficiency' control.
    """
    evidence_service.delete_skill_override(current_user.id, skill_key)
    # Recalculate
    try:
        from ....services import analysis_service as _as
        state = _as.get_state(current_user.id)
        if state and state.get("target_role"):
            await run_analysis(current_user.id, state["target_role"])
    except Exception:
        pass
    return None


@router.post("/refresh")
async def refresh_analysis(current_user: CurrentUser = Depends(get_current_user)):
    """Refresh evidence audit, re-run analysis, and update learner skill states."""
    state = analysis_service.get_state(current_user.id)
    role = state.get("target_role") if state else None
    if not role:
        try:
            c = get_supabase_client()
            r = c.table("analysis_results").select("target_role").eq("user_id", current_user.id).order("created_at", desc=True).limit(1).execute()
            if r.data and len(r.data) > 0:
                role = r.data[0].get("target_role")
        except Exception:
            pass
    if not role:
        role = "Software Engineer"
    result = await run_analysis(current_user.id, role)
    return result


@router.get("/evidence-summary")
def get_evidence_summary(current_user: CurrentUser = Depends(get_current_user)):
    """Return honest evidence audit: sources analyzed, available, unavailable, and snapshot."""
    from ....services import learner_state_service
    sources_analyzed, sources_available, sources_unavailable = learner_state_service.audit_user_sources(current_user.id)
    snapshot = learner_state_service.get_latest_evidence_snapshot(current_user.id)
    return {
        "user_id": current_user.id,
        "sources_analyzed": sources_analyzed,
        "sources_available": sources_available,
        "sources_unavailable": sources_unavailable,
        "latest_snapshot": snapshot,
    }

