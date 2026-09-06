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
  created_at: string;
  updated_at: string;
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

export type RoadmapGenerateResponse = Roadmap & {
  items: RoadmapItem[];
  milestones: RoadmapMilestone[];
};

export function generateRoadmap(target_role?: string) {
  return apiFetch<RoadmapGenerateResponse>("/roadmap/generate", {
    method: "POST",
    body: JSON.stringify(target_role ? { target_role } : {}),
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
