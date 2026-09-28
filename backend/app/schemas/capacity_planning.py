from pydantic import BaseModel, Field
from typing import Optional, List


class CapacityPlanningRow(BaseModel):
    skill: str
    display_name: Optional[str] = None
    priority: str
    status: str
    district: str
    courses_teaching: int = 0
    courses_missing: int = 0
    institutions_teaching: int = 0
    institutions_total: int = 0
    learner_count: int = 0
    evidenced_learner_count: int = 0
    verified_learner_count: int = 0
    trainers_observed: int = 0
    market_trend: Optional[str] = None
    market_share: Optional[float] = None
    match_type: Optional[str] = None
    capacity_status: str = Field(pattern="^(CAPACITY_DATA_AVAILABLE|CAPACITY_DATA_INSUFFICIENT)$")
    planning_note: str = ""


class CapacityPlanningResponse(BaseModel):
    district: str
    district_status: str
    role: str
    canonical_role: Optional[str] = None
    role_mapping_status: str
    course_id: Optional[str] = None
    market_context: Optional[dict] = None
    capacity: List[CapacityPlanningRow]
    summary: dict
    capacity_evidence_status: str
    planning_note: str = ""
    provenance: dict
    note: str = ""
