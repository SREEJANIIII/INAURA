from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime

AnalysisStatus = Literal["not_started", "ready", "processing", "completed", "failed"]


class AnalysisStateResponse(BaseModel):
    user_id: str
    target_role: Optional[str]
    status: AnalysisStatus
    last_retrieval: Optional[dict]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SetTargetRoleRequest(BaseModel):
    target_role: str = Field(..., min_length=2, max_length=100, description="Primary career goal, e.g., AI/ML Engineer or Other")


class PrepareAnalysisRequest(BaseModel):
    target_role: Optional[str] = Field(None, description="Override stored target_role for this preparation")


class PrepareAnalysisResponse(BaseModel):
    status: AnalysisStatus
    target_role: str
    message: str
    retrieval: Optional[dict] = None


class TopicGapResponse(BaseModel):
    pillar: str
    skill: str = "Data Structures & Algorithms"
    status: str
    solved: int
    gap_type: str = "coverage_gap"
    priority_category: str
    importance: float
    explanation: str
    actionable_advice: str


class StrengthResponse(BaseModel):
    skill: str
    display_name: str
    category: str
    proficiency: float
    confidence: float
    required_level: float
    evidence_count: int
    explanation: str
    quadrant: str
    quadrant_title: str


class SkillGapResponse(BaseModel):
    canonical_name: str
    skill: str
    target_role: str
    required_level: float
    current_proficiency: float
    confidence: float
    gap: float
    importance: float
    demand: float
    interview_relevance: float
    industry_confidence: float = 0.85
    priority: float
    priority_score: float
    priority_category: str
    gap_type: str
    actionable_advice: str
    evidence_context: Optional[str] = None
    source: Optional[str] = None
    quadrant: Optional[str] = None
    quadrant_title: Optional[str] = None
    explanation: str
    skills: Optional[dict] = None

