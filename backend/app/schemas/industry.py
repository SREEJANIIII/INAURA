from pydantic import BaseModel, Field
from typing import Optional, List, Any
from datetime import datetime


class IndustryRequirementResponse(BaseModel):
    id: str
    role: str
    skill: str
    skill_slug: Optional[str] = None
    skill_category: str
    required_level: float = Field(default=0.75, ge=0.0, le=1.0)
    importance: float = Field(..., ge=0.0, le=1.0)
    demand: float = Field(..., ge=0.0, le=1.0)
    interview_relevance: float = Field(..., ge=0.0, le=1.0)
    industry_confidence: float = Field(default=0.85, ge=0.0, le=1.0)
    source: str
    source_url: Optional[str] = None
    source_quality: float = Field(default=0.85, ge=0.0, le=1.0)
    evidence_context: Optional[str] = None
    description: Optional[str] = None
    version: str = "2026.1"
    metadata: Optional[dict] = None
    published_at: Optional[str] = None
    retrieved_at: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class RoleSummaryResponse(BaseModel):
    title: str
    slug: str
    category: str
    description: str
    aliases: List[str]
    source_benchmarks: List[str]


class SharedSkillItem(BaseModel):
    skill: str
    category: str
    required_level_a: float
    required_level_b: float
    importance_a: float
    importance_b: float
    level_delta: float
    importance_delta: float


class UniqueSkillItem(BaseModel):
    skill: str
    category: str
    required_level: float
    importance: float


class RoleComparisonResponse(BaseModel):
    role_a: str
    role_b: str
    overlap_score: float
    transition_effort: str
    shared_skill_count: int
    unique_to_a_count: int
    unique_to_b_count: int
    shared_skills: List[SharedSkillItem]
    unique_skills_a: List[UniqueSkillItem]
    unique_skills_b: List[UniqueSkillItem]
    transferable_skills: List[str]
    key_skills_to_acquire: List[str]
    transition_advice: str


class CustomRoleRequest(BaseModel):
    role: str = Field(..., min_length=2, max_length=100, description="Custom role title, e.g., AI Engineer")
    query: Optional[str] = Field(None, max_length=400, description="Optional focus query")


class CustomRoleResponse(BaseModel):
    status: str
    role: str
    is_custom: bool
    requirements: List[IndustryRequirementResponse]
    skills_count: int
    confidence: float
    source_summary: str
    note: str


class RetrieveRequest(BaseModel):
    role: str = Field(..., min_length=2, max_length=100, description="Target role, e.g., Software Engineer")
    query: Optional[str] = Field(None, max_length=400, description="Optional free-text query; defaults to role")
    top_k: int = Field(10, ge=1, le=30, description="Number of requirements to retrieve")


class RetrieveItem(BaseModel):
    id: str
    role: str
    skill: str
    skill_category: str
    required_level: float = 0.75
    importance: float
    demand: float
    interview_relevance: float
    industry_confidence: float = 0.85
    source: str
    source_url: Optional[str] = None
    source_quality: float = 0.85
    evidence_context: Optional[str] = None
    description: Optional[str] = None
    version: str = "2026.1"
    similarity: float = Field(..., description="Retrieval relevance 0-1, not proficiency")


class RetrieveResponse(BaseModel):
    role: str
    query: str
    count: int
    items: List[RetrieveItem]
    note: str = Field(default="INAURA Industry Knowledge Catalog — authentic benchmarks with source attribution")
