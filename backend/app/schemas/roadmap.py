from pydantic import BaseModel, Field
from typing import Optional, List, Literal, Dict, Any
from datetime import datetime

RoadmapStatus = Literal["active", "completed", "archived"]
ItemStatus = Literal["not_started", "in_progress", "completed"]
ItemType = Literal["learn", "practice", "project", "assessment"]
ResourceType = Literal["course", "documentation", "tutorial", "article", "video", "practice", "project_reference"]
MilestoneStatus = Literal["not_started", "in_progress", "completed"]

TaskType = Literal["learn", "practice", "build", "validate"]
TaskStatus = Literal["not_started", "in_progress", "completed", "skipped"]
WeekStatus = Literal["locked", "current", "completed", "behind_schedule"]


class RoadmapGenerateRequest(BaseModel):
    target_role: Optional[str] = Field(None, min_length=2, max_length=100, description="Target role for roadmap, defaults to latest analysis role")
    hours_per_week: Optional[int] = Field(None, ge=1, le=80, description="Optional override for weekly hours capacity")


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
    personalization_explanation: Optional[dict] = None
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


# --- Weekly Adaptive Tasks & Weeks Schemas ---

class RoadmapTaskResponse(BaseModel):
    id: str
    roadmap_week_id: str
    skill_slug: str
    skill_name: str
    task_type: TaskType
    title: str
    description: str
    estimated_minutes: int
    sequence_order: int
    status: TaskStatus
    completion_percentage: float = 0.0
    resources: List[dict] = Field(default_factory=list)
    validation_method: str = "self_check"
    evidence_generated: Optional[dict] = None
    why_this_task: str = ""
    personalization_context: Optional[dict] = None
    completed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class RoadmapWeekResponse(BaseModel):
    id: str
    roadmap_id: str
    week_number: int
    title: str
    objective: str
    estimated_hours: float
    skills: List[str] = Field(default_factory=list)
    status: WeekStatus = "locked"
    completion_percentage: float = 0.0
    tasks: Optional[List[RoadmapTaskResponse]] = None
    start_date: Optional[str] = None
    target_completion_date: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

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
    evidence_snapshot_id: Optional[str] = None
    weekly_hours_budget: Optional[int] = None
    total_weeks: Optional[int] = None
    current_week_index: Optional[int] = None
    skill_explanations: Optional[List[dict]] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RoadmapGenerateResponse(RoadmapResponse):
    items: Optional[List[RoadmapItemResponse]] = None
    milestones: Optional[List[RoadmapMilestoneResponse]] = None
    weeks: Optional[List[RoadmapWeekResponse]] = None


class RoadmapItemUpdateRequest(BaseModel):
    status: Optional[ItemStatus] = Field(None, description="not_started|in_progress|completed")
    completion_percentage: Optional[float] = Field(None, ge=0, le=100, description="0-100")

    class Config:
        extra = "forbid"


class RoadmapTaskUpdateRequest(BaseModel):
    status: Optional[TaskStatus] = Field(None, description="not_started|in_progress|completed|skipped")
    completion_percentage: Optional[float] = Field(None, ge=0, le=100)
    submission_url: Optional[str] = Field(None, description="Repository or project URL verifying the task")
    submission_notes: Optional[str] = Field(None, description="Notes on how the task was completed")
    quiz_score: Optional[float] = Field(None, ge=0, le=100, description="Score on validation quiz/test")


class RoadmapReassessRequest(BaseModel):
    target_role: Optional[str] = Field(None, description="Optional target role for reassessment")
    adjust_hours_per_week: Optional[int] = Field(None, ge=1, le=80)
    mode: Optional[Literal["compress", "extend_timeline"]] = "compress"


class LearnerSkillStateResponse(BaseModel):
    skill_slug: str
    skill_name: str
    state_classification: Literal["KNOWN", "INFERRED", "UNKNOWN"]
    proficiency: float
    confidence: float
    required_level: float
    gap: float
    evidence_coverage: float
    evidence_strength: float
    evidence_count: int
    evidence_depth: int
    active_sources: List[str]
    reasoning: str
    last_evaluated_at: str


class EvidenceSnapshotResponse(BaseModel):
    id: str
    user_id: str
    analysis_result_id: Optional[str] = None
    sources_analyzed: List[dict]
    sources_available: List[str]
    sources_unavailable: List[str]
    learner_skill_states: Dict[str, Any]
    engine_version: str
    created_at: datetime
