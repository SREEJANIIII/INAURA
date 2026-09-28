from pydantic import BaseModel, Field
from typing import Optional, List


class ProposalSkill(BaseModel):
    id: str
    name: str


class ProposalPriority(BaseModel):
    level: str = Field(pattern="^(HIGH|MEDIUM|LOW|INSUFFICIENT_EVIDENCE)$")
    status: str = Field(pattern="^(aligned|actionable_gap|insufficient_evidence)$")
    reasons: List[str] = Field(default_factory=list)


class CurriculumProposalAction(BaseModel):
    type: str = Field(pattern="^(ADD_SKILL|INCREASE_COVERAGE|ADD_PRACTICAL_ASSESSMENT|UPDATE_MODULE|REVIEW_CONTENT)$")
    status: str = Field(pattern="^(PENDING_REVIEW)$")


class ProposalCurrentState(BaseModel):
    curriculum_status: Optional[str] = None
    coverage: Optional[str] = None
    modules: List[str] = Field(default_factory=list)
    learner_attainment: Optional[str] = None
    verified_coverage: Optional[float] = None
    market_status: Optional[str] = None
    trend: Optional[str] = None
    skill_share: Optional[float] = None


class ProposalChange(BaseModel):
    action_type: str
    skill: str
    target: str = Field(pattern="^(course|module)$")
    module_ids: List[str] = Field(default_factory=list)
    module_names: List[str] = Field(default_factory=list)


class CurriculumProposalReason(BaseModel):
    text: str


class CurriculumProposal(BaseModel):
    proposal_id: str
    course_id: str
    course_name: Optional[str] = None
    institution_id: str
    institution_name: Optional[str] = None
    district: str
    role: str
    skill: ProposalSkill
    priority: ProposalPriority
    action: CurriculumProposalAction
    title: str
    rationale: List[str] = Field(default_factory=list)
    current_state: ProposalCurrentState
    proposed_change: ProposalChange
    evidence: dict
    market_context: dict
    provenance: dict


class CurriculumProposalEvidence(BaseModel):
    market: dict
    curriculum: dict
    learner_supply: dict
    trainer: dict


class CurriculumProposalSummary(BaseModel):
    total: int = 0
    by_action: dict = Field(default_factory=dict)
    high_priority: int = 0


class CurriculumProposalsResponse(BaseModel):
    district: str
    district_status: Optional[str] = None
    role: str
    canonical_role: Optional[str] = None
    role_mapping_status: str
    market_context: Optional[dict] = None
    proposals: List[CurriculumProposal]
    summary: CurriculumProposalSummary
    provenance: dict
    note: str = ""
