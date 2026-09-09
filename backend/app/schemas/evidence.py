from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Literal, Any, Dict
from datetime import datetime
import re

EvidenceType = Literal[
    "github",
    "leetcode",
    "codeforces",
    "kaggle",
    "linkedin",
    "resume",
    "syllabus",
    "certification_file",
    "project_doc",
    "project",
    "certification",
    "manual",
]

VerificationStatus = Literal["unverified", "verified", "failed"]

URL_TYPES = {"github", "leetcode", "codeforces", "kaggle", "linkedin"}
FILE_TYPES = {"resume", "syllabus", "certification_file", "project_doc"}


def _is_url_or_username(v: str | None) -> str | None:
    if v is None or v == "":
        return None
    v = v.strip()
    # Allow full URL or username (no spaces, reasonable length)
    if " " in v:
        raise ValueError("URL/username must not contain spaces")
    if len(v) < 2 or len(v) > 400:
        raise ValueError("URL/username length must be 2-400")
    # If it looks like URL, basic check
    if v.startswith("http://") or v.startswith("https://"):
        if not re.match(r"^https?://[^\s/$.?#].[^\s]*$", v):
            raise ValueError("Invalid URL format")
    else:
        # username mode — allow alphanumeric, -, _, ., /
        if not re.match(r"^[A-Za-z0-9._\-/]+$", v):
            raise ValueError("Username contains invalid characters")
    return v


class EvidenceCreate(BaseModel):
    evidence_type: str
    source_url: Optional[str] = Field(None, description="URL or username for profile sources")
    file_path: Optional[str] = Field(None, description="Storage path for file evidence (set after upload)")
    title: Optional[str] = Field(None, max_length=200)
    metadata: Optional[dict] = Field(default=None)

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, v):
        return _is_url_or_username(v)


class EvidenceUpdate(BaseModel):
    source_url: Optional[str] = None
    file_path: Optional[str] = None
    title: Optional[str] = Field(None, max_length=200)
    metadata: Optional[dict] = None
    verification_status: Optional[VerificationStatus] = None
    verification_message: Optional[str] = None
    verified_at: Optional[datetime] = None
    provider: Optional[str] = None

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, v):
        return _is_url_or_username(v)


class EvidenceResponse(BaseModel):
    id: str
    user_id: str
    evidence_type: str
    source_url: Optional[str] = None
    file_path: Optional[str] = None
    title: Optional[str] = None
    metadata: Optional[dict] = None
    verification_status: VerificationStatus = "unverified"
    verification_message: Optional[str] = None
    verified_at: Optional[datetime] = None
    provider: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class EvidenceVerificationResponse(BaseModel):
    evidence_id: str
    verification_status: VerificationStatus
    verification_message: str
    verified_at: Optional[datetime] = None
    provider: str
    detected_skills: List[str] = Field(default_factory=list)
    metadata: Optional[dict] = None


# Projects
class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    description: str = Field(..., min_length=10, max_length=800)
    technologies: List[str] = Field(..., min_length=1, max_length=15)
    student_contribution: Optional[str] = Field(None, max_length=800, description="Specific personal contributions, features built, or modules owned")
    project_url: Optional[str] = Field(None, max_length=400)
    github_url: Optional[str] = Field(None, max_length=400)

    @field_validator("project_url", "github_url")
    @classmethod
    def validate_url(cls, v):
        if v is None or v == "":
            return None
        v = v.strip()
        if v and not v.startswith("http"):
            raise ValueError("URL must start with http:// or https://")
        return v


class ProjectResponse(BaseModel):
    id: str
    user_id: str
    name: str
    description: str
    technologies: List[str]
    student_contribution: Optional[str] = None
    project_url: Optional[str]
    github_url: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Certifications
class CertCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=150)
    issuing_org: str = Field(..., min_length=2, max_length=120)
    completion_year: int = Field(..., ge=2000, le=2035)
    certificate_url: Optional[str] = Field(None, max_length=400)

    @field_validator("certificate_url")
    @classmethod
    def validate_url(cls, v):
        if v is None or v == "":
            return None
        v = v.strip()
        if v and not v.startswith("http"):
            raise ValueError("URL must start with http:// or https://")
        return v


class CertResponse(BaseModel):
    id: str
    user_id: str
    name: str
    issuing_org: str
    completion_year: int
    certificate_url: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class EvidenceSummary(BaseModel):
    total_sources: int = 9
    provided: int
    items: List[EvidenceResponse]
    projects: List[ProjectResponse]
    certifications: List[CertResponse]
