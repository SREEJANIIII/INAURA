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

export type AIReviewResult = {
  review: Record<string, unknown>;
  meta: AIReviewMeta;
};

export function runAiReview(target_role?: string) {
  return apiFetch<AIReviewResult>("/ai-review-test", {
    method: "POST",
    body: JSON.stringify({ target_role: target_role || null }),
  });
}
