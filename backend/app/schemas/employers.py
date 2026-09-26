from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
from uuid import UUID


class EmployerCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=200)
    description: Optional[str] = None
    industry: Optional[str] = Field(None, max_length=150)
    website: Optional[str] = Field(None, max_length=300)
    location: Optional[str] = Field(None, max_length=200)
    contact_email: Optional[str] = Field(None, max_length=200)


class EmployerUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=200)
    description: Optional[str] = None
    industry: Optional[str] = Field(None, max_length=150)
    website: Optional[str] = Field(None, max_length=300)
    location: Optional[str] = Field(None, max_length=200)
    contact_email: Optional[str] = Field(None, max_length=200)
    status: Optional[str] = Field(None, pattern="^(active|suspended|archived)$")


class EmployerOut(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    industry: Optional[str] = None
    website: Optional[str] = None
    location: Optional[str] = None
    contact_email: Optional[str] = None
    status: str
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class MemberOut(BaseModel):
    id: UUID
    employer_id: UUID
    user_id: str
    role: str
    created_at: datetime

    class Config:
        from_attributes = True


class MemberAdd(BaseModel):
    user_id: str = Field(..., min_length=1)
    role: str = Field("member", pattern="^(owner|member)$")


class RequirementCreate(BaseModel):
    title: str = Field(..., min_length=2, max_length=200)
    role_key: Optional[str] = Field(None, max_length=150)
    location: Optional[str] = Field(None, max_length=200)
    employment_type: Optional[str] = Field(
        None, pattern="^(full_time|part_time|internship|contract|apprenticeship)$"
    )
    description: Optional[str] = None
    experience_min_years: Optional[float] = Field(None, ge=0)
    qualification_text: Optional[str] = None


class RequirementUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=2, max_length=200)
    role_key: Optional[str] = Field(None, max_length=150)
    location: Optional[str] = Field(None, max_length=200)
    employment_type: Optional[str] = Field(
        None, pattern="^(full_time|part_time|internship|contract|apprenticeship)$"
    )
    description: Optional[str] = None
    experience_min_years: Optional[float] = Field(None, ge=0)
    qualification_text: Optional[str] = None
    status: Optional[str] = Field(None, pattern="^(draft|open|paused|closed)$")


class RequirementOut(BaseModel):
    id: UUID
    employer_id: UUID
    title: str
    role_key: Optional[str] = None
    location: Optional[str] = None
    employment_type: Optional[str] = None
    description: Optional[str] = None
    experience_min_years: Optional[float] = None
    qualification_text: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RequirementSkillIn(BaseModel):
    skill_id: UUID
    importance: str = Field(..., pattern="^(required|preferred)$")
    required_level: Optional[float] = Field(None, ge=0, le=1)
    note: Optional[str] = None


class RequirementSkillOut(BaseModel):
    id: UUID
    hiring_requirement_id: UUID
    skill_id: UUID
    importance: str
    required_level: Optional[float] = None
    note: Optional[str] = None
    created_at: datetime
    skill_name: Optional[str] = None
    skill_category: Optional[str] = None

    class Config:
        from_attributes = True


class RequirementSkillsBulk(BaseModel):
    skills: List[RequirementSkillIn] = Field(..., min_length=0, max_length=50)


class CanonicalSkillOut(BaseModel):
    id: UUID
    canonical_name: str
    display_name: str
    category: Optional[str] = None

    class Config:
        from_attributes = True

