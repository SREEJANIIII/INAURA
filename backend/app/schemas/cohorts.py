from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, date
from uuid import UUID


class CohortCreate(BaseModel):
    institution_id: UUID
    course_id: UUID
    name: str = Field(..., min_length=2, max_length=200)
    code: Optional[str] = Field(None, max_length=60)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    academic_year: Optional[str] = Field(None, max_length=20)


class CohortUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=200)
    code: Optional[str] = Field(None, max_length=60)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    academic_year: Optional[str] = Field(None, max_length=20)
    status: Optional[str] = Field(None, pattern="^(draft|active|completed|archived)$")


class CohortResponse(BaseModel):
    id: UUID
    institution_id: UUID
    course_id: UUID
    name: str
    code: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    academic_year: Optional[str] = None
    status: str
    data_origin: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CohortMemberCreate(BaseModel):
    user_id: str = Field(..., min_length=1, description="Canonical student id (auth.users.id)")


class CohortMemberUpdate(BaseModel):
    enrollment_status: str = Field(..., pattern="^(active|completed|withdrawn)$")


class CohortMemberResponse(BaseModel):
    id: UUID
    cohort_id: UUID
    user_id: str
    enrollment_status: str
    joined_at: Optional[datetime] = None
    exited_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CohortSupplySkill(BaseModel):
    skill: str
    display_name: Optional[str] = None
    category: Optional[str] = None
    cohort_size: int
    assessed_member_count: int
    evidenced_member_count: int
    verified_member_count: int
    skill_coverage: float
    verified_coverage: float
    average_proficiency: Optional[float] = None
    median_proficiency: Optional[float] = None
    min_proficiency: Optional[float] = None
    max_proficiency: Optional[float] = None
    average_confidence: Optional[float] = None
    verification_rate: Optional[float] = None
    qualifying_signal_count: int
    average_evidence_count: Optional[float] = None
    source_distribution: dict
    tier_distribution: dict


class UnmappedConceptOut(BaseModel):
    skill_id: str
    member_count: int
    signal_count: int


class CohortSupplyProvenance(BaseModel):
    source: str
    supply_type: str
    member_signal_rows: int
    member_assessment_rows: int
    note: str


class CohortSkillSupplyResponse(BaseModel):
    cohort: dict
    course: dict
    institution: dict
    member_count: int
    membership_counts: dict
    min_members_for_detail: int
    suppressed: bool
    skills: List[CohortSupplySkill]
    unmapped_concepts: List[UnmappedConceptOut]
    provenance: CohortSupplyProvenance
    note: str


class CourseCohortSupplyResponse(BaseModel):
    course: dict
    cohorts: List[dict]
    member_count: int
    min_members_for_detail: int
    suppressed: bool
    skills: List[CohortSupplySkill]
    unmapped_concepts: List[UnmappedConceptOut]
    provenance: CohortSupplyProvenance
    note: str
