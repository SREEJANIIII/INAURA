from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime, date
from uuid import UUID


APP_STATUSES = ("saved", "applied", "screening", "interview", "offer_received", "selected", "rejected", "withdrawn")


class ApplicationCreate(BaseModel):
    hiring_requirement_id: UUID


class StatusTransitionIn(BaseModel):
    to_status: str = Field(
        ..., pattern="^(saved|applied|screening|interview|offer_received|selected|rejected|withdrawn)$"
    )
    note: Optional[str] = Field(None, max_length=1000)


class ApplicationEventOut(BaseModel):
    id: UUID
    application_id: UUID
    from_status: Optional[str] = None
    to_status: str
    actor: Optional[str] = None
    note: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ApplicationOut(BaseModel):
    id: UUID
    student_id: str
    hiring_requirement_id: UUID
    employer_id: Optional[UUID] = None
    status: str
    outcome: Optional[str] = None
    outcome_decided_at: Optional[datetime] = None
    applied_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ApplicationDetailOut(ApplicationOut):
    events: List[ApplicationEventOut] = []


class SkillFeedbackIn(BaseModel):
    skill_id: UUID
    expected_level: Optional[float] = Field(None, ge=0, le=1)
    observed_level: Optional[float] = Field(None, ge=0, le=1)
    comment: Optional[str] = Field(None, max_length=1000)


class EmployerFeedbackCreate(BaseModel):
    technical_ability: Optional[int] = Field(None, ge=1, le=5)
    communication: Optional[int] = Field(None, ge=1, le=5)
    problem_solving: Optional[int] = Field(None, ge=1, le=5)
    project_readiness: Optional[int] = Field(None, ge=1, le=5)
    role_readiness: Optional[int] = Field(None, ge=1, le=5)
    overall_rating: Optional[int] = Field(None, ge=1, le=5)
    interview_summary: Optional[str] = None
    overall_comment: Optional[str] = None
    skills: List[SkillFeedbackIn] = Field(default_factory=list, max_length=50)


class SkillFeedbackOut(BaseModel):
    id: UUID
    employer_feedback_id: UUID
    skill_id: UUID
    expected_level: Optional[float] = None
    observed_level: Optional[float] = None
    skill_gap: Optional[float] = None
    comment: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class EmployerFeedbackOut(BaseModel):
    id: UUID
    employer_id: UUID
    application_id: UUID
    student_id: str
    technical_ability: Optional[int] = None
    communication: Optional[int] = None
    problem_solving: Optional[int] = None
    project_readiness: Optional[int] = None
    role_readiness: Optional[int] = None
    overall_rating: Optional[int] = None
    interview_summary: Optional[str] = None
    overall_comment: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: datetime
    skills: List[SkillFeedbackOut] = []

    class Config:
        from_attributes = True


class PlacementCreate(BaseModel):
    employer_id: UUID
    application_id: Optional[UUID] = None
    role_title: str = Field(..., min_length=2, max_length=200)
    location: Optional[str] = Field(None, max_length=200)
    joining_date: Optional[date] = None
    status: str = Field(..., pattern="^(offer_accepted|selected|joined|declined|not_joined)$")


class PlacementUpdate(BaseModel):
    role_title: Optional[str] = Field(None, min_length=2, max_length=200)
    location: Optional[str] = Field(None, max_length=200)
    joining_date: Optional[date] = None
    status: Optional[str] = Field(None, pattern="^(offer_accepted|selected|joined|declined|not_joined)$")
    verification_status: Optional[str] = Field(None, pattern="^(unverified|verified|disputed)$")


class PlacementOut(BaseModel):
    id: UUID
    student_id: str
    employer_id: UUID
    application_id: Optional[UUID] = None
    role_title: str
    location: Optional[str] = None
    joining_date: Optional[date] = None
    status: str
    outcome_source: str
    verification_status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AlignmentCreate(BaseModel):
    hiring_requirement_id: UUID
    course_name: str = Field(..., min_length=2, max_length=200)
    qualification_name: Optional[str] = Field(None, max_length=200)
    skill_id: Optional[UUID] = None
    coverage: Optional[float] = Field(None, ge=0, le=1)
    evidence_note: Optional[str] = None
    evidence_id: Optional[UUID] = None
    certification_id: Optional[UUID] = None


class AlignmentOut(BaseModel):
    id: UUID
    hiring_requirement_id: UUID
    course_name: str
    qualification_name: Optional[str] = None
    skill_id: Optional[UUID] = None
    coverage: Optional[float] = None
    evidence_note: Optional[str] = None
    evidence_id: Optional[UUID] = None
    certification_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DashboardOut(BaseModel):
    funnel: dict
    rates: dict
    denominators: dict
    top_required_skills: List[dict] = []
    top_observed_gaps: List[dict] = []
    unlinked_placements_n: int = 0
    window: dict


class IndustryOutcomeSignal(BaseModel):
    signal_version: str = "industry-outcome-signal-v1"
    role: Optional[str] = None
    location: Optional[str] = None
    skill: Optional[str] = None
    time_window: dict
    denominators: dict
    application_count: int
    interview_count: int
    selection_count: int
    placement_count: int
    feedback_count: int
    observed_demand: Optional[float] = None
    observed_skill_gap: Optional[float] = None
    min_n_met: bool
