from pydantic import BaseModel, Field
from typing import Dict, List, Optional


class StartAssessmentRequest(BaseModel):
    skill: str = Field(..., min_length=1, max_length=120, description="Canonical skill name or alias, e.g. 'Python'")
    question_count: Optional[int] = Field(
        None, ge=3, le=7, description="Requested number of questions (prototype range 3-7)"
    )


class SubmitAssessmentRequest(BaseModel):
    attempt_id: str = Field(..., min_length=8, max_length=64)
    responses: Dict[str, str] = Field(
        default_factory=dict,
        description="Map of question_id -> selected option id (MCQ) or short answer text",
    )
    duration_seconds: Optional[int] = Field(None, ge=0, le=86400)


class AssessmentOption(BaseModel):
    id: str
    text: str


class AssessmentQuestionOut(BaseModel):
    id: str
    skill: str
    difficulty: str
    kind: str
    prompt: str
    type: str
    options: List[AssessmentOption] = []
    version: str


class StartAssessmentResponse(BaseModel):
    attempt_id: str
    skill: str
    skill_key: str
    assessment_version: str
    question_count: int
    started_at: str
    expires_at: str
    questions: List[AssessmentQuestionOut]
    disclaimer: str


class LastAssessment(BaseModel):
    attempt_id: Optional[str] = None
    score: float = 0.0
    correct_count: int = 0
    question_count: int = 0
    completed_at: Optional[str] = None
    assessment_version: Optional[str] = None
    total_attempts: int = 1


class LayerCapability(BaseModel):
    """Which assessment layers apply to one skill (additive, optional)."""

    skill: str = ""
    skill_key: str = ""
    knowledge_assessment: bool = False
    practical_assessment: bool = False
    interview_assessment: bool = False
    practical_kind: Optional[str] = None
    layers: List[str] = []


class LayerResult(BaseModel):
    """Completion state of one layer for one skill (additive, optional)."""

    status: str = "not_started"
    score: Optional[float] = None
    attempt_id: Optional[str] = None
    session_id: Optional[str] = None
    completed_at: Optional[str] = None
    validity: Optional[str] = None
    communication_score: Optional[float] = None


class AvailableAssessment(BaseModel):
    skill: str
    skill_key: str
    reason: str
    reason_label: str
    proficiency: float = 0.0
    confidence: float = 0.0
    required_level: float = 0.0
    gap: float = 0.0
    importance: float = 0.0
    priority_score: float = 0.0
    evidence_count: int = 0
    already_assessed: bool = False
    question_count: int = 0
    last_assessment: Optional[LastAssessment] = None
    # 3-layer assessment (additive): applicable layers + per-layer progress.
    capabilities: Optional[LayerCapability] = None
    layers: Optional[Dict[str, LayerResult]] = None


class AvailableAssessmentsResponse(BaseModel):
    assessment_version: str
    target_role: Optional[str] = None
    analysis_id: Optional[str] = None
    available: List[AvailableAssessment] = []
    disclaimer: str


class QuestionFeedback(BaseModel):
    question_id: str
    skill: str
    difficulty: str
    kind: str
    correct: bool
    answered: bool
    explanation: str


class SubmitAssessmentResponse(BaseModel):
    attempt_id: str
    skill: str
    assessment_version: str
    score: float
    correct_count: int
    question_count: int
    validity: str
    counts_as_evidence: bool
    completed_at: str
    source_reliability: float
    feedback: List[QuestionFeedback] = []
    analysis: Optional[dict] = None
    disclaimer: str


# ---------------------------------------------------------------------------
# Layer 2 — practical assessment
# ---------------------------------------------------------------------------

class PracticalTaskDimension(BaseModel):
    id: str
    label: str


class PracticalTaskOut(BaseModel):
    id: str
    skill: str
    task_type: str
    title: str
    prompt: str
    starter_code: str = ""
    language: str = ""
    estimated_minutes: int = 20
    dimensions: List[PracticalTaskDimension] = []
    check_count: int = 0
    version: str


class StartPracticalRequest(BaseModel):
    skill: str = Field(..., min_length=1, max_length=120)


class StartPracticalResponse(BaseModel):
    attempt_id: str
    skill: str
    skill_key: str
    task_version: str
    started_at: str
    task: PracticalTaskOut
    disclaimer: str


class PracticalCheckResult(BaseModel):
    check_id: str
    dimension: str
    description: str
    passed: bool


class SubmitPracticalRequest(BaseModel):
    attempt_id: str = Field(..., min_length=8, max_length=64)
    code: str = Field(default="", max_length=20000)
    duration_seconds: Optional[int] = Field(None, ge=0, le=86400)


class SubmitPracticalResponse(BaseModel):
    attempt_id: str
    skill: str
    task_id: str
    task_version: str
    score: float
    validity: str
    counts_as_evidence: bool
    completed_at: str
    source_reliability: float
    dimensions: Dict[str, float] = {}
    checks: List[PracticalCheckResult] = []
    analysis: Optional[dict] = None
    disclaimer: str


# ---------------------------------------------------------------------------
# Layer 3 — AI skill interview
# ---------------------------------------------------------------------------

class StartInterviewRequest(BaseModel):
    skill: str = Field(..., min_length=1, max_length=120)


class InterviewTTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)
    session_id: str = Field(default="", max_length=64)
    question_id: str = Field(default="", max_length=120)


class InterviewQuestionOut(BaseModel):
    id: str
    competency: str
    prompt: str
    follow_ups: List[str] = []


class InterviewCompetencyOut(BaseModel):
    id: str
    label: str


class StartInterviewResponse(BaseModel):
    session_id: str
    skill: str
    skill_key: str
    interview_version: str
    status: str
    started_at: str
    plan: dict
    evaluated_dimensions: Dict[str, List[str]] = {}
    privacy_notice: str
    disclaimer: str


class InterviewSessionOut(BaseModel):
    session_id: Optional[str] = None
    skill: Optional[str] = None
    status: str = "in_progress"
    plan: dict = {}
    transcript: List[dict] = []
    technical_scores: Optional[dict] = None
    communication_scores: Optional[dict] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class SubmitInterviewResponsesRequest(BaseModel):
    session_id: str = Field(..., min_length=8, max_length=64)
    responses: Dict[str, str] = Field(
        default_factory=dict,
        description="Map of question_id -> written answer text",
    )


class SubmitInterviewResponsesResponse(BaseModel):
    session_id: str
    skill: Optional[str] = None
    answered: int = 0
    total: int = 0


class CompleteInterviewRequest(BaseModel):
    session_id: str = Field(..., min_length=8, max_length=64)


class CompleteInterviewResponse(BaseModel):
    session_id: str
    skill: str
    status: str
    validity: str
    counts_as_evidence: bool
    completed_at: Optional[str] = None
    source_reliability: Optional[float] = None
    technical_scores: Optional[dict] = None
    communication_scores: Optional[dict] = None
    analysis: Optional[dict] = None
    grading_path: Optional[str] = None
    note: Optional[str] = None


# ---------------------------------------------------------------------------
# Layer 3 — Per-answer adaptive interview
# ---------------------------------------------------------------------------

class AnswerInterviewRequest(BaseModel):
    question_id: str = Field(..., min_length=1, max_length=120)
    transcript: str = Field(..., min_length=1, max_length=8000, description="Answer text (typed or voice-transcribed)")


class AnswerInterviewEvaluation(BaseModel):
    """Structured per-answer evaluation from Gemini."""
    question_id: str = ""
    technical_correctness: float = Field(default=0.0, ge=0.0, le=1.0)
    depth: float = Field(default=0.0, ge=0.0, le=1.0)
    reasoning: float = Field(default=0.0, ge=0.0, le=1.0)
    specificity: float = Field(default=0.0, ge=0.0, le=1.0)
    communication: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_corroboration: float = Field(default=0.0, ge=0.0, le=1.0)
    contradiction: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    brief_explanation: str = ""
    follow_up_needed: bool = False
    suggested_follow_up: str = ""
    next_question: str = ""
    next_question_reason: str = ""
    target_competency: str = ""
    question_type: str = ""
    demonstrated: List[str] = []
    missing: List[str] = []
    misconceptions: List[str] = []


class AnswerInterviewQuestionOut(BaseModel):
    id: str
    competency: str
    prompt: str
    follow_ups: List[str] = []


class AnswerInterviewResponse(BaseModel):
    session_id: str
    question_id: str
    next_action: str = "next"
    action: Optional[str] = None
    spoken_response: Optional[str] = None
    ai_available: bool = True
    evaluation: Optional[AnswerInterviewEvaluation] = None
    evaluation_pending: bool = False
    current_index: int = 0
    current_question: Optional[AnswerInterviewQuestionOut] = None
    completed: bool = False
    answered_count: int = 0
    total_questions: int = 0
    note: Optional[str] = None
    failure_category: Optional[str] = None
    provider_status: Optional[int] = None
    provider_code: Optional[str] = None
    retry_after: Optional[str] = None
