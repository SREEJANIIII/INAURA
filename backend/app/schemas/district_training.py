from pydantic import BaseModel, Field
from typing import Optional, List


class DistrictMarketContext(BaseModel):
    role: Optional[str] = None
    country: Optional[str] = None
    region: Optional[str] = None
    city: Optional[str] = None
    match_type: str = "insufficient_data"
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    providers: List[str] = Field(default_factory=list)
    data_origins: List[str] = Field(default_factory=list)
    demand_row_count: int = 0


class DistrictSkillMarket(BaseModel):
    skill_share: Optional[float] = None
    demand: Optional[float] = None
    trend: Optional[str] = None
    confidence: Optional[float] = None
    posting_count: Optional[int] = None
    skill_posting_count: Optional[int] = None
    period: Optional[dict] = None
    provider_id: Optional[str] = None
    data_origin: Optional[str] = None
    evidence_suppressed: Optional[bool] = None


class DistrictTrainingSupply(BaseModel):
    institution_count: int = 0
    institutions_teaching: int = 0
    course_count: int = 0
    courses_teaching: int = 0
    cohort_count: int = 0
    learner_count: int = 0
    evidenced_learner_count: int = 0
    verified_learner_count: int = 0
    evidence_coverage: Optional[float] = None
    verified_coverage: Optional[float] = None
    average_proficiency: Optional[float] = None
    average_confidence: Optional[float] = None
    qualifying_signal_count: int = 0


class DistrictCurriculumBlock(BaseModel):
    courses_teaching: int = 0
    courses_missing: int = 0
    coverages: List[str] = Field(default_factory=list)


class DistrictTrainerSignal(BaseModel):
    trainer_count: int = 0
    institutions_with_skill_trainers: int = 0
    trainer_skill_coverage: Optional[float] = None
    trainer_signal: str = "not_applicable"
    capacity_status: str = "insufficient_data"


class DistrictSkillGap(BaseModel):
    curriculum: Optional[str] = None
    attainment: Optional[str] = None
    concentration: Optional[str] = None


class DistrictPrioritySignal(BaseModel):
    level: str
    reasons: List[str] = Field(default_factory=list)


class DistrictSkillIntelligence(BaseModel):
    skill: str
    display_name: Optional[str] = None
    category: Optional[str] = None
    market: Optional[DistrictSkillMarket] = None
    training_supply: DistrictTrainingSupply
    curriculum: DistrictCurriculumBlock
    trainer: DistrictTrainerSignal
    gap: DistrictSkillGap
    priority: DistrictPrioritySignal


class DistrictInstitutionOut(BaseModel):
    id: str
    name: Optional[str] = None
    institution_type: Optional[str] = None


class DistrictCapacitySignal(BaseModel):
    current_course_count: int = 0
    current_cohort_count: int = 0
    current_learner_count: int = 0
    trainer_count: int = 0
    capacity_evidence_status: str = "insufficient_data"
    seat_note: str = ""


class DistrictTrainingResponse(BaseModel):
    district: str
    district_status: str
    state: Optional[str] = None
    country: Optional[str] = None
    role: str
    canonical_role: Optional[str] = None
    role_mapping_status: str
    market_context: Optional[DistrictMarketContext] = None
    institutions: List[DistrictInstitutionOut] = Field(default_factory=list)
    skills: List[DistrictSkillIntelligence] = Field(default_factory=list)
    suppressed: bool = False
    summary: dict
    capacity: DistrictCapacitySignal
    unmapped_excluded: dict
    provenance: dict
    note: str = ""


class DistrictTrainingGap(BaseModel):
    skill: str
    display_name: Optional[str] = None
    market: Optional[DistrictSkillMarket] = None
    training_supply: DistrictTrainingSupply
    gap: DistrictSkillGap
    priority: DistrictPrioritySignal
