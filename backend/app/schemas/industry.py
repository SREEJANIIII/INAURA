from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class IndustryRequirementResponse(BaseModel):
    id: str
    role: str
    skill: str
    skill_category: str
    importance: float
    demand: float
    interview_relevance: float
    source: str
    source_url: Optional[str]
    description: Optional[str]
    version: str
    metadata: Optional[dict]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RetrieveRequest(BaseModel):
    role: str = Field(..., min_length=2, max_length=100, description="Target role, e.g., AI/ML Engineer")
    query: Optional[str] = Field(None, max_length=400, description="Optional free-text query; defaults to role")
    top_k: int = Field(10, ge=1, le=30, description="Number of requirements to retrieve")


class RetrieveItem(BaseModel):
    id: str
    role: str
    skill: str
    skill_category: str
    importance: float
    demand: float
    interview_relevance: float
    source: str
    source_url: Optional[str]
    description: Optional[str]
    version: str
    similarity: float = Field(..., description="Retrieval relevance 0-1, not proficiency")


class RetrieveResponse(BaseModel):
    role: str
    query: str
    count: int
    items: List[RetrieveItem]
    note: str = Field(default="prototype industry knowledge — heuristic values, not scientifically validated")
