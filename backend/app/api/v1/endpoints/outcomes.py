"""Person 2: requirement + outcome endpoints (thin routes -> services)."""

from fastapi import APIRouter, Depends, HTTPException, Header
from typing import Optional

from ....core.security import get_current_user, CurrentUser
from ....core.config import get_settings
from ....schemas.employers import (
    RequirementUpdate,
    RequirementOut,
    RequirementSkillsBulk,
    RequirementSkillOut,
)
from ....schemas.outcomes import (
    ApplicationCreate,
    ApplicationOut,
    ApplicationDetailOut,
    StatusTransitionIn,
    EmployerFeedbackCreate,
    EmployerFeedbackOut,
    PlacementCreate,
    PlacementUpdate,
    PlacementOut,
    AlignmentCreate,
    AlignmentOut,
    DashboardOut,
    IndustryOutcomeSignal,
)
from ....schemas.industry_outcomes import (
    ObservationRefreshRequest,
    ObservationRefreshResponse,
)
from ....services import employer_service as empsvc
from ....services import outcome_service as svc
from ....services import industry_outcome_service as obs

router = APIRouter(prefix="/outcomes", tags=["outcomes"])

requirements_router = APIRouter(prefix="/requirements", tags=["requirements"])


@requirements_router.get("/{requirement_id}", response_model=RequirementOut)
def get_requirement(requirement_id: str, current_user: CurrentUser = Depends(get_current_user)):
    return empsvc.get_requirement(current_user.id, requirement_id)


@requirements_router.patch("/{requirement_id}", response_model=RequirementOut)
def update_requirement(requirement_id: str, payload: RequirementUpdate, current_user: CurrentUser = Depends(get_current_user)):
    clean = {k: v for k, v in payload.model_dump().items() if v is not None}
    return empsvc.update_requirement(current_user.id, requirement_id, clean)


@requirements_router.delete("/{requirement_id}", status_code=204)
def delete_requirement(requirement_id: str, current_user: CurrentUser = Depends(get_current_user)):
    empsvc.delete_requirement(current_user.id, requirement_id)
    return None


@requirements_router.get("/{requirement_id}/skills", response_model=list[RequirementSkillOut])
def list_requirement_skills(requirement_id: str, current_user: CurrentUser = Depends(get_current_user)):
    return empsvc.list_requirement_skills(current_user.id, requirement_id)


@requirements_router.put("/{requirement_id}/skills", response_model=list[RequirementSkillOut])
def set_requirement_skills(requirement_id: str, payload: RequirementSkillsBulk, current_user: CurrentUser = Depends(get_current_user)):
    return empsvc.set_requirement_skills(
        current_user.id, requirement_id, [s.model_dump() for s in payload.skills]
    )


@router.post("/applications", response_model=ApplicationOut, status_code=201)
def create_application(payload: ApplicationCreate, current_user: CurrentUser = Depends(get_current_user)):
    return svc.create_application(current_user.id, str(payload.hiring_requirement_id))


@router.get("/applications", response_model=list[ApplicationOut])
def list_applications(status: Optional[str] = None, current_user: CurrentUser = Depends(get_current_user)):
    if status and status not in ("saved", "applied", "screening", "interview", "offer_received", "selected", "rejected", "withdrawn"):
        raise HTTPException(status_code=400, detail="Invalid status filter")
    return svc.list_applications(current_user.id, status)


@router.get("/applications/{app_id}", response_model=ApplicationDetailOut)
def get_application(app_id: str, current_user: CurrentUser = Depends(get_current_user)):
    return svc.get_application_detail(current_user.id, app_id)


@router.patch("/applications/{app_id}/status", response_model=ApplicationOut)
def transition_application(app_id: str, payload: StatusTransitionIn, current_user: CurrentUser = Depends(get_current_user)):
    return svc.transition_status(app_id, current_user.id, payload.to_status, payload.note)


@router.post("/applications/{app_id}/feedback", response_model=EmployerFeedbackOut, status_code=201)
def submit_feedback(app_id: str, payload: EmployerFeedbackCreate, current_user: CurrentUser = Depends(get_current_user)):
    data = payload.model_dump()
    data["skills"] = [s.model_dump() if hasattr(s, "model_dump") else s for s in payload.skills]
    return svc.submit_feedback(current_user.id, app_id, data)


@router.get("/applications/{app_id}/feedback", response_model=EmployerFeedbackOut)
def get_feedback(app_id: str, current_user: CurrentUser = Depends(get_current_user)):
    return svc.get_feedback(current_user.id, app_id)


@router.post("/placements", response_model=PlacementOut, status_code=201)
def create_placement(payload: PlacementCreate, current_user: CurrentUser = Depends(get_current_user)):
    return svc.create_placement(current_user.id, payload.model_dump())


@router.get("/placements", response_model=list[PlacementOut])
def list_placements(current_user: CurrentUser = Depends(get_current_user)):
    return svc.list_placements(current_user.id)


@router.patch("/placements/{placement_id}", response_model=PlacementOut)
def update_placement(placement_id: str, payload: PlacementUpdate, current_user: CurrentUser = Depends(get_current_user)):
    clean = {k: v for k, v in payload.model_dump().items() if v is not None}
    return svc.update_placement(current_user.id, placement_id, clean)


@router.post("/placements/{placement_id}/confirm", response_model=PlacementOut)
def confirm_placement(placement_id: str, current_user: CurrentUser = Depends(get_current_user)):
    return svc.confirm_placement(current_user.id, placement_id, True)


@router.post("/alignments", response_model=AlignmentOut, status_code=201)
def create_alignment(payload: AlignmentCreate, current_user: CurrentUser = Depends(get_current_user)):
    return svc.create_alignment(current_user.id, payload.model_dump())


@router.get("/alignments", response_model=list[AlignmentOut])
def list_alignments(hiring_requirement_id: Optional[str] = None, current_user: CurrentUser = Depends(get_current_user)):
    return svc.list_alignments(current_user.id, hiring_requirement_id)


@router.get("/dashboard", response_model=DashboardOut)
def get_dashboard(
    employer_id: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    current_user: CurrentUser = Depends(get_current_user),
):
    return svc.get_dashboard(current_user.id, employer_id, from_date, to_date)


@router.get("/industry-signals", response_model=IndustryOutcomeSignal)
def get_industry_signals(
    role: Optional[str] = None,
    location: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    skill_id: Optional[str] = None,
    current_user: CurrentUser = Depends(get_current_user),
):
    if skill_id:
        return svc.get_industry_skill_signal(skill_id, role, location, from_date, to_date)
    return svc.get_industry_signals(role, location, from_date, to_date)


@router.post("/observations/refresh", response_model=ObservationRefreshResponse)
def refresh_observations(
    payload: ObservationRefreshRequest,
    current_user: CurrentUser = Depends(get_current_user),
    x_outcome_refresh_key: Optional[str] = Header(None, alias="X-Outcome-Refresh-Key"),
):
    """Phase 3 internal refresh: recompute observation cells for a window and
    upsert by (role, skill, scope, location, window_to). Gated by
    OUTCOME_REFRESH_KEY — disabled (503) when unset so ordinary authenticated
    callers (students, employers) can never write observations."""
    settings = get_settings()
    if not settings.outcome_refresh_key:
        raise HTTPException(status_code=503, detail="Observation refresh is not configured")
    if x_outcome_refresh_key != settings.outcome_refresh_key:
        raise HTTPException(status_code=403, detail="Invalid refresh key")
    result = obs.refresh_observations(
        role=payload.role,
        skill=payload.skill,
        location=payload.location,
        scope=payload.scope,
        from_s=payload.window_from,
        to_s=payload.window_to,
    )
    # Phase 3: bust the industry read cache so fresh overlays are served.
    # Best-effort: refresh results stand even if cache clearing fails.
    try:
        from ....services import industry_service
        industry_service.clear_industry_cache()
    except Exception:
        pass
    return result
