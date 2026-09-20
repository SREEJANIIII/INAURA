import { apiFetch } from "./api";

export interface AtsSkillMatch {
  skill: string;
  category: string;
  importance: number;
  matched: boolean;
  occurrences: number;
  role_relevance?: string | null;
}

export interface AtsSectionDetail {
  name: string;
  found: boolean;
  importance: "critical" | "important" | "optional" | string;
  description: string;
}

export interface AtsContactCheck {
  has_email: boolean;
  email?: string | null;
  has_phone: boolean;
  phone?: string | null;
  has_linkedin: boolean;
  linkedin_url?: string | null;
  has_github: boolean;
  github_url?: string | null;
  has_portfolio?: boolean;
  portfolio_url?: string | null;
  all_links?: string[];
}

export interface AtsScores {
  overall: number;
  skills_match: number;
  impact_metrics: number;
  sections_structure: number;
  formatting_parseability: number;
}

export interface AtsRecommendation {
  title: string;
  description: string;
  category: "skills" | "impact" | "format" | "sections" | string;
  priority: "high" | "medium" | "low" | string;
}

export interface AtsBulletRewrite {
  original: string;
  improved: string;
  explanation: string;
}

export interface AtsTestResponse {
  filename: string;
  target_role: string;
  word_count: number;
  char_count: number;
  scores: AtsScores;
  grade: string;
  verdict: string;
  summary: string;
  matched_skills: AtsSkillMatch[];
  missing_skills: AtsSkillMatch[];
  extra_skills: string[];
  sections: AtsSectionDetail[];
  contact: AtsContactCheck;
  action_verbs_found: string[];
  metrics_found: string[];
  recommendations: AtsRecommendation[];
  bullet_rewrites: AtsBulletRewrite[];
  parsed_text_preview: string;
  parse_status: string;
  parse_warning?: string | null;
}

export interface AtsRoleOption {
  title: string;
  slug: string;
  category: string;
  description: string;
  benchmark_skills: string[];
}

export interface ExistingResumeOption {
  id: string;
  title: string;
  filename: string;
  created_at?: string;
  file_path?: string;
  has_parsed_text: boolean;
  word_count: number;
}

export async function getAtsRoles(): Promise<AtsRoleOption[]> {
  return apiFetch<AtsRoleOption[]>("/resume/roles");
}

export async function getExistingResumes(): Promise<ExistingResumeOption[]> {
  return apiFetch<ExistingResumeOption[]>("/resume/existing");
}

export async function testResumeAts(formData: FormData): Promise<AtsTestResponse> {
  return apiFetch<AtsTestResponse>("/resume/ats-test", {
    method: "POST",
    body: formData,
  });
}
