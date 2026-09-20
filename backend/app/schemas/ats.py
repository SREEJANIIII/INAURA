from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any


class AtsSkillMatch(BaseModel):
    skill: str
    category: str = "General"
    importance: float = 0.5
    matched: bool = False
    occurrences: int = 0
    role_relevance: Optional[str] = None


class AtsSectionDetail(BaseModel):
    name: str
    found: bool
    importance: str = "important"  # critical | important | optional
    description: str = ""


class AtsContactCheck(BaseModel):
    has_email: bool = False
    email: Optional[str] = None
    has_phone: bool = False
    phone: Optional[str] = None
    has_linkedin: bool = False
    linkedin_url: Optional[str] = None
    has_github: bool = False
    github_url: Optional[str] = None
    has_portfolio: bool = False
    portfolio_url: Optional[str] = None
    all_links: List[str] = Field(default_factory=list)


class AtsScores(BaseModel):
    overall: int = Field(..., ge=0, le=100)
    skills_match: int = Field(..., ge=0, le=100)
    impact_metrics: int = Field(..., ge=0, le=100)
    sections_structure: int = Field(..., ge=0, le=100)
    formatting_parseability: int = Field(..., ge=0, le=100)


class AtsRecommendation(BaseModel):
    title: str
    description: str
    category: str = "skills"  # skills | impact | format | sections
    priority: str = "high"  # high | medium | low


class AtsBulletRewrite(BaseModel):
    original: str
    improved: str
    explanation: str


class AtsTestResponse(BaseModel):
    filename: str
    target_role: str
    word_count: int
    char_count: int
    scores: AtsScores
    grade: str  # A+, A, B, C, D
    verdict: str
    summary: str
    matched_skills: List[AtsSkillMatch] = Field(default_factory=list)
    missing_skills: List[AtsSkillMatch] = Field(default_factory=list)
    extra_skills: List[str] = Field(default_factory=list)
    sections: List[AtsSectionDetail] = Field(default_factory=list)
    contact: AtsContactCheck = Field(default_factory=AtsContactCheck)
    action_verbs_found: List[str] = Field(default_factory=list)
    metrics_found: List[str] = Field(default_factory=list)
    recommendations: List[AtsRecommendation] = Field(default_factory=list)
    bullet_rewrites: List[AtsBulletRewrite] = Field(default_factory=list)
    parsed_text_preview: str = ""
    parse_status: str = "ok"
    parse_warning: Optional[str] = None


class AtsRoleOption(BaseModel):
    title: str
    slug: str
    category: str
    description: str
    benchmark_skills: List[str] = Field(default_factory=list)
