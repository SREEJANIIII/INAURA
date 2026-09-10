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
