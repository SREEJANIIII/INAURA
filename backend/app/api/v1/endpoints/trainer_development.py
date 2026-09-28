"""P1.3: trainer development signal endpoint (thin route -> service).

Aggregate capability signals only — no trainer identities, no assignment,
no training plans.
"""

from fastapi import APIRouter, Depends, Query
from typing import Optional

from ....core.security import get_current_user, CurrentUser
from ....schemas.trainer_development import TrainerDevelopmentResponse
from ....services import trainer_development_service as svc

router = APIRouter(prefix="/industry", tags=["industry"])


@router.get("/trainer-development-signals", response_model=TrainerDevelopmentResponse)
def get_trainer_development_signals(
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
    signal: Optional[str] = Query(None, description="Signal type filter"),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Trainer development signals for a district + role.

    Projects observed trainer_skill mappings against teaching context and
    P1.1 priorities. Absence of a mapping is reported as absent evidence,
    never as inability; no trainer is ever assigned or recommended.
    """
    return svc.get_trainer_development_signals(
        district=district, role=role, state=state, country=country, city=city,
        region=region, start_date=start_date, end_date=end_date,
        provider_id=provider_id, course_id=course_id, skill=skill, signal=signal,
    )
