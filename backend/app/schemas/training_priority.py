from pydantic import BaseModel, Field
from typing import Optional, List


class PriorityMarketEvidence(BaseModel):
    trend: Optional[str] = None
    skill_share: Optional[float] = None
    posting_count: Optional[int] = None
    skill_posting_count: Optional[int] = None
    required_level: Optional[float] = None
    importance: Optional[float] = None
    market_confidence: Optional[float] = None
    match_type: Optional[str] = None
    provider_id: Optional[str] = None
    data_origin: Optional[str] = None
    evidence_suppressed: Optional[bool] = None


class PriorityCurriculumEvidence(BaseModel):
    courses_teaching: int = 0
    courses_missing: int = 0
    coverages: List[str] = Field(default_factory=list)


class PriorityLearnerEvidence(BaseModel):
    learner_count: int = 0
    evidenced_learner_count: int = 0
    verified_learner_count: int = 0
    evidence_coverage: Optional[float] = None
    verified_coverage: Optional[float] = None
    average_proficiency: Optional[float] = None
    supply_confidence: Optional[float] = None


class PriorityTrainerEvidence(BaseModel):
    trainer_count: int = 0
    institutions_with_skill_trainers: int = 0
    trainer_signal: Optional[str] = None
    capacity_status: Optional[str] = None


class TrainingPriorityEvidence(BaseModel):
    skill: Optional[str] = None
    market: PriorityMarketEvidence
    curriculum: PriorityCurriculumEvidence
    learner_supply: PriorityLearnerEvidence
    trainer: PriorityTrainerEvidence


class TrainingPriority(BaseModel):
    skill: str
    display_name: Optional[str] = None
    category: Optional[str] = None
    priority: str = Field(pattern="^(HIGH|MEDIUM|LOW|INSUFFICIENT_EVIDENCE)$")
    status: str = Field(pattern="^(aligned|actionable_gap|insufficient_evidence)$")
    reasons: List[str] = Field(default_factory=list)
    evidence: TrainingPriorityEvidence


class TrainingPrioritySummary(BaseModel):
    HIGH: int = 0
    MEDIUM: int = 0
    LOW: int = 0
    INSUFFICIENT_EVIDENCE: int = 0
    aligned_count: int = 0
    actionable_gap_count: int = 0
    total: int = 0


class TrainingPrioritiesResponse(BaseModel):
    district: str
    district_status: str
    state: Optional[str] = None
    country: Optional[str] = None
    role: str
    canonical_role: Optional[str] = None
    role_mapping_status: str
    market_context: Optional[dict] = None
    priorities: List[TrainingPriority]
    summary: TrainingPrioritySummary
    capacity_note: str = ""
    provenance: dict
    note: str = ""


class SkillPriorityResponse(TrainingPriority):
    district: str
    role: str
    market_context: Optional[dict] = None
    provenance: dict
