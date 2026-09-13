from pydantic import BaseModel, Field
from typing import List, Optional


class CapabilityEvidence(BaseModel):
    provider: str = ""
    repository: str = ""
    files: List[str] = Field(default_factory=list)
    depth: int = 0
    reason: str = ""


class IndustryExpectation(BaseModel):
    capability_id: str = ""
    title: str = ""
    detail: str = ""
    relevance: List[str] = Field(default_factory=list)


class CapabilityItem(BaseModel):
    id: str = ""
    title: str = ""
    summary: str = ""
    observable_abilities: List[str] = Field(default_factory=list)
    related_skills: List[str] = Field(default_factory=list)
    support: float = 0.0
    evidence: List[CapabilityEvidence] = Field(default_factory=list)


class DemonstratedCapability(BaseModel):
    id: str = ""
    title: str = ""
    support: float = 0.0
    confidence: float = 0.0
    evidence: List[CapabilityEvidence] = Field(default_factory=list)


class MissingCapability(BaseModel):
    id: str = ""
    title: str = ""
    support: float = 0.0
    status: str = ""
    priority: float = 0.0
    priority_category: str = "covered"
    next_actions: List[str] = Field(default_factory=list)
    resources: List[dict] = Field(default_factory=list)
    evidence: List[CapabilityEvidence] = Field(default_factory=list)


class RequirementProvenance(BaseModel):
    source: str = ""
    source_url: Optional[str] = None
    source_quality: Optional[float] = None
    evidence_strength: str = ""
    required_level: float = 0.0
    importance: float = 0.0
    role_relevance: str = ""
    evidence_context: str = ""
    supporting_chunks: List[dict] = Field(default_factory=list)


class SkillCapability(BaseModel):
    skill: str
    slug: str = ""
    role: str = ""
    proficiency: float = 0.0
    confidence: float = 0.0
    required_level: float = 0.0
    importance: float = 0.0
    status: str = ""
    priority: float = 0.0
    priority_category: str = "covered"
    industry_expectations: List[IndustryExpectation] = Field(default_factory=list)
    capabilities: List[CapabilityItem] = Field(default_factory=list)
    demonstrated_capabilities: List[DemonstratedCapability] = Field(default_factory=list)
    missing_capabilities: List[MissingCapability] = Field(default_factory=list)
    evidence_gap: List[str] = Field(default_factory=list)
    skill_gap: List[str] = Field(default_factory=list)
    evidence_sources: List[CapabilityEvidence] = Field(default_factory=list)
    requirement: RequirementProvenance = Field(default_factory=RequirementProvenance)
    explanation: str = ""


class CapabilityMapResponse(BaseModel):
    role: str
    generated_at: str = ""
    capability_model_version: str = ""
    engine_version: str = ""
    skills: List[SkillCapability] = Field(default_factory=list)
    summary: dict = Field(default_factory=dict)
