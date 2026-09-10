from fastapi import APIRouter, Depends

from ....core.security import get_current_user, CurrentUser
from ....schemas.assessment import (
    AvailableAssessmentsResponse,
    StartAssessmentRequest,
    StartAssessmentResponse,
    SubmitAssessmentRequest,
    SubmitAssessmentResponse,
)
from ....services.assessment import service as assessment_service
from ....services.assessment.question_bank import DEFAULT_QUESTION_COUNT

router = APIRouter(prefix="/analysis/assessment", tags=["assessment"])


@router.get("/available", response_model=AvailableAssessmentsResponse)
async def get_available_assessments(current_user: CurrentUser = Depends(get_current_user)):
    """Skills INAURA has a reason to verify directly, with their latest results."""
    return assessment_service.list_available_assessments(current_user.id)


@router.post("/start", response_model=StartAssessmentResponse)
async def start_assessment(
    payload: StartAssessmentRequest, current_user: CurrentUser = Depends(get_current_user)
):
    """Begin an attempt for one skill and return its questions (no answer keys)."""
    return assessment_service.start_attempt(
        user_id=current_user.id,
        skill=payload.skill,
        question_count=payload.question_count or DEFAULT_QUESTION_COUNT,
    )


@router.post("/submit", response_model=SubmitAssessmentResponse)
async def submit_assessment(
    payload: SubmitAssessmentRequest, current_user: CurrentUser = Depends(get_current_user)
):
    """
    Grade an attempt deterministically, store the result, and recalculate the
    analysis so the assessed skill's proficiency, confidence, gap, priority and
    readiness are updated immediately.
    """
    return await assessment_service.submit_attempt(
        user_id=current_user.id,
        attempt_id=payload.attempt_id,
        responses=payload.responses,
        duration_seconds=payload.duration_seconds,
    )
