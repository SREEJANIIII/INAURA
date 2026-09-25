from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class ResumeCreate(BaseModel):
    target_role: str = Field(..., min_length=2, max_length=120)
    title: Optional[str] = Field(None, max_length=160)
    template: Literal["classic", "modern", "minimal"] = "classic"


class ResumeUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=2, max_length=160)
    target_role: Optional[str] = Field(None, min_length=2, max_length=120)
    template: Optional[Literal["classic", "modern", "minimal"]] = None
    content: Optional[Dict[str, Any]] = None


class ResumeResponse(BaseModel):
    id: str
    title: str
    target_role: str
    template: str
    content: Dict[str, Any]
    claims: List[Dict[str, Any]] = []
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

