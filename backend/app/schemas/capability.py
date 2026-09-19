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


class CapabilityMatchedSignal(BaseModel):
    signal: str = ""
    statement: str = ""
    source_type: str = ""
    support: float = 0.0
    files: List[str] = Field(default_factory=list)


class CapabilityMissingSignal(BaseModel):
    signal: str = ""
    statement: str = ""


class CapabilityExplanation(BaseModel):
    summary: str = ""
    status_reason: str = ""
    evidence_strength: str = ""
    matched_signals: List[CapabilityMatchedSignal] = Field(default_factory=list)
    missing_signals: List[CapabilityMissingSignal] = Field(default_factory=list)


class CapabilityItem(BaseModel):
    id: str = ""
    title: str = ""
    summary: str = ""
    observable_abilities: List[str] = Field(default_factory=list)
    related_skills: List[str] = Field(default_factory=list)
    support: float = 0.0
    evidence: List[CapabilityEvidence] = Field(default_factory=list)
    # Interpretation layer (deterministic; support/evidence unchanged).
    status: str = ""
    knowledge_statement: str = ""
    # Phase 2: why this status was assigned (read-only explanation).
    capability_explanation: CapabilityExplanation = Field(
        default_factory=CapabilityExplanation
    )


class WhatInauraKnowsArea(BaseModel):
    capability_id: str = ""
    capability_title: str = ""
    statement: str = ""
    support: float = 0.0
    status: str = ""


class WhatInauraKnowsEvidenceSummary(BaseModel):
    evidence_count: int = 0
    source_types: List[str] = Field(default_factory=list)
    implementation_evidence_count: int = 0


class WhatInauraKnows(BaseModel):
    summary: str = ""
    demonstrated_areas: List[WhatInauraKnowsArea] = Field(default_factory=list)
    developing_areas: List[WhatInauraKnowsArea] = Field(default_factory=list)
    unverified_areas: List[WhatInauraKnowsArea] = Field(default_factory=list)
    evidence_summary: WhatInauraKnowsEvidenceSummary = Field(
        default_factory=WhatInauraKnowsEvidenceSummary
    )


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
    category: str = ""
    prerequisites: List[str] = Field(default_factory=list)
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
    what_inaura_knows: WhatInauraKnows = Field(default_factory=WhatInauraKnows)


class CapabilityMapResponse(BaseModel):
    role: str
    generated_at: str = ""
    capability_model_version: str = ""
    engine_version: str = ""
    skills: List[SkillCapability] = Field(default_factory=list)
    summary: dict = Field(default_factory=dict)
