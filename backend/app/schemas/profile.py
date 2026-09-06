from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime


class ProfileBase(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=100, description="Full name")
    college: str = Field(..., min_length=2, max_length=150)
    degree: str = Field(..., min_length=2, max_length=100, description="Degree e.g., B.Tech, B.Sc")
    branch: str = Field(..., min_length=2, max_length=100, description="Branch / specialization")
    current_year: str = Field(..., description="Current year e.g., 1st Year, 2nd Year, Final Year, Graduate")
    graduation_year: int = Field(..., ge=2000, le=2035, description="Graduation year")
    career_interests: List[str] = Field(..., min_length=1, max_length=10, description="Areas of interest")
    hours_per_week: int = Field(..., ge=1, le=80, description="Hours available per week")


class ProfileCreate(ProfileBase):
    pass


class ProfileUpdate(ProfileBase):
    # All fields optional for partial update, but spec expects full setup
    full_name: Optional[str] = Field(None, min_length=2, max_length=100)
    college: Optional[str] = Field(None, min_length=2, max_length=150)
    degree: Optional[str] = Field(None, min_length=2, max_length=100)
    branch: Optional[str] = Field(None, min_length=2, max_length=100)
    current_year: Optional[str] = None
    graduation_year: Optional[int] = Field(None, ge=2000, le=2035)
    career_interests: Optional[List[str]] = None
    hours_per_week: Optional[int] = Field(None, ge=1, le=80)


class ProfileResponse(ProfileBase):
    user_id: str
    profile_completed: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
