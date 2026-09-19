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

export type CapabilityMatchedSignal = {
  signal: string;
  statement: string;
  source_type: string;
  support: number;
  files: string[];
};

export type CapabilityMissingSignal = {
  signal: string;
  statement: string;
};

export type CapabilityExplanation = {
  summary: string;
  status_reason: string;
  evidence_strength: string;
  matched_signals: CapabilityMatchedSignal[];
  missing_signals: CapabilityMissingSignal[];
};

export type CapabilityItem = {
  id: string;
  title: string;
  summary: string;
  observable_abilities: string[];
  related_skills: string[];
  support: number;
  evidence: CapabilityEvidence[];
  status?: string;
  knowledge_statement?: string;
  capability_explanation?: CapabilityExplanation;
};

export type WhatInauraKnowsArea = {
  capability_id: string;
  capability_title: string;
  statement: string;
  support: number;
  status: string;
};

export type WhatInauraKnows = {
  summary: string;
  demonstrated_areas: WhatInauraKnowsArea[];
  developing_areas: WhatInauraKnowsArea[];
  unverified_areas: WhatInauraKnowsArea[];
  evidence_summary: {
    evidence_count: number;
    source_types: string[];
    implementation_evidence_count: number;
  };
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
  /** Requirement category, e.g. "Frontend" (optional: older backends omit it) */
  category?: string;
  /** Canonical prerequisite skill slugs, e.g. ["javascript", "html_css"] */
  prerequisites?: string[];
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
  what_inaura_knows?: WhatInauraKnows;
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
