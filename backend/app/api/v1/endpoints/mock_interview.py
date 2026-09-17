"""Adaptive AI mock interview endpoints (evidence source, not a score oracle)."""

from fastapi import APIRouter, Depends

from ....core.security import get_current_user, CurrentUser
from ....schemas.mock_interview import (
    MockInterviewReport,
    MockInterviewSessionOut,
    StartMockInterviewRequest,
    StartMockInterviewResponse,
    SubmitMockAnswerRequest,
    SubmitMockAnswerResponse,
)
from ....services import mock_interview_service as svc

router = APIRouter(prefix="/interview", tags=["mock-interview"])


@router.post("/start", response_model=StartMockInterviewResponse)
async def start_mock_interview(
    payload: StartMockInterviewRequest, current_user: CurrentUser = Depends(get_current_user)
):
    """Start a personalized 3-question adaptive mock interview."""
    return await svc.start_session(
        user_id=current_user.id,
        target_role=payload.target_role,
        question_count=payload.question_count or 3,
    )


@router.get("/{session_id}", response_model=MockInterviewSessionOut)
async def get_mock_interview(session_id: str, current_user: CurrentUser = Depends(get_current_user)):
    """Load session state (plan + current question)."""
    return svc.get_session(user_id=current_user.id, session_id=session_id)


@router.post("/{session_id}/answer", response_model=SubmitMockAnswerResponse)
async def answer_mock_question(
    session_id: str,
    payload: SubmitMockAnswerRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    """Submit an answer transcript; Gemini evaluates it into structured evidence."""
    return await svc.submit_answer(
        user_id=current_user.id,
        session_id=session_id,
        transcript=payload.transcript,
        question_id=payload.question_id,
    )


@router.post("/{session_id}/complete", response_model=MockInterviewReport)
async def complete_mock_interview(
    session_id: str, current_user: CurrentUser = Depends(get_current_user)
):
    """Complete the session: build the evidence report and refresh analysis inputs."""
    return await svc.complete_session(user_id=current_user.id, session_id=session_id)


@router.get("/{session_id}/report", response_model=MockInterviewReport)
async def get_mock_report(session_id: str, current_user: CurrentUser = Depends(get_current_user)):
    """Read the evidence report for a completed session."""
    return svc.build_report(user_id=current_user.id, session_id=session_id)
