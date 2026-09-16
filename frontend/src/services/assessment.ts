import { apiFetch } from "./api";

/**
 * INAURA direct skill assessment.
 *
 * Prototype instrument: a short deterministic quiz used as the strongest
 * evidence source (VERY HIGH reliability), not a validated measurement of
 * human proficiency.
 */

export type AssessmentReason =
  | "conflicting_evidence"
  | "priority_gap"
  | "low_confidence"
  | "role_requirement"
  | string;

export type LastAssessment = {
  attempt_id: string | null;
  score: number;
  correct_count: number;
  question_count: number;
  completed_at: string | null;
  assessment_version: string | null;
  total_attempts: number;
};

export type AssessmentLayerKey = "knowledge" | "practical" | "interview";

export type LayerCapability = {
  skill: string;
  skill_key: string;
  knowledge_assessment: boolean;
  practical_assessment: boolean;
  interview_assessment: boolean;
  practical_kind: string | null;
  layers: AssessmentLayerKey[];
};

export type LayerResult = {
  status: string;
  score: number | null;
  attempt_id?: string | null;
  session_id?: string | null;
  completed_at?: string | null;
  validity?: string | null;
  communication_score?: number | null;
};

export type AvailableAssessment = {
  skill: string;
  skill_key: string;
  reason: AssessmentReason;
  reason_label: string;
  proficiency: number;
  confidence: number;
  required_level: number;
  gap: number;
  importance: number;
  priority_score: number;
  evidence_count: number;
  already_assessed: boolean;
  question_count: number;
  last_assessment: LastAssessment | null;
  /** Applicable assessment layers for this skill (additive; may be absent). */
  capabilities?: LayerCapability | null;
  /** Per-layer completion state (additive; may be absent). */
  layers?: Partial<Record<AssessmentLayerKey, LayerResult>> | null;
};

export type AvailableAssessmentsResponse = {
  assessment_version: string;
  target_role: string | null;
  analysis_id: string | null;
  available: AvailableAssessment[];
  disclaimer: string;
};

export type AssessmentQuestion = {
  id: string;
  skill: string;
  difficulty: string;
  kind: string;
  prompt: string;
  type: "multiple_choice" | "short_answer" | string;
  options: Array<{ id: string; text: string }>;
  version: string;
};

export type StartAssessmentResponse = {
  attempt_id: string;
  skill: string;
  skill_key: string;
  assessment_version: string;
  question_count: number;
  started_at: string;
  expires_at: string;
  questions: AssessmentQuestion[];
  disclaimer: string;
};

export type QuestionFeedback = {
  question_id: string;
  skill: string;
  difficulty: string;
  kind: string;
  correct: boolean;
  answered: boolean;
  explanation: string;
};

export type SubmitAssessmentResponse = {
  attempt_id: string;
  skill: string;
  assessment_version: string;
  score: number;
  correct_count: number;
  question_count: number;
  validity: "valid" | "low_confidence" | "invalid" | string;
  counts_as_evidence: boolean;
  completed_at: string;
  source_reliability: number;
  feedback: QuestionFeedback[];
  disclaimer: string;
  analysis?: {
    analysis_id?: string | null;
    target_role?: string | null;
    readiness_score?: number | null;
    evidence_component?: number | null;
    skill?: {
      skill: string;
      proficiency: number;
      confidence: number;
      gap: number;
      evidence_proficiency?: number;
      assessment_score?: number | null;
      has_assessment?: boolean;
    } | null;
  } | null;
};

export function getAvailableAssessments() {
  return apiFetch<AvailableAssessmentsResponse>("/analysis/assessment/available");
}

export function startAssessment(skill: string, questionCount?: number) {
  return apiFetch<StartAssessmentResponse>("/analysis/assessment/start", {
    method: "POST",
    body: JSON.stringify(questionCount ? { skill, question_count: questionCount } : { skill }),
  });
}

export function submitAssessment(
  attempt_id: string,
  responses: Record<string, string>,
  duration_seconds?: number
) {
  return apiFetch<SubmitAssessmentResponse>("/analysis/assessment/submit", {
    method: "POST",
    body: JSON.stringify({ attempt_id, responses, duration_seconds }),
  });
}

// ---------------------------------------------------------------------------
// Layer 2 — practical (work-sample) assessment
// ---------------------------------------------------------------------------

export type PracticalTask = {
  id: string;
  skill: string;
  task_type: string;
  title: string;
  prompt: string;
  starter_code: string;
  language: string;
  estimated_minutes: number;
  dimensions: Array<{ id: string; label: string }>;
  check_count: number;
  version: string;
};

export type StartPracticalResponse = {
  attempt_id: string;
  skill: string;
  skill_key: string;
  task_version: string;
  started_at: string;
  task: PracticalTask;
  disclaimer: string;
};

export type PracticalCheckResult = {
  check_id: string;
  dimension: string;
  description: string;
  passed: boolean;
};

export type SubmitPracticalResponse = {
  attempt_id: string;
  skill: string;
  task_id: string;
  task_version: string;
  score: number;
  validity: "valid" | "low_confidence" | "invalid" | string;
  counts_as_evidence: boolean;
  completed_at: string;
  source_reliability: number;
  dimensions: Record<string, number>;
  checks: PracticalCheckResult[];
  analysis?: SubmitAssessmentResponse["analysis"];
  disclaimer: string;
};

export function startPracticalAssessment(skill: string) {
  return apiFetch<StartPracticalResponse>("/analysis/assessment/practical/start", {
    method: "POST",
    body: JSON.stringify({ skill }),
  });
}

export function submitPracticalAssessment(
  attempt_id: string,
  code: string,
  duration_seconds?: number
) {
  return apiFetch<SubmitPracticalResponse>("/analysis/assessment/practical/submit", {
    method: "POST",
    body: JSON.stringify({ attempt_id, code, duration_seconds }),
  });
}

// ---------------------------------------------------------------------------
// Layer 3 — AI skill interview (one session validates exactly one skill)
// ---------------------------------------------------------------------------

export type InterviewQuestion = {
  id: string;
  competency: string;
  prompt: string;
  follow_ups: string[];
};

export type StartInterviewResponse = {
  session_id: string;
  skill: string;
  skill_key: string;
  interview_version: string;
  status: string;
  started_at: string;
  plan: {
    skill: string;
    competencies: Array<{ id: string; label: string }>;
    focus_areas: string[];
    questions: InterviewQuestion[];
    estimated_minutes: number;
  };
  evaluated_dimensions: Record<string, string[]>;
  privacy_notice: string;
  disclaimer: string;
};

export type InterviewSession = {
  session_id: string | null;
  skill: string | null;
  status: string;
  plan: StartInterviewResponse["plan"];
  transcript: Array<{
    question_id: string;
    competency: string;
    prompt: string;
    answer: string;
    answered: boolean;
  }>;
  technical_scores: { per_competency: Record<string, number>; overall: number } | null;
  communication_scores: { per_dimension: Record<string, number>; overall: number } | null;
  started_at: string | null;
  completed_at: string | null;
};

export type CompleteInterviewResponse = {
  session_id: string;
  skill: string;
  status: string;
  validity: string;
  counts_as_evidence: boolean;
  completed_at: string | null;
  source_reliability: number | null;
  technical_scores: InterviewSession["technical_scores"];
  communication_scores: InterviewSession["communication_scores"];
  analysis?: SubmitAssessmentResponse["analysis"];
  note?: string | null;
};

export function startSkillInterview(skill: string) {
  return apiFetch<StartInterviewResponse>("/analysis/assessment/interview/start", {
    method: "POST",
    body: JSON.stringify({ skill }),
  });
}

export function getSkillInterview(session_id: string) {
  return apiFetch<InterviewSession>(`/analysis/assessment/interview/${encodeURIComponent(session_id)}`);
}

export function submitInterviewResponses(session_id: string, responses: Record<string, string>) {
  return apiFetch<{ session_id: string; skill: string | null; answered: number; total: number }>(
    "/analysis/assessment/interview/respond",
    {
      method: "POST",
      body: JSON.stringify({ session_id, responses }),
    }
  );
}

export function completeSkillInterview(session_id: string) {
  return apiFetch<CompleteInterviewResponse>("/analysis/assessment/interview/complete", {
    method: "POST",
    body: JSON.stringify({ session_id }),
  });
}
