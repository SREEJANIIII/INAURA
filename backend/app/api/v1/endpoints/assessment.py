from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Response

from ....core.config import get_settings
from ....core.security import get_current_user, CurrentUser
from ....schemas.assessment import (
    AnswerInterviewRequest,
    AnswerInterviewResponse,
    AvailableAssessmentsResponse,
    CompleteInterviewRequest,
    CompleteInterviewResponse,
    InterviewSessionOut,
    StartAssessmentRequest,
    StartAssessmentResponse,
    StartInterviewRequest,
    StartInterviewResponse,
    InterviewTTSRequest,
    StartPracticalRequest,
    StartPracticalResponse,
    SubmitAssessmentRequest,
    SubmitAssessmentResponse,
    SubmitInterviewResponsesRequest,
    SubmitInterviewResponsesResponse,
    SubmitPracticalRequest,
    SubmitPracticalResponse,
)
from ....services.assessment import service as assessment_service
from ....services.assessment import interview as interview_service
from ....services.assessment import practical_service
from ....services.assessment.question_bank import DEFAULT_QUESTION_COUNT
from ....services import tts_service

router = APIRouter(prefix="/analysis/assessment", tags=["assessment"])


@router.post("/interview/tts")
async def interview_tts(payload: InterviewTTSRequest, current_user: CurrentUser = Depends(get_current_user)):
    """Voice the exact Gemini-generated question text via NVIDIA TTS.

    Called only AFTER the answer endpoint has produced the next question.
    NVIDIA_API_KEY stays server-side; failures never touch the interview.
    Provider (502) failures surface here as 503: generic in production,
    with safe provider facts when TTS_DEBUG=true for local development.
    """
    try:
        result = await tts_service.synthesize(payload.text, payload.session_id, payload.question_id)
    except HTTPException as exc:
        if exc.status_code != 502:
            raise
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        response: Dict[str, Any] = {
            "message": "NVIDIA TTS request failed",
            "provider": "nvidia",
        }
        if get_settings().tts_debug is True:
            response.update({
                "status": detail.get("status"),
                "category": detail.get("error_category"),
                "reason": detail.get("reason") or detail.get("message"),
            })
        raise HTTPException(status_code=503, detail=response) from exc
    return Response(content=result.audio, media_type=result.media_type, headers={"Cache-Control": "no-store"})


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


# ---------------------------------------------------------------------------
# Layer 2 — practical (work-sample) assessment
# ---------------------------------------------------------------------------

@router.post("/practical/start", response_model=StartPracticalResponse)
async def start_practical_assessment(
    payload: StartPracticalRequest, current_user: CurrentUser = Depends(get_current_user)
):
    """Begin a practical work-sample attempt for one skill (where applicable)."""
    return practical_service.start_practical_attempt(
        user_id=current_user.id,
        skill=payload.skill,
    )


@router.post("/practical/submit", response_model=SubmitPracticalResponse)
async def submit_practical_assessment(
    payload: SubmitPracticalRequest, current_user: CurrentUser = Depends(get_current_user)
):
    """
    Grade a practical submission deterministically and recalculate the
    analysis so the skill profile incorporates the new signal immediately.
    """
    return await practical_service.submit_practical_attempt(
        user_id=current_user.id,
        attempt_id=payload.attempt_id,
        code=payload.code,
        duration_seconds=payload.duration_seconds,
    )


# ---------------------------------------------------------------------------
# Layer 3 — AI skill interview (one session validates exactly one skill)
# ---------------------------------------------------------------------------

@router.post("/interview/start", response_model=StartInterviewResponse)
async def start_skill_interview(
    payload: StartInterviewRequest, current_user: CurrentUser = Depends(get_current_user)
):
    """Create a skill-specific interview session with its adaptive plan."""
    return interview_service.start_interview_session(
        user_id=current_user.id,
        skill=payload.skill,
    )


@router.get("/interview/{session_id}", response_model=InterviewSessionOut)
async def get_skill_interview(
    session_id: str, current_user: CurrentUser = Depends(get_current_user)
):
    """Load an interview session (plan + transcript)."""
    return interview_service.get_interview_session(
        user_id=current_user.id,
        session_id=session_id,
    )


@router.post("/interview/respond", response_model=SubmitInterviewResponsesResponse)
async def submit_interview_responses(
    payload: SubmitInterviewResponsesRequest, current_user: CurrentUser = Depends(get_current_user)
):
    """Save written answers onto an in-progress interview session."""
    return interview_service.submit_interview_responses(
        user_id=current_user.id,
        session_id=payload.session_id,
        responses=payload.responses,
    )


@router.post("/interview/complete", response_model=CompleteInterviewResponse)
async def complete_skill_interview(
    payload: CompleteInterviewRequest, current_user: CurrentUser = Depends(get_current_user)
):
    """
    Finish an interview: grade against the fixed rubric when grading is
    configured, otherwise keep the transcript as awaiting review. Either way
    the existing skill profile is never overwritten — at most one new
    interview signal flows through the standard pipeline.
    """
    return await interview_service.complete_interview_session(
        user_id=current_user.id,
        session_id=payload.session_id,
    )


@router.post("/interview/{session_id}/answer", response_model=AnswerInterviewResponse)
async def answer_interview_question(
    session_id: str,
    payload: AnswerInterviewRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    """Submit one answer to a skill interview question; Gemini evaluates it
    and the system decides whether to ask a follow-up or advance."""
    return await interview_service.answer_interview_question(
        user_id=current_user.id,
        session_id=session_id,
        question_id=payload.question_id,
        transcript=payload.transcript,
    )
