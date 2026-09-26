import { apiFetch } from "./api";

export type OutcomeOverlay = {
  observed_demand: number | null;
  observed_skill_gap: number | null;
  outcome_sample: { requirements_n: number; applied_n: number; feedback_count: number };
  outcome_window: { window_from: string | null; window_to: string | null; basis: string };
  outcome_provenance: {
    signal_version: string;
    scope: string;
    location: string;
    role: string | null;
    skill: string | null;
  };
  stale: boolean;
};

export type EmergingSkill = {
  skill: string;
  skill_id: string | null;
  observed_demand: number | null;
  observed_skill_gap: number | null;
  outcome_sample: OutcomeOverlay["outcome_sample"];
  outcome_window: OutcomeOverlay["outcome_window"];
  status: "observed_not_required";
  role: string | null;
  location: string | null;
};

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
  // Phase 3: contextual employer-outcome annotation. Absent unless the
  // overlay is enabled and the cell meets its threshold. Never a math input.
  outcome_overlay?: OutcomeOverlay | null;
  // Dynamic Industry Intelligence (all optional for compatibility)
  required_level?: number;
  industry_confidence?: number;
  trend?: string | null;
  freshness?: string | null;
  data_origin?: string | null;
  location?: Record<string, unknown> | null;
  collected_at?: string | null;
  last_updated?: string | null;
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
  // Dynamic Industry Intelligence (all optional for compatibility)
  trend?: string | null;
  freshness?: string | null;
  data_origin?: string | null;
  location?: Record<string, unknown> | null;
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

export type RoleSummary = {
  title: string;
  slug: string;
  category: string;
  description: string;
  aliases: string[];
  source_benchmarks: string[];
};

/** The catalog roles INAURA has industry benchmarks for, with descriptions */
export function getRolesCatalog() {
  return apiFetch<RoleSummary[]>("/industry/roles/catalog");
}

export function listRoles() {
  return apiFetch<string[]>("/industry/roles");
}

export function getRequirements(role: string) {
  return apiFetch<IndustryRequirement[]>(`/industry/requirements?role=${encodeURIComponent(role)}`);
}

// Phase 3: aggregated employer-observed skills with no curated requirement.
// Read-only; every item carries status "observed_not_required".
export function getEmergingSkills(role: string, location?: string) {
  const q = location
    ? `?role=${encodeURIComponent(role)}&location=${encodeURIComponent(location)}`
    : `?role=${encodeURIComponent(role)}`;
  return apiFetch<EmergingSkill[]>(`/industry/outcomes/emerging${q}`);
}

// export function retrieveIndustry(payload: { role: string; query?: string; top_k?: number }) {
export function retrieveIndustry(payload: { role: string; query?: string; top_k?: number; location?: string }) {
  return apiFetch<RetrieveResponse>("/industry/retrieve", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export type IntelligenceSkill = {
  id?: string | null;
  role: string;
  skill: string;
  skill_slug?: string | null;
  skill_category?: string | null;
  required_level: number;
  importance: number;
  demand: number;
  interview_relevance: number;
  industry_confidence: number;
  trend?: string | null;
  freshness?: string | null;
  source: string;
  source_url?: string | null;
  evidence_context?: string | null;
  data_origin?: string | null;
  data_origins?: string[] | null;
  location?: { label?: string; scope?: string } | null;
  location_match?: string | null;
  mapping_status?: string | null;
  source_concept?: string | null;
  canonical_mapping?: string | null;
  mapping_rationale?: string | null;
  collected_at?: string | null;
  last_updated?: string | null;
  published_at?: string | null;
  retrieved_at?: string | null;
};

export type IntelligenceResponse = {
  role: string;
  location: { label?: string; scope?: string };
  location_match: string;
  last_updated: string | null;
  skills: IntelligenceSkill[];
  counts?: Record<string, number> | null;
  data_origins?: string[] | null;
  note: string;
};

export function getRoleIntelligence(role: string, location?: string) {
  const params = new URLSearchParams({ role });
  if (location && location.trim()) params.set("location", location.trim());
  return apiFetch<IntelligenceResponse>(`/industry/intelligence?${params.toString()}`);
}

export function listDemandProviders() {
  return apiFetch<
    { provider_id: string; display_name: string; data_origin: string; is_live: boolean; description: string }[]
  >("/industry/providers");
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
