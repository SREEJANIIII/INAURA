import { apiFetch } from "./api";

export type AIReviewMeta = {
  experimental: string;
  model: string;
  llm_calls: number;
  latency_ms: number;
  usage: {
    input_tokens?: number | null;
    output_tokens?: number | null;
    total_tokens?: number | null;
  } | null;
  data_sources: string[];
  target_role: string;
};

export type ComparisonRow = {
  skill: string;
  deterministic: {
    level_pct: number;
    direction: string;
    evidence_count: number;
    evidence_state: string;
  } | null;
  gemini: {
    level_pct: number | null;
    verdict: string;
    direction: string;
  } | null;
  category:
    | "agreement"
    | "partial_agreement"
    | "disagreement"
    | "gemini_only"
    | "engine_only";
  detail: string;
};

export type AIComparison = {
  version: string;
  rows: ComparisonRow[];
  agreements: string[];
  differences: Array<{
    skill: string;
    category: string;
    deterministic: ComparisonRow["deterministic"];
    gemini: ComparisonRow["gemini"];
    detail: string;
  }>;
  ai_only_insights: Array<{ kind: string; text: string }>;
  engine_only_insights: Array<{
    skill: string;
    proficiency_pct?: number;
    gap_pct?: number;
    reason: string;
  }>;
  warnings: Array<{ type: string; skill: string; detail: string }>;
  note: string;
};

export type AIReviewResult = {
  review: Record<string, unknown>;
  meta: AIReviewMeta;
  comparison?: AIComparison | null;
};

export function runAiReview(target_role?: string) {
  return apiFetch<AIReviewResult>("/ai-review-test", {
    method: "POST",
    body: JSON.stringify({ target_role: target_role || null }),
  });
}
