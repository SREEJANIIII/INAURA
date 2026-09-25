"""Phase 3A: industry outcome observation contracts.

industry-outcome-signal-v1 is frozen (Person 2 decision). This module adds the
observation-row, overlay, emerging-skill, and refresh contracts WITHOUT
changing the approved signal. No PII fields exist anywhere in this module.
"""

from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
from uuid import UUID

SIGNAL_VERSION = "industry-outcome-signal-v1"
TIME_WINDOW_BASIS = "applied_at for counts; feedback created_at for gap"

# Approved suppression thresholds (Phase 1 contract — do not change here).
CITY_MIN_APPLIED = 5
CITY_MIN_FEEDBACK = 5
ROLE_MIN_APPLIED = 10
ROLE_MIN_FEEDBACK = 5

# Scope sentinels (Correction 6, option A — explicit, no NULL ambiguity).
SCOPE_CITY = "city"
SCOPE_ROLE = "role"
SCOPE_GLOBAL = "global"
GLOBAL_LOCATION = "GLOBAL"

ALLOWED_SCOPES = (SCOPE_CITY, SCOPE_ROLE, SCOPE_GLOBAL)


class OutcomeSample(BaseModel):
    requirements_n: int = Field(..., ge=0)
    applied_n: int = Field(..., ge=0)
    feedback_count: int = Field(..., ge=0)


class OutcomeWindow(BaseModel):
    window_from: Optional[str] = None
    window_to: Optional[str] = None
    basis: str = TIME_WINDOW_BASIS


class OutcomeProvenance(BaseModel):
    signal_version: str = SIGNAL_VERSION
    scope: str = Field(..., pattern="^(city|role|global)$")
    location: str
    role: Optional[str] = None
    skill: Optional[str] = None


class OutcomeOverlay(BaseModel):
    """Contextual annotation on a curated requirement. Never a math input."""

    observed_demand: Optional[float] = Field(None, ge=0, le=1)
    observed_skill_gap: Optional[float] = Field(None, ge=-1, le=1)
    outcome_sample: OutcomeSample
    outcome_window: OutcomeWindow
    outcome_provenance: OutcomeProvenance
    stale: bool = False

    class Config:
        from_attributes = True


class ObservationOut(BaseModel):
    """API shape of one industry_outcome_observations row. Aggregates only."""

    id: UUID
    role: str
    skill: str
    skill_id: Optional[UUID] = None
    scope: str
    location: str
    window_from: Optional[str] = None
    window_to: Optional[str] = None
    requirements_n: int
    applied_n: int
    interview_count: int
    selection_count: int
    placement_count: int
    feedback_count: int
    observed_demand: Optional[float] = None
    observed_skill_gap: Optional[float] = None
    min_n_met: bool
    signal_version: str
    created_at: datetime

    class Config:
        from_attributes = True


class ObservationIssue(BaseModel):
    key: str
    code: str


class ObservationRefreshRequest(BaseModel):
    role: Optional[str] = Field(None, max_length=150)
    skill: Optional[str] = Field(None, max_length=150)
    location: Optional[str] = Field(None, max_length=200)
    scope: Optional[str] = Field(None, pattern="^(city|role|global)$")
    window_from: Optional[str] = None
    window_to: Optional[str] = None


class ObservationRefreshResponse(BaseModel):
    accepted: int = Field(..., ge=0)
    quarantined: int = Field(..., ge=0)
    issues: List[ObservationIssue] = []


class EmergingSkillOut(BaseModel):
    skill: str
    skill_id: Optional[UUID] = None
    observed_demand: Optional[float] = None
    observed_skill_gap: Optional[float] = None
    outcome_sample: OutcomeSample
    outcome_window: OutcomeWindow
    status: str = "observed_not_required"
    role: Optional[str] = None
    location: Optional[str] = None

    class Config:
        from_attributes = True


class IndustryOutcomeSignalV1(BaseModel):
    """Frozen contract mirror for validation reuse. Field set must match
    outcome_service.get_industry_signals()/get_industry_skill_signal() output."""

    signal_version: str = SIGNAL_VERSION
    role: Optional[str] = None
    location: Optional[str] = None
    skill: Optional[str] = None
    time_window: dict
    denominators: dict
    application_count: int
    interview_count: int
    selection_count: int
    placement_count: int
    feedback_count: int
    observed_demand: Optional[float] = None
    observed_skill_gap: Optional[float] = None
    min_n_met: bool

    class Config:
        from_attributes = True
