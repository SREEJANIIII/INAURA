"""P1.6: outcome feedback endpoint (thin route -> service).

Observational aggregates only: sample sizes, placement/feedback counts,
periods, signals, and limitations. No causal claims, no individual records,
no writes to skill or gap mathematics.
"""

from fastapi import APIRouter, Depends, Query
from typing import Optional

from ....core.security import get_current_user, CurrentUser
from ....schemas.outcome_feedback import (
    OutcomeFeedbackResponse,
    SkillOutcomeDetailResponse,
)
from ....services import outcome_feedback_service as svc

router = APIRouter(prefix="/industry", tags=["industry"])


@router.get("/outcome-feedback", response_model=OutcomeFeedbackResponse)
def get_outcome_feedback(
    district: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
    course_id: Optional[str] = Query(None),
    institution_id: Optional[str] = Query(None),
    skill: Optional[str] = Query(None, description="Canonical skill slug, e.g. docker"),
    proposal_id: Optional[str] = Query(None, description="P1.2 proposal id (resolves course + skill)"),
    start_date: Optional[str] = Query(None, description="Observation window start (ISO)"),
    end_date: Optional[str] = Query(None, description="Observation window end (ISO)"),
    state: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    region: Optional[str] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Outcome feedback signals: what happened after training signals.

    Joins existing outcome records (applications, employer/skill feedback,
    qualification alignments, placements) to skill/role/course/district via
    canonical IDs. Co-occurrence is reported as co-occurrence; causal impact
    is never claimed. Small samples are suppressed with explicit limits.
    """
    return svc.get_outcome_feedback(
        district=district, role=role, course_id=course_id,
        institution_id=institution_id, skill=skill, proposal_id=proposal_id,
        start_date=start_date, end_date=end_date,
        state=state, country=country, city=city, region=region,
    )


@router.get("/outcome-feedback/{skill}", response_model=SkillOutcomeDetailResponse)
def get_skill_outcome_feedback(
    skill: str,
    district: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
    course_id: Optional[str] = Query(None),
    institution_id: Optional[str] = Query(None),
    proposal_id: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    region: Optional[str] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Single-skill outcome feedback lookup."""
    return svc.get_skill_outcome_feedback(
        skill, district=district, role=role, course_id=course_id,
        institution_id=institution_id, proposal_id=proposal_id,
        start_date=start_date, end_date=end_date,
        state=state, country=country, city=city, region=region,
    )
