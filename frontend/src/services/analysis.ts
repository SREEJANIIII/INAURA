import { apiFetch } from "./api";

export type TopicCoverageGap = {
  pillar: string;
  skill: string;
  status: string;
  solved: number;
  gap_type: string;
  priority_category: string;
  importance: number;
  explanation: string;
  actionable_advice: string;
};

export type StrengthItem = {
  skill: string;
  display_name: string;
  category: string;
  proficiency: number;
  confidence: number;
  required_level: number;
  evidence_count: number;
  explanation: string;
  quadrant: string;
  quadrant_title: string;
};

export type AnalysisResult = {
  id: string;
  user_id: string;
  target_role: string;
  readiness_score: number;
  skill_component: number;
  industry_component: number;
  evidence_component: number;
  readiness_explanation?: string;
  disclaimer?: string;
  assessment_count: number;
  gap_count: number;
  engine_version: string;
  created_at: string;
  updated_at: string;
  metadata?: {
    strengths_count?: number;
    priority_breakdown?: Record<string, number>;
    topic_gaps_count?: number;
  };
};

export type SkillAssessment = {
  id: string;
  user_id: string;
  skill_id: string;
  proficiency: number;
  confidence: number;
  evidence_weight: number;
  source_diversity: number;
  evidence_count: number;
  explanation: string;
  created_at: string;
  updated_at: string;
  skills?: { canonical_name: string; display_name: string; category: string };
};

export type SkillGap = {
  id: string;
  user_id: string;
  analysis_result_id: string;
  skill_id: string;
  target_role: string;
  required_level: number;
  current_proficiency: number;
  confidence: number;
  gap: number;
  importance: number;
  demand: number;
  interview_relevance: number;
  industry_confidence?: number;
  priority_score: number;
  priority?: number;
  priority_category?: "critical" | "high" | "medium" | "low" | "covered" | string;
  gap_type?: "skill_gap" | "evidence_gap" | "coverage_gap" | "industry_data_gap" | string;
  actionable_advice?: string;
  evidence_context?: string;
  source?: string;
  quadrant?: string;
  quadrant_title?: string;
  explanation: string;
  created_at: string;
  skills?: { canonical_name: string; display_name: string; category: string };
};

export function runAnalysis(target_role?: string) {
  return apiFetch<{
    id: string;
    user_id: string;
    target_role: string;
    readiness_score: number;
    skill_component: number;
    industry_component: number;
    evidence_component: number;
    readiness_explanation: string;
    assessment_count: number;
    gap_count: number;
    engine_version: string;
    assessments: Array<{
      skill: string;
      proficiency: number;
      confidence: number;
      required_level: number;
      gap: number;
      importance: number;
      demand: number;
      interview_relevance: number;
      priority: number;
      evidence_count: number;
      source_diversity: number;
      explanation: string;
    }>;
    gaps: Array<{
      canonical_name: string;
      required_level: number;
      current_proficiency: number;
      confidence: number;
      gap: number;
      importance: number;
      demand: number;
      interview: number;
      priority: number;
      explanation: string;
    }>;
    created_at: string;
  }>("/analysis/run", {
    method: "POST",
    body: JSON.stringify(target_role ? { target_role } : {}),
  });
}

export function getLatestAnalysis() {
  return apiFetch<AnalysisResult>("/analysis/latest");
}

export function getSkills() {
  return apiFetch<SkillAssessment[]>("/analysis/skills");
}

export function getGaps() {
  return apiFetch<SkillGap[]>("/analysis/gaps");
}
