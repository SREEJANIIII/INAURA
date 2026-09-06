import { apiFetch } from "./api";

export type IndustryRequirement = {
  id: string;
  role: string;
  skill: string;
  skill_category: string;
  importance: number;
  demand: number;
  interview_relevance: number;
  source: string;
  source_url: string | null;
  description: string | null;
  version: string;
  metadata: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
};

export type RetrieveItem = {
  id: string;
  role: string;
  skill: string;
  skill_category: string;
  importance: number;
  demand: number;
  interview_relevance: number;
  source: string;
  source_url: string | null;
  description: string | null;
  version: string;
  similarity: number;
};

export type RetrieveResponse = {
  role: string;
  query: string;
  count: number;
  items: RetrieveItem[];
  note: string;
};

export type AnalysisState = {
  user_id: string;
  target_role: string | null;
  status: "not_started" | "ready" | "processing" | "completed" | "failed";
  last_retrieval: RetrieveResponse | null;
  created_at: string;
  updated_at: string;
};

export function listRoles() {
  return apiFetch<string[]>("/industry/roles");
}

export function getRequirements(role: string) {
  return apiFetch<IndustryRequirement[]>(`/industry/requirements?role=${encodeURIComponent(role)}`);
}

export function retrieveIndustry(payload: { role: string; query?: string; top_k?: number }) {
  return apiFetch<RetrieveResponse>("/industry/retrieve", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getAnalysisState() {
  return apiFetch<AnalysisState>("/analysis/state");
}

export function setTargetRole(target_role: string) {
  return apiFetch<AnalysisState>("/analysis/target", {
    method: "POST",
    body: JSON.stringify({ target_role }),
  });
}

export function prepareAnalysis(target_role?: string) {
  return apiFetch<{
    status: AnalysisState["status"];
    target_role: string;
    message: string;
    retrieval: RetrieveResponse | null;
  }>("/analysis/prepare", {
    method: "POST",
    body: JSON.stringify(target_role ? { target_role } : {}),
  });
}
