"""Pydantic schemas for the adaptive AI mock interview.

The mock interview is ANOTHER EVIDENCE SOURCE for INAURA's
evidence-driven architecture — it never overwrites deterministic
proficiency directly. Gemini produces structured per-answer evidence;
the skill engine aggregates it through the standard pipeline.
"""

from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class StartMockInterviewRequest(BaseModel):
    target_role: Optional[str] = Field(
        default=None, max_length=100, description="Target role; defaults to analysis state / profile"
    )
    question_count: Optional[int] = Field(
        default=6, ge=5, le=8, description="Planned questions (prototype range 5-8)"
    )


class MockInterviewQuestionOut(BaseModel):
    id: str
    sequence: int
    question: str
    question_type: str = "technical"
    target_skill: str = ""
    source_evidence: str = ""
    priority: float = 0.0
    interview_relevance: float = 0.0
    is_follow_up: bool = False
    parent_question_id: Optional[str] = None


class StartMockInterviewResponse(BaseModel):
    session_id: str
    target_role: str
    status: str
    question_count: int
    current_index: int = 0
    questions: List[MockInterviewQuestionOut] = []
    current_question: Optional[MockInterviewQuestionOut] = None
    ai_available: bool = True
    privacy_notice: str
    disclaimer: str


class AnswerEvaluation(BaseModel):
    """Structured interview evidence for ONE answer (Gemini output, validated)."""

    question_id: str = ""
    skills: List[str] = Field(default_factory=list)
    technical_correctness: float = Field(default=0.0, ge=0.0, le=1.0)
    depth: float = Field(default=0.0, ge=0.0, le=1.0)
    reasoning: float = Field(default=0.0, ge=0.0, le=1.0)
    communication: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_corroboration: float = Field(default=0.0, ge=0.0, le=1.0)
    contradiction: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    explanation: str = ""
    follow_up_needed: bool = False
    suggested_follow_up: str = ""


class SubmitMockAnswerRequest(BaseModel):
    transcript: str = Field(..., min_length=1, max_length=8000, description="Answer transcript (typed or transcribed)")
    question_id: Optional[str] = Field(default=None, description="Defaults to current question")


class SubmitMockAnswerResponse(BaseModel):
    session_id: str
    question_id: str
    next_action: str = "next"
    ai_available: bool = True
    evaluation: Optional[AnswerEvaluation] = None
    evaluation_pending: bool = False
    current_index: int = 0
    current_question: Optional[MockInterviewQuestionOut] = None
    completed: bool = False
    note: Optional[str] = None


class MockInterviewSessionOut(BaseModel):
    session_id: str
    target_role: str
    status: str
    question_count: int
    current_index: int
    questions: List[MockInterviewQuestionOut] = []
    current_question: Optional[MockInterviewQuestionOut] = None
    answers_count: int = 0
    ai_available: bool = True


class SkillInterviewResult(BaseModel):
    skill: str
    evidence_before: Optional[float] = None
    proficiency_before: Optional[float] = None
    confidence_before: Optional[float] = None
    interview_signal: Optional[float] = None
    verdict: str = "insufficient_data"
    explanation: str = ""


class MockInterviewReport(BaseModel):
    session_id: str
    target_role: str
    status: str
    questions_answered: int
    skills_evaluated: List[str] = []
    strengths: List[str] = []
    weak_evidence: List[str] = []
    needs_validation: List[str] = []
    corroborated: List[str] = []
    inconsistencies: List[Dict[str, str]] = []
    skill_results: List[SkillInterviewResult] = []
    recommended_next_actions: List[str] = []
    overall_interview_confidence: float = 0.0
    ai_available: bool = True
    note: Optional[str] = None
