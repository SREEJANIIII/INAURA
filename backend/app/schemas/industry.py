from pydantic import BaseModel, Field
from typing import Optional, List, Any
from datetime import datetime

from .industry_outcomes import OutcomeOverlay


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
    source_version: Optional[str] = None
    source_occupation: Optional[str] = None
    source_reference: Optional[str] = None
    mapping_version: Optional[str] = None
    role_relevance: Optional[str] = None
    source_concept: Optional[str] = None
    canonical_mapping: Optional[str] = None
    mapping_rationale: Optional[str] = None
    source_quality: float = Field(default=0.85, ge=0.0, le=1.0)
    evidence_context: Optional[str] = None
    description: Optional[str] = None
    version: str = "2026.1"
    metadata: Optional[dict] = None
    published_at: Optional[str] = None
    retrieved_at: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # Phase 7: requirement trustworthiness (all optional for compatibility
    # with rows persisted before these fields existed).
    evidence_strength: Optional[str] = Field(
        default=None,
        description="Trust tier: strong, moderate, weak, or insufficient",
    )
    supporting_chunks: Optional[List[dict]] = Field(
        default=None,
        description="References (chunk id, role, topic, source, url) to benchmark chunks mentioning this skill",
    )
    duplicate_sources_collapsed: Optional[int] = Field(
        default=None,
        description="Same-source duplicate rows collapsed during aggregation",
    )
    # Phase 3: contextual employer-outcome annotation. Absent unless the
    # outcome overlay is enabled and the cell meets its threshold. Never a
    # gap-mathematics input.
    outcome_overlay: Optional[OutcomeOverlay] = Field(
        default=None,
        description="Observed employer-demand context for this curated requirement",
    )
    # Dynamic Industry Intelligence (additive, all optional for compatibility).
    location: Optional[dict] = Field(
        default=None,
        description="Location scope {scope, country, region, city, label, is_global}; None means global/default",
    )
    trend: Optional[str] = Field(
        default=None,
        description="Skill trend: stable, rising, emerging, declining, insufficient_data",
    )
    freshness: Optional[str] = Field(
        default=None,
        description="Freshness state: current, aging, stale, unknown",
    )
    data_origin: Optional[str] = Field(
        default=None,
        description="Provenance tier: source_data, inaura_derived, demo_seeded",
    )
    data_origins: Optional[List[str]] = Field(default=None)
    collected_at: Optional[str] = Field(default=None)
    last_updated: Optional[str] = Field(default=None)
    location_match: Optional[str] = Field(
        default=None,
        description="How the row relates to the requested location: global, exact, fallback_global",
    )
    mapping_status: Optional[str] = Field(
        default=None,
        description="Canonical mapping state: mapped or unmapped (unmapped preserves source concept)",
    )

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
    location: Optional[str] = Field(None, max_length=120, description="Optional location label, e.g., Bengaluru; omit for global")


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
    source_version: Optional[str] = None
    source_occupation: Optional[str] = None
    source_reference: Optional[str] = None
    mapping_version: Optional[str] = None
    role_relevance: Optional[str] = None
    source_concept: Optional[str] = None
    canonical_mapping: Optional[str] = None
    mapping_rationale: Optional[str] = None
    source_quality: float = 0.85
    evidence_context: Optional[str] = None
    description: Optional[str] = None
    version: str = "2026.1"
    similarity: float = Field(..., description="Retrieval relevance 0-1, not proficiency")
    evidence_strength: Optional[str] = Field(
        default=None,
        description="Trust tier: strong, moderate, weak, or insufficient",
    )
    supporting_chunks: Optional[List[dict]] = Field(
        default=None,
        description="References (chunk id, role, topic, source, url) to benchmark chunks mentioning this skill",
    )
    # Phase 3: contextual employer-outcome annotation (see IndustryRequirementResponse).
    outcome_overlay: Optional[OutcomeOverlay] = Field(
        default=None,
        description="Observed employer-demand context for this curated requirement",
    )
    trend: Optional[str] = Field(default=None)
    freshness: Optional[str] = Field(default=None)
    data_origin: Optional[str] = Field(default=None)
    location: Optional[dict] = Field(default=None)
    collected_at: Optional[str] = Field(default=None)
    last_updated: Optional[str] = Field(default=None)


class RetrieveResponse(BaseModel):
    role: str
    query: str
    count: int
    items: List[RetrieveItem]
    note: str = Field(default="INAURA Industry Knowledge Catalog — authentic benchmarks with source attribution")


class IndustryIntelligenceSkill(BaseModel):
    id: Optional[str] = None
    role: str
    skill: str
    skill_slug: Optional[str] = None
    skill_category: Optional[str] = "General"
    required_level: float = 0.75
    importance: float = 0.5
    demand: float = 0.5
    interview_relevance: float = 0.5
    industry_confidence: float = 0.85
    trend: Optional[str] = None
    freshness: Optional[str] = None
    source: str = ""
    source_url: Optional[str] = None
    evidence_context: Optional[str] = None
    data_origin: Optional[str] = None
    data_origins: Optional[List[str]] = None
    location: Optional[dict] = None
    location_match: Optional[str] = None
    mapping_status: Optional[str] = None
    source_concept: Optional[str] = None
    canonical_mapping: Optional[str] = None
    collected_at: Optional[str] = None
    last_updated: Optional[str] = None
    published_at: Optional[str] = None
    retrieved_at: Optional[str] = None


class IndustryIntelligenceResponse(BaseModel):
    role: str
    location: dict
    location_match: str = "global"
    last_updated: Optional[str] = None
    skills: List[IndustryIntelligenceSkill]
    counts: Optional[dict] = None
    data_origins: Optional[List[str]] = None
    note: str = ""


class DemandProviderInfo(BaseModel):
    provider_id: str
    display_name: str
    data_origin: str
    is_live: bool
    description: str
