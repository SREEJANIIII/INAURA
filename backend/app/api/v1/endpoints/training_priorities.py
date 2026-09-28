"""P1.1: training priority endpoints (thin routes -> service).

Aggregate planning signals only — no student-level data, no seat
recommendations, no LLM involvement.
"""

from fastapi import APIRouter, Depends, Query
from typing import Optional

from ....core.security import get_current_user, CurrentUser
from ....schemas.training_priority import (
    TrainingPrioritiesResponse,
    SkillPriorityResponse,
)
from ....services import training_priority_service as svc

router = APIRouter(prefix="/industry", tags=["industry"])


@router.get("/training-priorities", response_model=TrainingPrioritiesResponse)
def get_training_priorities(
    district: str = Query(..., description="District name, e.g. Bengaluru Urban"),
    role: str = Query(..., description="Target role, e.g. Software Engineer"),
    state: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    region: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    provider_id: Optional[str] = Query(None),
    priority: Optional[str] = Query(None, description="Filter: HIGH, MEDIUM, LOW, INSUFFICIENT_EVIDENCE"),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Deterministic training priorities for a district + role.

    Projects P0 #5 district rows through the reused P0 #4 rule outcome:
    missing market evidence or undecidable attainment becomes
    INSUFFICIENT_EVIDENCE (never LOW/HIGH); aligned skills keep their
    aligned status instead of a LOW label. Ordered by level, then observed
    share, then skill — no numerical score.
    """
    return svc.get_training_priorities(
        district=district, role=role, state=state, country=country, city=city,
        region=region, start_date=start_date, end_date=end_date,
        provider_id=provider_id, priority=priority,
    )


@router.get("/training-priorities/{skill}", response_model=SkillPriorityResponse)
def get_skill_priority(
    skill: str,
    district: str = Query(...),
    role: str = Query(...),
    state: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    region: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    provider_id: Optional[str] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Single-skill evidence packet (lookup for review/detail views)."""
    return svc.get_skill_priority(
        skill, district=district, role=role, state=state, country=country,
        city=city, region=region, start_date=start_date, end_date=end_date,
        provider_id=provider_id,
    )
