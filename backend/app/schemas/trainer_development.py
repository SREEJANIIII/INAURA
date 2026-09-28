from pydantic import BaseModel, Field
from typing import Optional, List


class TrainerSignalPriority(BaseModel):
    level: Optional[str] = None
    status: Optional[str] = None
    reasons: List[str] = Field(default_factory=list)


class TrainerSignalEvidence(BaseModel):
    trainer_count: int = 0
    institutions_with_skill_trainers: int = 0
    institutions_teaching: int = 0
    trainers_in_teaching_institutions: int = 0
    proficiency_breakdown: dict = Field(default_factory=dict)


class RelatedProposal(BaseModel):
    proposal_id: str
    course_id: str
    action_type: str
    priority: str


class TrainerDevelopmentSignal(BaseModel):
    skill: str
    display_name: Optional[str] = None
    signal: str = Field(pattern="^(DEVELOPMENT_SIGNAL|SUFFICIENT_EVIDENCE|INSUFFICIENT_EVIDENCE)$")
    signal_type: str = Field(pattern="^(NO_TRAINER_OBSERVED|LOW_TRAINER_COVERAGE|SKILL_TRAINER_MISMATCH|TRAINER_CAPABILITY_OBSERVED|TRAINER_DATA_INSUFFICIENT)$")
    reasons: List[str] = Field(default_factory=list)
    priority: TrainerSignalPriority
    trainer_evidence: TrainerSignalEvidence
    related_proposals: List[RelatedProposal] = Field(default_factory=list)
    market_context: dict = Field(default_factory=dict)


class TrainerDevelopmentResponse(BaseModel):
    district: str
    district_status: str
    role: str
    canonical_role: Optional[str] = None
    role_mapping_status: str
    course_id: Optional[str] = None
    market_context: Optional[dict] = None
    signals: List[TrainerDevelopmentSignal]
    summary: dict
    provenance: dict
    note: str = ""
