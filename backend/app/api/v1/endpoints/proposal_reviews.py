"""P1.5: proposal review endpoints (thin routes -> service).

Append-only human decisions. No PATCH (history rows are never edited);
new decisions — including re-review out of DEFERRED — arrive via POST.
Approval records a decision only and never mutates curriculum data.
"""

from fastapi import APIRouter, Depends, Query
from typing import Optional

from ....core.security import get_current_user, CurrentUser
from ....schemas.proposal_reviews import (
    ReviewCreate,
    ReviewResponse,
    ProposalStatusResponse,
)
from ....services import proposal_review_service as svc

router = APIRouter(prefix="/industry", tags=["industry"])


@router.get("/curriculum-reviews", response_model=list[ReviewResponse])
def list_reviews(
    proposal_id: Optional[str] = Query(None),
    course_id: Optional[str] = Query(None),
    district: Optional[str] = Query(None),
    decision: Optional[str] = Query(None, description="APPROVED, REJECTED, or DEFERRED"),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Review history reads (governance transparency)."""
    return svc.list_reviews(proposal_id=proposal_id, course_id=course_id,
                            district=district, decision=decision)


@router.post("/curriculum-reviews", response_model=ReviewResponse, status_code=201)
def create_review(payload: ReviewCreate, current_user: CurrentUser = Depends(get_current_user)):
    """Record one human decision on a live P1.2 proposal.

    The proposal must exist in the current projection (404 otherwise);
    transitions follow the explicit graph; REJECTED/DEFERRED require a
    reason. The reviewer is the authenticated caller.
    """
    data = payload.model_dump()
    return svc.create_review(
        current_user.id, data.pop("proposal_id"), data.pop("district"),
        data.pop("role"), data.pop("decision"), data.pop("reason", None), **data,
    )


@router.get("/curriculum-reviews/{proposal_id}", response_model=ProposalStatusResponse)
def get_proposal_status(
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
    course_id: Optional[str] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Current review status + full append-only history for one proposal."""
    return svc.get_proposal_status(
        proposal_id, district, role, state=state, country=country, city=city,
        region=region, start_date=start_date, end_date=end_date,
        provider_id=provider_id, course_id=course_id,
    )
