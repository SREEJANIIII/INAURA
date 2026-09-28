"""P1.4: capacity planning signal endpoint (thin route -> service).

Planning inputs only: observed counts plus an explicit statement that seat
capacity is not measured. No seat, ratio, or shortage claims.
"""

from fastapi import APIRouter, Depends, Query
from typing import Optional

from ....core.security import get_current_user, CurrentUser
from ....schemas.capacity_planning import CapacityPlanningResponse
from ....services import capacity_planning_service as svc

router = APIRouter(prefix="/industry", tags=["industry"])


@router.get("/capacity-planning", response_model=CapacityPlanningResponse)
def get_capacity_planning(
    district: str = Query(..., description="District name, e.g. Bengaluru Urban"),
    role: str = Query(..., description="Target role, e.g. Software Engineer"),
    state: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    region: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    provider_id: Optional[str] = Query(None),
    course_id: Optional[str] = Query(None, description="Scope to a single course UUID"),
    skill: Optional[str] = Query(None, description="Canonical skill slug, e.g. docker"),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Capacity planning signals for a district + role.

    Returns observed institutions/courses/learners/trainers per prioritized
    skill with capacity_status CAPACITY_DATA_INSUFFICIENT, because no
    validated seat-capacity source exists. Missing data is never presented
    as zero capacity or as an observed shortage.
    """
    return svc.get_capacity_planning(
        district=district, role=role, state=state, country=country, city=city,
        region=region, start_date=start_date, end_date=end_date,
        provider_id=provider_id, course_id=course_id, skill=skill,
    )
