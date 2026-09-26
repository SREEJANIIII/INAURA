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

export type CanonicalSkill = {
  id: string;
  canonical_name: string;
  display_name: string;
  category?: string | null;
};

export type RequirementSkill = {
  id: string;
  hiring_requirement_id: string;
  skill_id: string;
  importance: "required" | "preferred";
  required_level: number | null;
  note: string | null;
  created_at: string;
  skill_name?: string | null;
  skill_category?: string | null;
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

export function updateEmployer(
  employerId: string,
  payload: {
    name?: string;
    description?: string | null;
    industry?: string | null;
    website?: string | null;
    location?: string | null;
    contact_email?: string | null;
    status?: "active" | "suspended" | "archived";
  }
) {
  return apiFetch<Employer>(`/employers/${employerId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function deleteEmployer(employerId: string) {
  return apiFetch<void>(`/employers/${employerId}`, { method: "DELETE" });
}

export function listMembers(employerId: string) {
  return apiFetch<Member[]>(`/employers/${employerId}/members`);
}

export function addMember(employerId: string, payload: { user_id: string; role?: "owner" | "member" }) {
  return apiFetch<Member>(`/employers/${employerId}/members`, {
    method: "POST",
    body: JSON.stringify({ role: "member", ...payload }),
  });
}

export function removeMember(employerId: string, targetUserId: string) {
  return apiFetch<void>(`/employers/${employerId}/members/${targetUserId}`, {
    method: "DELETE",
  });
}

export function listRequirements(employerId: string) {
  return apiFetch<Requirement[]>(`/employers/${employerId}/requirements`);
}

export function getRequirement(requirementId: string) {
  return apiFetch<Requirement>(`/requirements/${requirementId}`);
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

export function updateRequirement(
  requirementId: string,
  payload: {
    title?: string;
    role_key?: string | null;
    location?: string | null;
    employment_type?: string | null;
    description?: string | null;
    experience_min_years?: number | null;
    qualification_text?: string | null;
    status?: "draft" | "open" | "paused" | "closed";
  }
) {
  return apiFetch<Requirement>(`/requirements/${requirementId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function deleteRequirement(requirementId: string) {
  return apiFetch<void>(`/requirements/${requirementId}`, { method: "DELETE" });
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

export function listCanonicalSkills() {
  return apiFetch<CanonicalSkill[]>("/employers/skills/catalog");
}

