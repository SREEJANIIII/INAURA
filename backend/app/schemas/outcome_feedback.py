from pydantic import BaseModel, Field
from typing import Optional, List


class OutcomeSample(BaseModel):
    feedback_count: Optional[int] = None
    feedback_suppressed: bool = False
    placement_count: Optional[int] = None
    placements_suppressed: bool = False
    successful_placements: Optional[int] = None
    alignment_count: int = 0


class OutcomeEmployerFeedback(BaseModel):
    observations: int = 0
    average_observed_minus_expected: Optional[float] = None
    average_coverage: Optional[float] = None


class SkillOutcomeFeedback(BaseModel):
    skill: str
    display_name: Optional[str] = None
    signal: str = Field(pattern="^(SUPPORTIVE_SIGNAL|MIXED_SIGNAL|CONTRADICTORY_SIGNAL|INSUFFICIENT_OUTCOME_EVIDENCE)$")
    limitation: str = ""
    sample: OutcomeSample
    employer_feedback: OutcomeEmployerFeedback
    training_priority: Optional[str] = None
    observed_mismatch: bool = False


class OutcomeFeedbackSummary(BaseModel):
    skills_observed: int = 0
    supportive: int = 0
    mixed: int = 0
    contradictory: int = 0
    insufficient: int = 0
    observed_mismatches: int = 0


class OutcomeFeedbackResponse(BaseModel):
    district: Optional[str] = None
    role: Optional[str] = None
    canonical_role: Optional[str] = None
    role_mapping_status: str
    course_id: Optional[str] = None
    institution_id: Optional[str] = None
    proposal_id: Optional[str] = None
    observation_period: dict
    skills: List[SkillOutcomeFeedback]
    summary: OutcomeFeedbackSummary
    provenance: dict
    note: str = ""


class SkillOutcomeDetailResponse(SkillOutcomeFeedback):
    district: Optional[str] = None
    role: Optional[str] = None
    observation_period: dict = Field(default_factory=dict)
    provenance: dict = Field(default_factory=dict)
