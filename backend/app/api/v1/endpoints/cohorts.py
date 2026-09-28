"""P0 #3: cohort endpoints (thin routes -> cohort_supply_service).

Aggregate skill-supply responses never contain user_ids or per-member
evidence — only cohort-level statistics.
"""

from fastapi import APIRouter, Depends, Query
from typing import Optional

from ....core.security import get_current_user, CurrentUser
from ....schemas.cohorts import (
    CohortCreate,
    CohortUpdate,
    CohortResponse,
    CohortMemberCreate,
    CohortMemberUpdate,
    CohortMemberResponse,
    CohortSkillSupplyResponse,
    CourseCohortSupplyResponse,
)
from ....services import cohort_supply_service as svc

router = APIRouter(prefix="/cohorts", tags=["cohorts"])


@router.post("", response_model=CohortResponse, status_code=201)
def create_cohort(payload: CohortCreate, current_user: CurrentUser = Depends(get_current_user)):
    data = payload.model_dump()
    data["institution_id"] = str(data["institution_id"])
    data["course_id"] = str(data["course_id"])
    return svc.create_cohort(data)


@router.get("", response_model=list[CohortResponse])
def list_cohorts(
    course_id: Optional[str] = Query(None),
    institution_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
):
    return svc.list_cohorts(course_id, institution_id, status)


@router.get("/{cohort_id}", response_model=CohortResponse)
def get_cohort(cohort_id: str, current_user: CurrentUser = Depends(get_current_user)):
    return svc.get_cohort(cohort_id)


@router.patch("/{cohort_id}", response_model=CohortResponse)
def update_cohort(cohort_id: str, payload: CohortUpdate, current_user: CurrentUser = Depends(get_current_user)):
    clean = {k: v for k, v in payload.model_dump().items() if v is not None}
    if clean.get("start_date") is not None:
        clean["start_date"] = str(clean["start_date"])
    if clean.get("end_date") is not None:
        clean["end_date"] = str(clean["end_date"])
    return svc.update_cohort(cohort_id, clean)


@router.post("/{cohort_id}/members", response_model=CohortMemberResponse, status_code=201)
def add_member(cohort_id: str, payload: CohortMemberCreate, current_user: CurrentUser = Depends(get_current_user)):
    return svc.add_member(cohort_id, payload.user_id)


@router.get("/{cohort_id}/members", response_model=list[CohortMemberResponse])
def list_members(
    cohort_id: str,
    enrollment_status: Optional[str] = Query(None, pattern="^(active|completed|withdrawn)$"),
    current_user: CurrentUser = Depends(get_current_user),
):
    return svc.list_members(cohort_id, enrollment_status)


@router.patch("/{cohort_id}/members/{member_id}", response_model=CohortMemberResponse)
def update_member(
    cohort_id: str, member_id: str, payload: CohortMemberUpdate,
    current_user: CurrentUser = Depends(get_current_user),
):
    return svc.update_member(cohort_id, member_id, payload.enrollment_status)


@router.delete("/{cohort_id}/members/{member_id}", status_code=204)
def remove_member(cohort_id: str, member_id: str, current_user: CurrentUser = Depends(get_current_user)):
    # Withdraws (soft) — history rows are never hard-deleted by the API.
    svc.remove_member(cohort_id, member_id)
    return None


@router.get("/{cohort_id}/skill-supply", response_model=CohortSkillSupplyResponse)
def get_cohort_skill_supply(cohort_id: str, current_user: CurrentUser = Depends(get_current_user)):
    return svc.get_cohort_skill_supply(cohort_id)


course_cohort_router = APIRouter(prefix="/courses", tags=["courses"])


@course_cohort_router.get("/{course_id}/cohorts", response_model=list[CohortResponse])
def list_course_cohorts(course_id: str, current_user: CurrentUser = Depends(get_current_user)):
    return svc.list_cohorts(course_id=course_id)


@course_cohort_router.get("/{course_id}/cohort-supply", response_model=CourseCohortSupplyResponse)
def get_course_cohort_supply(course_id: str, current_user: CurrentUser = Depends(get_current_user)):
    return svc.get_course_cohort_supply(course_id)
