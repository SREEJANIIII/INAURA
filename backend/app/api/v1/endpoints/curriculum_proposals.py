"""P1.2: curriculum proposal endpoints (thin routes -> service).

Proposals are human-reviewable planning artifacts: every record starts
PENDING_REVIEW, nothing here mutates curriculum data, and no approval
workflow exists yet.
"""

from fastapi import APIRouter, Depends, Query
from typing import Optional

from ....core.security import get_current_user, CurrentUser
from ....schemas.curriculum_proposals import (
    CurriculumProposal,
    CurriculumProposalsResponse,
)
from ....services import curriculum_proposal_service as svc

router = APIRouter(prefix="/industry", tags=["industry"])


@router.get("/curriculum-proposals", response_model=CurriculumProposalsResponse)
def get_curriculum_proposals(
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
    action_type: Optional[str] = Query(None, description="One of the five controlled actions"),
    priority: Optional[str] = Query(None, description="HIGH, MEDIUM, LOW, INSUFFICIENT_EVIDENCE"),
    status: Optional[str] = Query(None, description="Review status (PENDING_REVIEW for now)"),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Deterministic curriculum change proposals for a district + role.

    One record per course + skill; separate courses never merge. Only
    HIGH/MEDIUM priorities with decidable evidence produce proposals —
    INSUFFICIENT_EVIDENCE and LOW stay proposal-free. Statuses start at
    PENDING_REVIEW; generation never touches curriculum tables.
    """
    return svc.get_curriculum_proposals(
        district=district, role=role, state=state, country=country, city=city,
        region=region, start_date=start_date, end_date=end_date,
        provider_id=provider_id, course_id=course_id, skill=skill,
        action_type=action_type, priority=priority, status=status,
    )


@router.get("/curriculum-proposals/{proposal_id}", response_model=CurriculumProposal)
def get_curriculum_proposal(
    proposal_id: str,
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
    """Single proposal lookup (detail for human-review views)."""
    return svc.get_curriculum_proposal(
        proposal_id, district=district, role=role, state=state,
        country=country, city=city, region=region, start_date=start_date,
        end_date=end_date, provider_id=provider_id,
    )
