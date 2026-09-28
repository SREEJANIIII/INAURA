from pydantic import BaseModel, Field
from typing import Optional, List


class ReviewCreate(BaseModel):
    proposal_id: str = Field(..., min_length=1, max_length=120)
    district: str = Field(..., min_length=1, max_length=200)
    role: str = Field(..., min_length=1, max_length=150)
    decision: str = Field(..., pattern="^(APPROVED|REJECTED|DEFERRED)$")
    reason: Optional[str] = Field(None, max_length=2000)
    # Optional P1.2 context scoping the proposal lookup (same semantics).
    state: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    region: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    provider_id: Optional[str] = None
    course_id: Optional[str] = None


class ReviewResponse(BaseModel):
    id: str
    proposal_id: str
    district: str
    role: str
    course_id: Optional[str] = None
    institution_id: Optional[str] = None
    skill_slug: Optional[str] = None
    action_type: Optional[str] = None
    reviewer_id: Optional[str] = None
    from_status: Optional[str] = None
    to_status: str
    reason: Optional[str] = None
    created_at: str
    current_status: Optional[str] = None

    class Config:
        from_attributes = True


class ProposalStatusResponse(BaseModel):
    proposal_id: str
    course_id: Optional[str] = None
    current_status: str
    decisions: int = 0
    history: List[dict] = Field(default_factory=list)
    proposal: dict = Field(default_factory=dict)
