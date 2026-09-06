from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from datetime import datetime

RoadmapStatus = Literal["active", "completed", "archived"]
ItemStatus = Literal["not_started", "in_progress", "completed"]
ItemType = Literal["learn", "practice", "project", "assessment"]
ResourceType = Literal["course", "documentation", "tutorial", "article", "video", "practice", "project_reference"]
MilestoneStatus = Literal["not_started", "in_progress", "completed"]

class RoadmapGenerateRequest(BaseModel):
    target_role: Optional[str] = Field(None, min_length=2, max_length=100, description="Target role for roadmap, defaults to latest analysis role")

class RoadmapResourceResponse(BaseModel):
    id: str
    roadmap_item_id: str
    title: str
    resource_type: ResourceType
    url: str
    provider: Optional[str] = None
    difficulty: Optional[str] = None
    estimated_hours: Optional[float] = None
    is_free: bool
    description: str
    created_at: datetime

    class Config:
        from_attributes = True

class RoadmapItemResponse(BaseModel):
    id: str
    roadmap_id: str
    skill_id: str
    skill_gap_id: Optional[str] = None
    title: str
    description: str
    item_type: ItemType
    priority: int
    estimated_hours: float
    sequence_order: int
    status: ItemStatus
    completion_percentage: float
    why_it_matters: str
    created_at: datetime
    updated_at: datetime
    # joined
    skills: Optional[dict] = None
    roadmap_resources: Optional[List[RoadmapResourceResponse]] = None

    class Config:
        from_attributes = True

class RoadmapMilestoneResponse(BaseModel):
    id: str
    roadmap_id: str
    title: str
    description: str
    sequence_order: int
    target_hours: float
    status: MilestoneStatus
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class RoadmapResponse(BaseModel):
    id: str
    user_id: str
    analysis_result_id: str
    target_role: str
    title: str
    status: RoadmapStatus
    engine_version: str
    total_estimated_hours: float
    estimated_weeks: int
    progress: Optional[float] = None
    hours_per_week: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class RoadmapGenerateResponse(RoadmapResponse):
    items: Optional[List[RoadmapItemResponse]] = None
    milestones: Optional[List[RoadmapMilestoneResponse]] = None

class RoadmapItemUpdateRequest(BaseModel):
    status: Optional[ItemStatus] = Field(None, description="not_started|in_progress|completed")
    completion_percentage: Optional[float] = Field(None, ge=0, le=100, description="0-100")

    class Config:
        extra = "forbid"
