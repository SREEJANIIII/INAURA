import { apiFetch } from "./api";

export type Roadmap = {
  id: string;
  user_id: string;
  analysis_result_id: string;
  target_role: string;
  title: string;
  status: "active" | "completed" | "archived";
  engine_version: string;
  total_estimated_hours: number;
  estimated_weeks: number;
  progress?: number;
  hours_per_week?: number;
  weekly_hours_budget?: number;
  evidence_snapshot_id?: string | null;
  total_weeks?: number;
  current_week_index?: number;
  adaptive_rebalance_count?: number;
  last_rebalanced_at?: string | null;
  weeks?: RoadmapWeek[];
  items?: RoadmapItem[];
  milestones?: RoadmapMilestone[];
  skill_explanations?: SkillPersonalizationExplanation[];
  created_at?: string | null;
  updated_at?: string | null;
};

export type SkillPersonalizationExplanation = {
  skill_name: string;
  canonical_name: string;
  skill_slug: string;
  current_proficiency: number;
  current_proficiency_pct: number;
  required_level: number;
  required_level_pct: number;
  gap_pct: number;
  confidence: number;
  confidence_pct: number;
  confidence_rationale: string;
  demonstrated_capabilities: string[];
  missing_capabilities: string[];
  supporting_evidence: string[];
  prerequisites_required: string[];
  prerequisites_status: string;
  target_role: string;
  importance_pct: number;
  demand_pct: number;
  interview_relevance_pct: number;
  priority_score: number;
  allocated_hours: number;
  weekly_hours_budget: number;
  weekly_pacing: string;
  smallest_learning_unit: string;
  validation_criteria: string;
  five_whys: {
    why_learning: string;
    why_now: string;
    why_time: string;
    why_resource: string;
    how_validated: string;
  };
  readable_summary: string;
};

export type RoadmapResource = {
  id: string;
  roadmap_item_id: string;
  title: string;
  resource_type: "course" | "documentation" | "tutorial" | "article" | "video" | "practice" | "project_reference";
  url: string;
  provider: string | null;
  difficulty: string | null;
  estimated_hours: number | null;
  is_free: boolean;
  description: string;
  created_at: string;
};

export type RoadmapItem = {
  id: string;
  roadmap_id: string;
  skill_id: string;
  skill_gap_id: string | null;
  title: string;
  description: string;
  item_type: "learn" | "practice" | "project" | "assessment";
  priority: number;
  estimated_hours: number;
  sequence_order: number;
  status: "not_started" | "in_progress" | "completed";
  completion_percentage: number;
  why_it_matters: string;
  personalization_explanation?: SkillPersonalizationExplanation;
  created_at: string;
  updated_at: string;
  skills?: { canonical_name: string; display_name: string; category: string };
  roadmap_resources?: RoadmapResource[];
};

export type RoadmapMilestone = {
  id: string;
  roadmap_id: string;
  title: string;
  description: string;
  sequence_order: number;
  target_hours: number;
  status: "not_started" | "in_progress" | "completed";
  created_at: string;
  updated_at: string;
};

export type RoadmapTask = {
  id: string;
  roadmap_week_id: string;
  skill_slug: string;
  skill_name: string;
  task_type: "learn" | "practice" | "build" | "validate";
  title: string;
  description: string;
  estimated_minutes: number;
  sequence_order: number;
  status: "not_started" | "in_progress" | "completed" | "skipped";
  completion_percentage: number;
  resources: Array<{
    title: string;
    url: string;
    type?: string;
    provider?: string;
    is_free?: boolean;
    estimated_minutes?: number;
  }>;
  validation_method: string;
  evidence_generated?: Record<string, unknown> | null;
  why_this_task: string;
  personalization_context?: Record<string, unknown> | null;
  completed_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type RoadmapWeek = {
  id: string;
  roadmap_id: string;
  week_number: number;
  title: string;
  objective: string;
  estimated_hours: number;
  skills: string[];
  status: "locked" | "current" | "completed" | "behind_schedule";
  completion_percentage: number;
  tasks?: RoadmapTask[];
  start_date?: string | null;
  target_completion_date?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type EvidenceSourceAudit = {
  source: string;
  status?: string;
  url?: string | null;
  user?: string | null;
  handle?: string | null;
  title?: string | null;
  count?: number;
  repos_inspected?: number;
};

export type LearnerSkillStateSnapshot = {
  user_id: string;
  skill_slug: string;
  skill_name: string;
  state_classification: "KNOWN" | "INFERRED" | "UNKNOWN";
  proficiency: number;
  confidence: number;
  required_level: number;
  gap: number;
  evidence_coverage: number;
  evidence_strength: number;
  evidence_count: number;
  evidence_depth: number;
  evidence_recency_days: number | null;
  active_sources: string[];
  evidence_ids: string[];
  reasoning: string;
  last_evaluated_at: string;
};

export type EvidenceSnapshot = {
  id: string;
  user_id: string;
  analysis_result_id: string | null;
  sources_analyzed: EvidenceSourceAudit[];
  sources_available: string[];
  sources_unavailable: string[];
  learner_skill_states: Record<string, LearnerSkillStateSnapshot>;
  engine_version: string;
  created_at: string;
};

export type EvidenceSummary = {
  user_id: string;
  sources_analyzed: EvidenceSourceAudit[];
  sources_available: string[];
  sources_unavailable: string[];
  latest_snapshot: EvidenceSnapshot | null;
};

export type RoadmapGenerateResponse = Roadmap & {
  items: RoadmapItem[];
  milestones: RoadmapMilestone[];
  weeks?: RoadmapWeek[];
};

export function generateRoadmap(target_role?: string, hours_per_week?: number) {
  return apiFetch<RoadmapGenerateResponse>("/roadmap/generate", {
    method: "POST",
    body: JSON.stringify({
      target_role: target_role || undefined,
      hours_per_week: hours_per_week || undefined,
    }),
  });
}

export function getLatestRoadmap() {
  return apiFetch<Roadmap>("/roadmap/latest");
}

export function getRoadmapItems() {
  return apiFetch<RoadmapItem[]>("/roadmap/items");
}

export function getRoadmapMilestones() {
  return apiFetch<RoadmapMilestone[]>("/roadmap/milestones");
}

export function updateRoadmapItem(itemId: string, payload: { status?: RoadmapItem["status"]; completion_percentage?: number }) {
  return apiFetch<RoadmapItem>(`/roadmap/items/${itemId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function getRoadmapWeeks(roadmapId?: string) {
  const query = roadmapId ? `?roadmap_id=${encodeURIComponent(roadmapId)}` : "";
  return apiFetch<RoadmapWeek[]>(`/roadmap/weeks${query}`);
}

export function getRoadmapWeek(weekId: string) {
  return apiFetch<RoadmapWeek>(`/roadmap/weeks/${weekId}`);
}

export function getRoadmapTasks(weekId?: string) {
  const query = weekId ? `?week_id=${encodeURIComponent(weekId)}` : "";
  return apiFetch<RoadmapTask[]>(`/roadmap/tasks${query}`);
}

export function updateRoadmapTask(
  taskId: string,
  payload: {
    status?: RoadmapTask["status"];
    completion_percentage?: number;
    submission_url?: string;
    submission_notes?: string;
    quiz_score?: number;
  }
) {
  return apiFetch<RoadmapTask>(`/roadmap/tasks/${taskId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function reassessRoadmap(payload?: {
  target_role?: string;
  adjust_hours_per_week?: number;
  mode?: "compress" | "extend_timeline";
}) {
  return apiFetch<Roadmap>("/roadmap/reassess", {
    method: "POST",
    body: JSON.stringify(payload || {}),
  });
}

export function getEvidenceSummary() {
  return apiFetch<EvidenceSummary>("/analysis/evidence-summary");
}
