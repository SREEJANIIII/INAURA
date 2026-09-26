import { apiFetch } from "./api";

export type ApplicationStatus =
  | "saved"
  | "applied"
  | "screening"
  | "interview"
  | "offer_received"
  | "selected"
  | "rejected"
  | "withdrawn";

export type ApplicationEvent = {
  id: string;
  application_id: string;
  from_status: string | null;
  to_status: string;
  actor: string | null;
  note: string | null;
  created_at: string;
};

export type CandidateProfile = {
  full_name: string;
  college?: string | null;
  degree?: string | null;
  branch?: string | null;
  graduation_year?: number | null;
};

export type CandidateSkillMatch = {
  skill_id: string;
  skill_name?: string | null;
  importance?: string | null;
  required_level?: number | null;
  observed_level?: number | null;
  status?: "met" | "gap" | "unassessed" | string | null;
};

export type CandidateEvidenceItem = {
  id: string;
  type: string;
  title?: string | null;
  url?: string | null;
  description?: string | null;
};

export type Application = {
  id: string;
  student_id: string;
  hiring_requirement_id: string;
  employer_id?: string | null;
  status: ApplicationStatus;
  outcome: string | null;
  outcome_decided_at: string | null;
  applied_at: string | null;
  created_at: string;
  updated_at: string;
  requirement_title?: string | null;
  employer_name?: string | null;
  candidate_name?: string | null;
};

export type ApplicationDetail = Application & {
  events: ApplicationEvent[];
  candidate_profile?: CandidateProfile | null;
  candidate_skills?: CandidateSkillMatch[];
  candidate_evidence?: CandidateEvidenceItem[];
};


export type SkillFeedback = {
  id: string;
  employer_feedback_id: string;
  skill_id: string;
  skill_name?: string | null;
  expected_level: number | null;
  observed_level: number | null;
  skill_gap: number | null;
  comment: string | null;
  created_at: string;
};

export type EmployerFeedback = {
  id: string;
  employer_id: string;
  application_id: string;
  student_id: string;
  technical_ability: number | null;
  communication: number | null;
  problem_solving: number | null;
  project_readiness: number | null;
  role_readiness: number | null;
  overall_rating: number | null;
  interview_summary: string | null;
  overall_comment: string | null;
  status: string;
  created_at: string;
  updated_at: string;
  skills: SkillFeedback[];
};

export type Placement = {
  id: string;
  student_id: string;
  employer_id: string;
  application_id: string | null;
  role_title: string;
  location: string | null;
  joining_date: string | null;
  status: string;
  outcome_source: string;
  verification_status: string;
  created_at: string;
  updated_at: string;
  employer_name?: string | null;
  requirement_title?: string | null;
};

export type Alignment = {
  id: string;
  hiring_requirement_id: string;
  course_name: string;
  qualification_name: string | null;
  skill_id: string | null;
  coverage: number | null;
  evidence_note: string | null;
  evidence_id: string | null;
  certification_id: string | null;
  created_at: string;
  updated_at: string;
};

export type Dashboard = {
  funnel: Record<string, number>;
  rates: {
    interview_rate: number;
    offer_rate: number;
    selection_rate: number;
    joining_rate_selection_base: number;
    joining_rate_application_base: number;
  };
  denominators: { applied_n: number; selected_n: number };
  top_required_skills: { skill_id: string; count: number }[];
  top_observed_gaps: { skill_id: string; avg_gap: number; feedback_count: number }[];
  unlinked_placements_n: number;
  window: { from: string | null; to: string | null };
};

export function createApplication(
  hiring_requirement_id: string,
  optionsOrStatus?: "saved" | "applied" | { initial_status?: "saved" | "applied"; note?: string },
  noteParam?: string
) {
  let initial_status: "saved" | "applied" = "applied";
  let note: string | undefined = undefined;
  if (typeof optionsOrStatus === "string") {
    initial_status = optionsOrStatus;
    note = noteParam;
  } else if (typeof optionsOrStatus === "object" && optionsOrStatus !== null) {
    if (optionsOrStatus.initial_status) initial_status = optionsOrStatus.initial_status;
    note = optionsOrStatus.note;
  }
  return apiFetch<Application>("/outcomes/applications", {
    method: "POST",
    body: JSON.stringify({ hiring_requirement_id, initial_status, note }),
  });
}

export type OpenRoleSkill = {
  skill_id: string;
  skill_name?: string | null;
  importance?: string | null;
  required_level?: number | null;
};

export type OpenRole = {
  id: string;
  title: string;
  role_key?: string | null;
  employer_id: string;
  employer_name?: string | null;
  location?: string | null;
  employment_type?: string | null;
  description?: string | null;
  created_at?: string | null;
  skills: OpenRoleSkill[];
  application?: { id: string; status: ApplicationStatus } | null;
};

export function listOpenRoles(search?: string) {
  return apiFetch<OpenRole[]>("/outcomes/open-roles", {
    params: search?.trim() ? { search: search.trim() } : undefined,
  });
}

export function listApplications(status?: string) {
  return apiFetch<Application[]>("/outcomes/applications", {
    params: status ? { status } : undefined,
  });
}

export function listApplicationsForEmployer(employerId: string) {
  return apiFetch<Application[]>(`/outcomes/employers/${employerId}/applications`);
}

export function listApplicationsForRequirement(requirementId: string) {
  return apiFetch<Application[]>(`/requirements/${requirementId}/applications`);
}

export function getApplication(id: string) {
  return apiFetch<ApplicationDetail>(`/outcomes/applications/${id}`);
}


export function transitionApplication(id: string, to_status: ApplicationStatus, note?: string) {
  return apiFetch<Application>(`/outcomes/applications/${id}/status`, {
    method: "PATCH",
    body: JSON.stringify({ to_status, note: note ?? null }),
  });
}

export function getFeedback(appId: string) {
  return apiFetch<EmployerFeedback>(`/outcomes/applications/${appId}/feedback`);
}

export function submitFeedback(
  appId: string,
  payload: {
    technical_ability?: number | null;
    communication?: number | null;
    problem_solving?: number | null;
    project_readiness?: number | null;
    role_readiness?: number | null;
    overall_rating?: number | null;
    interview_summary?: string | null;
    overall_comment?: string | null;
    skills?: {
      skill_id: string;
      expected_level?: number | null;
      observed_level?: number | null;
      comment?: string | null;
    }[];
  }
) {
  return apiFetch<EmployerFeedback>(`/outcomes/applications/${appId}/feedback`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function listPlacements() {
  return apiFetch<Placement[]>("/outcomes/placements");
}

export function listPlacementsForEmployer(employerId: string) {
  return apiFetch<Placement[]>(`/outcomes/employers/${employerId}/placements`);
}

export function getPlacement(id: string) {
  return apiFetch<Placement>(`/outcomes/placements/${id}`);
}

export function createPlacement(payload: {
  employer_id?: string | null;
  application_id?: string | null;
  role_title: string;
  location?: string | null;
  joining_date?: string | null;
  status?: string;
}) {
  return apiFetch<Placement>("/outcomes/placements", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updatePlacement(
  placementId: string,
  payload: {
    role_title?: string;
    location?: string | null;
    joining_date?: string | null;
    status?: string;
  }
) {
  return apiFetch<Placement>(`/outcomes/placements/${placementId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function confirmPlacement(placementId: string, verified: boolean = true) {
  return apiFetch<Placement>(`/outcomes/placements/${placementId}/confirm?verified=${verified}`, {
    method: "POST",
  });
}

export function listAlignments(hiring_requirement_id?: string) {
  return apiFetch<Alignment[]>("/outcomes/alignments", {
    params: hiring_requirement_id ? { hiring_requirement_id } : undefined,
  });
}

export function createAlignment(payload: {
  hiring_requirement_id: string;
  course_name: string;
  qualification_name?: string | null;
  skill_id?: string | null;
  coverage?: number | null;
  evidence_note?: string | null;
  evidence_id?: string | null;
  certification_id?: string | null;
}) {
  return apiFetch<Alignment>("/outcomes/alignments", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getDashboard(employer_id?: string) {
  return apiFetch<Dashboard>("/outcomes/dashboard", {
    params: employer_id ? { employer_id } : undefined,
  });
}
