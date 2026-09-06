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
