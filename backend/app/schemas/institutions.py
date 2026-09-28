from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from uuid import UUID


class InstitutionCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=200)
    code: Optional[str] = Field(None, max_length=60)
    institution_type: str = Field(
        "other",
        pattern="^(iti|polytechnic|college|university|skill_training_centre|training_institute|other)$",
    )
    district: Optional[str] = Field(None, max_length=150)
    state: Optional[str] = Field(None, max_length=150)
    country: Optional[str] = Field(None, max_length=150)
    city: Optional[str] = Field(None, max_length=150)
    website: Optional[str] = Field(None, max_length=300)
    description: Optional[str] = None


class InstitutionUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=200)
    code: Optional[str] = Field(None, max_length=60)
    institution_type: Optional[str] = Field(
        None,
        pattern="^(iti|polytechnic|college|university|skill_training_centre|training_institute|other)$",
    )
    district: Optional[str] = Field(None, max_length=150)
    state: Optional[str] = Field(None, max_length=150)
    country: Optional[str] = Field(None, max_length=150)
    city: Optional[str] = Field(None, max_length=150)
    website: Optional[str] = Field(None, max_length=300)
    description: Optional[str] = None
    status: Optional[str] = Field(None, pattern="^(active|suspended|archived)$")


class InstitutionResponse(BaseModel):
    id: UUID
    name: str
    code: Optional[str] = None
    institution_type: str
    district: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    website: Optional[str] = None
    description: Optional[str] = None
    status: str
    data_origin: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CourseCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=200)
    code: Optional[str] = Field(None, max_length=60)
    description: Optional[str] = None
    level: Optional[str] = Field(None, max_length=50)
    duration_text: Optional[str] = Field(None, max_length=60)
    delivery_mode: Optional[str] = Field(None, pattern="^(online|offline|hybrid)$")


class CourseUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=200)
    code: Optional[str] = Field(None, max_length=60)
    description: Optional[str] = None
    level: Optional[str] = Field(None, max_length=50)
    duration_text: Optional[str] = Field(None, max_length=60)
    delivery_mode: Optional[str] = Field(None, pattern="^(online|offline|hybrid)$")
    status: Optional[str] = Field(None, pattern="^(draft|active|archived)$")


class CourseResponse(BaseModel):
    id: UUID
    institution_id: UUID
    name: str
    code: Optional[str] = None
    description: Optional[str] = None
    level: Optional[str] = None
    duration_text: Optional[str] = None
    delivery_mode: Optional[str] = None
    status: str
    data_origin: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CourseModuleCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=200)
    code: Optional[str] = Field(None, max_length=60)
    description: Optional[str] = None
    sequence: int = Field(0, ge=0)
    hours: Optional[float] = Field(None, ge=0)


class CourseModuleUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=200)
    code: Optional[str] = Field(None, max_length=60)
    description: Optional[str] = None
    sequence: Optional[int] = Field(None, ge=0)
    hours: Optional[float] = Field(None, ge=0)
    status: Optional[str] = Field(None, pattern="^(draft|active|archived)$")


class CourseModuleResponse(BaseModel):
    id: UUID
    course_id: UUID
    name: str
    code: Optional[str] = None
    description: Optional[str] = None
    sequence: int
    hours: Optional[float] = None
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CourseSkillCreate(BaseModel):
    # Raw curriculum phrase; resolved server-side through the canonical
    # taxonomy. Callers never supply skill_id (single mapping system).
    source_concept: str = Field(..., min_length=1, max_length=200)
    module_id: Optional[UUID] = Field(None, description="Omit for course-level skills")
    coverage: Optional[str] = Field(None, pattern="^(introductory|intermediate|advanced)$")
    importance: Optional[str] = Field(None, pattern="^(required|preferred)$")
    evidence_source: Optional[str] = Field(None, max_length=300)


class CourseSkillResponse(BaseModel):
    id: UUID
    course_id: UUID
    module_id: Optional[UUID] = None
    skill_id: Optional[UUID] = None
    canonical_skill_slug: Optional[str] = None
    source_concept: str
    mapping_status: str
    mapping_rationale: Optional[str] = None
    coverage: Optional[str] = None
    importance: Optional[str] = None
    evidence_source: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TrainerCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=200)
    email: Optional[str] = Field(None, max_length=200)
    designation: Optional[str] = Field(None, max_length=150)


class TrainerResponse(BaseModel):
    id: UUID
    institution_id: UUID
    name: str
    email: Optional[str] = None
    designation: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TrainerSkillCreate(BaseModel):
    # Raw phrase; must resolve to a canonical taxonomy skill (400 otherwise).
    source_concept: str = Field(..., min_length=1, max_length=200)
    proficiency: Optional[str] = Field(None, pattern="^(introductory|intermediate|advanced)$")
    source: Optional[str] = Field(None, max_length=200)


class TrainerSkillResponse(BaseModel):
    id: UUID
    trainer_id: UUID
    skill_id: Optional[UUID] = None
    canonical_skill_slug: str
    proficiency: Optional[str] = None
    source: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CourseCoverageSkill(BaseModel):
    id: UUID
    module_id: Optional[UUID] = None
    source_concept: str
    canonical_skill_slug: Optional[str] = None
    mapping_status: str
    coverage: Optional[str] = None
    importance: Optional[str] = None


class CourseCoverageModule(BaseModel):
    module_id: UUID
    module_name: Optional[str] = None
    sequence: Optional[int] = None
    skills: List[CourseCoverageSkill]


class CourseCoverageResponse(BaseModel):
    course: CourseResponse
    modules: List[CourseCoverageModule]
    course_level_skills: List[CourseCoverageSkill]
    counts: dict
