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
