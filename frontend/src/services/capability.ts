import { apiFetch } from "./api";

export type CapabilityEvidence = {
  provider: string;
  repository: string;
  files: string[];
  depth: number;
  reason: string;
};

export type IndustryExpectation = {
  capability_id: string;
  title: string;
  detail: string;
  relevance: string[];
};

export type CapabilityItem = {
  id: string;
  title: string;
  summary: string;
  observable_abilities: string[];
  related_skills: string[];
  support: number;
  evidence: CapabilityEvidence[];
};

export type DemonstratedCapability = {
  id: string;
  title: string;
  support: number;
  confidence: number;
  evidence: CapabilityEvidence[];
};

export type CapabilityResource = {
  title: string;
  url: string;
  provider: string;
};

export type MissingCapability = {
  id: string;
  title: string;
  support: number;
  status: string;
  priority: number;
  priority_category: string;
  next_actions: string[];
  resources: CapabilityResource[];
  evidence: CapabilityEvidence[];
};

export type RequirementProvenance = {
  source: string;
  source_url: string | null;
  source_quality: number | null;
  evidence_strength: string;
  required_level: number;
  importance: number;
  role_relevance: string;
  evidence_context: string;
  supporting_chunks: Array<{
    chunk_id: string | null;
    role: string | null;
    topic: string | null;
    source: string | null;
    source_url: string | null;
  }>;
};

export type SkillCapability = {
  skill: string;
  slug: string;
  role: string;
  proficiency: number;
  confidence: number;
  required_level: number;
  importance: number;
  status: string;
  priority: number;
  priority_category: string;
  industry_expectations: IndustryExpectation[];
  capabilities: CapabilityItem[];
  demonstrated_capabilities: DemonstratedCapability[];
  missing_capabilities: MissingCapability[];
  evidence_gap: string[];
  skill_gap: string[];
  evidence_sources: CapabilityEvidence[];
  requirement: RequirementProvenance;
  explanation: string;
};

export type CapabilityMap = {
  role: string;
  generated_at: string;
  capability_model_version: string;
  engine_version: string;
  skills: SkillCapability[];
  summary: {
    total_skills: number;
    by_status: Record<string, number>;
  };
};

export function getCapabilityMap(payload: { target_role?: string; skill?: string }) {
  return apiFetch<CapabilityMap>("/analysis/capability-map", {
    params: {
      ...(payload.target_role ? { target_role: payload.target_role } : {}),
      ...(payload.skill ? { skill: payload.skill } : {}),
    },
  });
}
