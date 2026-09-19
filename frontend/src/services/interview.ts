import { apiFetch } from "./api";

/**
 * Adaptive AI mock interview — INAURA evidence source.
 * Camera/mic stay in the browser; only transcripts + structured
 * evaluations travel to the backend (Gemini calls are server-side).
 */

export type MockQuestion = {
  id: string;
  sequence: number;
  question: string;
  question_type: string;
  target_skill: string;
  source_evidence: string;
  priority: number;
  interview_relevance: number;
  is_follow_up: boolean;
  parent_question_id: string | null;
};

export type AnswerEvaluation = {
  question_id: string;
  skills: string[];
  technical_correctness: number;
  depth: number;
  reasoning: number;
  communication: number;
  evidence_corroboration: number;
  contradiction: number;
  confidence: number;
  explanation: string;
  demonstrated?: string[];
  missing?: string[];
  misconceptions?: string[];
  follow_up_needed: boolean;
  suggested_follow_up: string;
};

export type StartInterviewResponse = {
  session_id: string;
  target_role: string;
  status: string;
  question_count: number;
  current_index: number;
  questions: MockQuestion[];
  current_question: MockQuestion | null;
  ai_available: boolean;
  privacy_notice: string;
  disclaimer: string;
};

export type AnswerResponse = {
  session_id: string;
  question_id: string;
  next_action: string;
  ai_available: boolean;
  evaluation: AnswerEvaluation | null;
  evaluation_pending: boolean;
  spoken_response?: string | null;
  current_index: number;
  current_question: MockQuestion | null;
  completed: boolean;
  answered_count: number;
  question_count: number;
  provider_used?: string | null;
  note: string | null;
};

export type SessionState = {
  session_id: string;
  target_role: string;
  status: string;
  question_count: number;
  current_index: number;
  questions: MockQuestion[];
  current_question: MockQuestion | null;
  answers_count: number;
  ai_available: boolean;
};

export type SkillResult = {
  skill: string;
  evidence_before: number | null;
  proficiency_before: number | null;
  confidence_before: number | null;
  interview_signal: number | null;
  verdict: string;
  explanation: string;
};

export type InterviewReport = {
  session_id: string;
  target_role: string;
  status: string;
  questions_answered: number;
  skills_evaluated: string[];
  strengths: string[];
  weak_evidence: string[];
  needs_validation: string[];
  corroborated: string[];
  inconsistencies: Array<{ skill: string; detail: string }>;
  skill_results: SkillResult[];
  recommended_next_actions: string[];
  overall_interview_confidence: number;
  ai_available: boolean;
  note: string | null;
};

export function startMockInterview(target_role?: string, question_count = 3) {
  return apiFetch<StartInterviewResponse>("/interview/start", {
    method: "POST",
    body: JSON.stringify({ target_role: target_role || undefined, question_count }),
  });
}

export function getMockSession(session_id: string) {
  return apiFetch<SessionState>(`/interview/${encodeURIComponent(session_id)}`);
}

export function answerMockQuestion(session_id: string, transcript: string, question_id?: string) {
  return apiFetch<AnswerResponse>(`/interview/${encodeURIComponent(session_id)}/answer`, {
    method: "POST",
    body: JSON.stringify({ transcript, question_id: question_id || undefined }),
  });
}

export function completeMockInterview(session_id: string) {
  return apiFetch<InterviewReport>(`/interview/${encodeURIComponent(session_id)}/complete`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export function getMockReport(session_id: string) {
  return apiFetch<InterviewReport>(`/interview/${encodeURIComponent(session_id)}/report`);
}
