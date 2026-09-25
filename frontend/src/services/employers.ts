import { apiFetch } from "./api";

export type Employer = {
  id: string;
  name: string;
  description: string | null;
  industry: string | null;
  website: string | null;
  location: string | null;
  contact_email?: string | null;
  status: string;
  created_at: string;
  updated_at: string;
};

export type Member = {
  id: string;
  employer_id: string;
  user_id: string;
  role: string;
  created_at: string;
};

export type Requirement = {
  id: string;
  employer_id: string;
  title: string;
  role_key: string | null;
  location: string | null;
  employment_type: string | null;
  description: string | null;
  experience_min_years: number | null;
  qualification_text: string | null;
  status: string;
  created_at: string;
  updated_at: string;
};

export type RequirementSkill = {
  id: string;
  hiring_requirement_id: string;
  skill_id: string;
  importance: "required" | "preferred";
  required_level: number | null;
  note: string | null;
  created_at: string;
};

export function listEmployers() {
  return apiFetch<Employer[]>("/employers");
}

export function createEmployer(payload: {
  name: string;
  description?: string | null;
  industry?: string | null;
  website?: string | null;
  location?: string | null;
  contact_email?: string | null;
}) {
  return apiFetch<Employer>("/employers", { method: "POST", body: JSON.stringify(payload) });
}

export function getEmployer(id: string) {
  return apiFetch<Employer>(`/employers/${id}`);
}

export function listRequirements(employerId: string) {
  return apiFetch<Requirement[]>(`/employers/${employerId}/requirements`);
}

export function createRequirement(
  employerId: string,
  payload: {
    title: string;
    role_key?: string | null;
    location?: string | null;
    employment_type?: string | null;
    description?: string | null;
    experience_min_years?: number | null;
    qualification_text?: string | null;
  }
) {
  return apiFetch<Requirement>(`/employers/${employerId}/requirements`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function listRequirementSkills(requirementId: string) {
  return apiFetch<RequirementSkill[]>(`/requirements/${requirementId}/skills`);
}

export function setRequirementSkills(
  requirementId: string,
  skills: { skill_id: string; importance: "required" | "preferred"; required_level?: number | null; note?: string | null }[]
) {
  return apiFetch<RequirementSkill[]>(`/requirements/${requirementId}/skills`, {
    method: "PUT",
    body: JSON.stringify({ skills }),
  });
}
