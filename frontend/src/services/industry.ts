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

// Labour-market observations (P0 #1): aggregated imported-posting signals.
// Derived measurements with provenance; demo-origin rows are synthetic and
// must never be labelled live.
export type LabourMarketSignal = {
  role_key: string;
  skill_slug?: string | null;
  source_concept?: string | null;
  mapping_status: string;
  location_scope: string;
  country?: string | null;
  region?: string | null;
  city?: string | null;
  period_start: string;
  period_end: string;
  posting_count: number;
  skill_posting_count: number;
  distinct_company_count?: number | null;
  skill_share?: number | null;
  demand?: number | null;
  required_level?: number | null;
  importance?: number | null;
  trend: string;
  confidence?: number | null;
  evidence_suppressed: boolean;
  provider_id: string;
  data_origin: string;
  source_version?: string | null;
  evidence_context?: string | null;
  computed_at?: string | null;
};

export function getLabourMarketSignals(params: {
  role?: string;
  skill?: string;
  country?: string;
  region?: string;
  city?: string;
  start_date?: string;
  end_date?: string;
  provider_id?: string;
  include_raw_concepts?: boolean;
} = {}) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    q.set(k, String(v));
  }
  const suffix = q.toString() ? `?${q.toString()}` : "";
  return apiFetch<LabourMarketSignal[]>(`/industry/labour-market/signals${suffix}`);
}

// Course / industry alignment (P0 #4): deterministic projection joining
// labour-market demand, course curriculum, and cohort supply on canonical
// skill identity. Aggregate dimensions only — no student-level data.
export type AlignmentSkillRow = {
  skill: string;
  display_name?: string | null;
  category?: string | null;
  industry?: {
    required: boolean;
    posting_count?: number | null;
    skill_posting_count?: number | null;
    skill_share?: number | null;
    trend?: string | null;
    confidence?: number | null;
    evidence_suppressed?: boolean | null;
    provider_id?: string | null;
    data_origin?: string | null;
  } | null;
  curriculum?: {
    taught: boolean;
    coverage?: string | null;
    modules: string[];
    mapping_status?: string | null;
  } | null;
  cohort?: {
    evidenced_member_count?: number | null;
    verified_member_count?: number | null;
    skill_coverage?: number | null;
    verified_coverage?: number | null;
    average_proficiency?: number | null;
  } | null;
  alignment: {
    curriculum_status: string;
    attainment_status: string;
    demand_status: string;
    overall_status: string;
    priority: string;
    priority_reasons: string[];
  };
};

export type CourseAlignmentResponse = {
  role: string;
  canonical_role?: string | null;
  role_mapping_status: string;
  course: { id: string; name?: string | null };
  institution: { id: string; name?: string | null };
  market_context?: Record<string, unknown> | null;
  cohort_context?: { mode?: string; member_count?: number; suppressed?: boolean } | null;
  skills: AlignmentSkillRow[];
  summary: Record<string, number>;
  extra_cohort_skills: string[];
  unmapped_excluded: Record<string, number>;
  provenance: Record<string, unknown>;
  note: string;
};

export function getCourseAlignment(params: {
  course_id: string;
  role: string;
  cohort_id?: string;
  country?: string;
  region?: string;
  city?: string;
  start_date?: string;
  end_date?: string;
  provider_id?: string;
}) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    q.set(k, String(v));
  }
  return apiFetch<CourseAlignmentResponse>(`/industry/course-alignment?${q.toString()}`);
}

// District training intelligence (P0 #5): evidence-backed planning inputs
// aggregated over district institutions/courses/cohorts. Aggregate
// dimensions only — no student-level data, no seat recommendations.
export type DistrictSkillRow = {
  skill: string;
  display_name?: string | null;
  market?: {
    skill_share?: number | null;
    trend?: string | null;
  } | null;
  training_supply: {
    learner_count: number;
    evidenced_learner_count: number;
    verified_learner_count: number;
    verified_coverage?: number | null;
  };
  curriculum: { courses_teaching: number; courses_missing: number };
  trainer: { trainer_count: number; trainer_signal: string };
  gap: { curriculum?: string | null; attainment?: string | null; concentration?: string | null };
  priority: { level: string; reasons: string[] };
};

export type DistrictTrainingResponse = {
  district: string;
  district_status: string;
  role: string;
  market_context?: { match_type?: string } | null;
  institutions: { id: string; name?: string | null; institution_type?: string | null }[];
  skills: DistrictSkillRow[];
  suppressed: boolean;
  summary: Record<string, number | Record<string, number>>;
  capacity: { capacity_evidence_status: string; seat_note: string };
  provenance: Record<string, unknown>;
  note: string;
};

export function getDistrictTraining(params: {
  district: string;
  role: string;
  state?: string;
  country?: string;
  city?: string;
  start_date?: string;
  end_date?: string;
  provider_id?: string;
}) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    q.set(k, String(v));
  }
  return apiFetch<DistrictTrainingResponse>(`/industry/district-training?${q.toString()}`);
}

// Training priorities (P1.1): deterministic action-prioritization over P0
// evidence. Levels HIGH/MEDIUM/LOW/INSUFFICIENT_EVIDENCE plus an orthogonal
// aligned/actionable_gap/insufficient_evidence status. Aggregate evidence
// packets only — no student-level data, no seat recommendations, no scores.
export type TrainingPriorityEntry = {
  skill: string;
  display_name?: string | null;
  category?: string | null;
  priority: string;
  status: string;
  reasons: string[];
  evidence: {
    market: {
      trend?: string | null;
      skill_share?: number | null;
      posting_count?: number | null;
      match_type?: string | null;
      provider_id?: string | null;
    };
    curriculum: { courses_teaching: number; courses_missing: number };
    learner_supply: {
      learner_count: number;
      verified_learner_count: number;
      verified_coverage?: number | null;
      average_proficiency?: number | null;
    };
    trainer: { trainer_count: number; capacity_status?: string | null };
  };
};

export type TrainingPrioritiesResponse = {
  district: string;
  district_status: string;
  role: string;
  canonical_role?: string | null;
  role_mapping_status: string;
  market_context?: { match_type?: string } | null;
  priorities: TrainingPriorityEntry[];
  summary: Record<string, number>;
  capacity_note: string;
  provenance: Record<string, unknown>;
  note: string;
};

export function getTrainingPriorities(params: {
  district: string;
  role: string;
  state?: string;
  country?: string;
  city?: string;
  region?: string;
  start_date?: string;
  end_date?: string;
  provider_id?: string;
  priority?: string;
}) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    q.set(k, String(v));
  }
  return apiFetch<TrainingPrioritiesResponse>(`/industry/training-priorities?${q.toString()}`);
}

// Curriculum change proposals (P1.2): human-reviewable planning artifacts.
// Every record starts PENDING_REVIEW; generation never mutates curriculum.
export type CurriculumProposalRow = {
  proposal_id: string;
  course_id: string;
  course_name?: string | null;
  institution_name?: string | null;
  district: string;
  role: string;
  skill: { id: string; name: string };
  priority: { level: string; status: string; reasons: string[] };
  action: { type: string; status: string };
  title: string;
  rationale: string[];
  market_context: { match_type?: string | null };
};

export type CurriculumProposalsResponse = {
  district: string;
  role: string;
  market_context?: Record<string, unknown> | null;
  proposals: CurriculumProposalRow[];
  summary: { total: number; by_action: Record<string, number>; high_priority: number };
  provenance: Record<string, unknown>;
  note: string;
};

export function getCurriculumProposals(params: {
  district: string;
  role: string;
  state?: string;
  country?: string;
  city?: string;
  region?: string;
  start_date?: string;
  end_date?: string;
  provider_id?: string;
  course_id?: string;
  skill?: string;
  action_type?: string;
  priority?: string;
  status?: string;
}) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    q.set(k, String(v));
  }
  return apiFetch<CurriculumProposalsResponse>(`/industry/curriculum-proposals?${q.toString()}`);
}

// Proposal reviews (P1.5): append-only human decisions. Approval records a
// decision only — it never mutates curriculum data and is not implementation.
export type ProposalReviewRow = {
  id: string;
  proposal_id: string;
  district: string;
  role: string;
  course_id?: string | null;
  reviewer_id?: string | null;
  from_status?: string | null;
  to_status: string;
  reason?: string | null;
  created_at: string;
};

export function getProposalReviews(params: {
  proposal_id?: string;
  course_id?: string;
  district?: string;
  decision?: string;
} = {}) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    q.set(k, String(v));
  }
  const suffix = q.toString() ? `?${q.toString()}` : "";
  return apiFetch<ProposalReviewRow[]>(`/industry/curriculum-reviews${suffix}`);
}

export function createProposalReview(payload: {
  proposal_id: string;
  district: string;
  role: string;
  decision: string;
  reason?: string;
}) {
  return apiFetch<ProposalReviewRow>("/industry/curriculum-reviews", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// Trainer development signals (P1.3): observed trainer-skill mappings
// projected against teaching context and P1.1 priorities. Aggregate only —
// no trainer identities, no assignment, no plans.
export type TrainerDevelopmentSignalRow = {
  skill: string;
  display_name?: string | null;
  signal: string;
  signal_type: string;
  reasons: string[];
  priority: { level?: string | null; status?: string | null; reasons: string[] };
  trainer_evidence: {
    trainer_count: number;
    institutions_with_skill_trainers: number;
    institutions_teaching: number;
    proficiency_breakdown: Record<string, number>;
  };
  related_proposals: { proposal_id: string; course_id: string; action_type: string; priority: string }[];
};

export type TrainerDevelopmentResponse = {
  district: string;
  district_status: string;
  role: string;
  market_context?: Record<string, unknown> | null;
  signals: TrainerDevelopmentSignalRow[];
  summary: Record<string, number>;
  provenance: Record<string, unknown>;
  note: string;
};

export function getTrainerDevelopmentSignals(params: {
  district: string;
  role: string;
  state?: string;
  country?: string;
  city?: string;
  region?: string;
  start_date?: string;
  end_date?: string;
  provider_id?: string;
  course_id?: string;
  skill?: string;
  signal?: string;
}) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    q.set(k, String(v));
  }
  return apiFetch<TrainerDevelopmentResponse>(`/industry/trainer-development-signals?${q.toString()}`);
}

// Capacity planning signals (P1.4): observed counts plus an explicit
// statement that seat capacity is not measured. No seat, ratio, or
// shortage claims — missing data is never presented as zero capacity.
export type CapacityPlanningRow = {
  skill: string;
  display_name?: string | null;
  priority: string;
  status: string;
  courses_teaching: number;
  institutions_teaching: number;
  institutions_total: number;
  learner_count: number;
  verified_learner_count: number;
  trainers_observed: number;
  market_trend?: string | null;
  capacity_status: string;
  planning_note: string;
};

export type CapacityPlanningResponse = {
  district: string;
  district_status: string;
  role: string;
  market_context?: Record<string, unknown> | null;
  capacity: CapacityPlanningRow[];
  summary: Record<string, number>;
  capacity_evidence_status: string;
  planning_note: string;
  provenance: Record<string, unknown>;
  note: string;
};

export function getCapacityPlanning(params: {
  district: string;
  role: string;
  state?: string;
  country?: string;
  city?: string;
  region?: string;
  start_date?: string;
  end_date?: string;
  provider_id?: string;
  course_id?: string;
  skill?: string;
}) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    q.set(k, String(v));
  }
  return apiFetch<CapacityPlanningResponse>(`/industry/capacity-planning?${q.toString()}`);
}

// Outcome feedback (P1.6): observed employer/placement aggregates with
// periods and limitations. Co-occurrence is reported as co-occurrence —
// causal impact is never claimed. Aggregate only, small samples suppressed.
export type SkillOutcomeRow = {
  skill: string;
  display_name?: string | null;
  signal: string;
  limitation: string;
  sample: {
    feedback_count?: number | null;
    placement_count?: number | null;
    successful_placements?: number | null;
    alignment_count: number;
  };
  employer_feedback: {
    observations: number;
    average_observed_minus_expected?: number | null;
  };
  training_priority?: string | null;
  observed_mismatch: boolean;
};

export type OutcomeFeedbackResponse = {
  district?: string | null;
  role?: string | null;
  observation_period: { start?: string | null; end?: string | null };
  skills: SkillOutcomeRow[];
  summary: Record<string, number>;
  provenance: Record<string, unknown>;
  note: string;
};

export function getOutcomeFeedback(params: {
  district?: string;
  role?: string;
  course_id?: string;
  institution_id?: string;
  skill?: string;
  proposal_id?: string;
  start_date?: string;
  end_date?: string;
} = {}) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    q.set(k, String(v));
  }
  const suffix = q.toString() ? `?${q.toString()}` : "";
  return apiFetch<OutcomeFeedbackResponse>(`/industry/outcome-feedback${suffix}`);
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
