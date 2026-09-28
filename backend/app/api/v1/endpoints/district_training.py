"""P0 #5: district training intelligence endpoint (thin route -> service).

Single comprehensive endpoint: aggregate analytics only, no student-level
data, no seat recommendations (the service states this explicitly).
"""

from fastapi import APIRouter, Depends, Query
from typing import Optional

from ....core.security import get_current_user, CurrentUser
from ....schemas.district_training import DistrictTrainingResponse
from ....services import district_training_service as svc

router = APIRouter(prefix="/industry", tags=["industry"])


@router.get("/district-training", response_model=DistrictTrainingResponse)
def get_district_training(
    district: str = Query(..., description="District name, e.g. Bengaluru Urban"),
    role: str = Query(..., description="Target role, e.g. Software Engineer"),
    state: Optional[str] = Query(None, description="State/region context, e.g. Karnataka"),
    country: Optional[str] = Query(None),
    city: Optional[str] = Query(None, description="City-scoped demand where available"),
    region: Optional[str] = Query(None, description="Explicit override for state/region context"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    provider_id: Optional[str] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
):
    """District training intelligence: evidence-backed planning inputs.

    Composes P0 #1 demand (via P0 #4 alignment), P0 #2 institutions/courses/
    trainers, and P0 #3 cohort supply with learner-weighted aggregation.
    Global demand is labelled fallback_global, never presented as district
    demand; suppressed small-cohort detail propagates.
    """
    return svc.get_district_training(
        district=district, role=role, state=state, country=country, city=city,
        region=region, start_date=start_date, end_date=end_date, provider_id=provider_id,
    )
