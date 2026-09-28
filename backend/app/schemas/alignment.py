from pydantic import BaseModel, Field
from typing import Optional, List


class AlignmentIndustryBlock(BaseModel):
    required: bool = True
    posting_count: Optional[int] = None
    skill_posting_count: Optional[int] = None
    distinct_company_count: Optional[int] = None
    skill_share: Optional[float] = None
    demand: Optional[float] = None
    required_level: Optional[float] = None
    importance: Optional[float] = None
    trend: Optional[str] = None
    confidence: Optional[float] = None
    evidence_suppressed: Optional[bool] = None
    location: Optional[dict] = None
    period: Optional[dict] = None
    provider_id: Optional[str] = None
    data_origin: Optional[str] = None
    source_version: Optional[str] = None
    evidence_context: Optional[str] = None


class AlignmentCurriculumBlock(BaseModel):
    taught: bool = True
    coverage: Optional[str] = None
    importance: Optional[str] = None
    modules: List[str] = Field(default_factory=list)
    mapping_status: Optional[str] = None
    source_concept: Optional[str] = None
    data_origin: Optional[str] = None


class AlignmentCohortBlock(BaseModel):
    member_count: Optional[int] = None
    assessed_member_count: Optional[int] = None
    evidenced_member_count: Optional[int] = None
    verified_member_count: Optional[int] = None
    skill_coverage: Optional[float] = None
    verified_coverage: Optional[float] = None
    average_proficiency: Optional[float] = None
    median_proficiency: Optional[float] = None
    average_confidence: Optional[float] = None
    verification_rate: Optional[float] = None
    qualifying_signal_count: Optional[int] = None


class AlignmentStatuses(BaseModel):
    curriculum_status: str
    attainment_status: str
    demand_status: str
    overall_status: str
    priority: str
    priority_reasons: List[str] = Field(default_factory=list)


class AlignmentSkillRow(BaseModel):
    skill: str
    display_name: Optional[str] = None
    category: Optional[str] = None
    industry: Optional[AlignmentIndustryBlock] = None
    curriculum: Optional[AlignmentCurriculumBlock] = None
    cohort: Optional[AlignmentCohortBlock] = None
    alignment: AlignmentStatuses


class CourseAlignmentResponse(BaseModel):
    role: str
    canonical_role: Optional[str] = None
    role_mapping_status: str
    course: dict
    institution: dict
    market_context: Optional[dict] = None
    cohort_context: Optional[dict] = None
    skills: List[AlignmentSkillRow]
    summary: dict
    extra_cohort_skills: List[str] = Field(default_factory=list)
    unmapped_excluded: dict
    provenance: dict
    note: str = ""
