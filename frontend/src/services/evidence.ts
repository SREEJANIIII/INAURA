import { apiFetch } from "./api";

export type EvidenceType =
  | "github"
  | "leetcode"
  | "codeforces"
  | "kaggle"
  | "linkedin"
  | "resume"
  | "syllabus"
  | "certification_file"
  | "project_doc";

export type VerificationStatus = "unverified" | "verified" | "failed";

export type Evidence = {
  id: string;
  user_id: string;
  evidence_type: EvidenceType;
  source_url: string | null;
  file_path: string | null;
  title: string | null;
  metadata: Record<string, unknown> | null;
  verification_status?: VerificationStatus;
  verification_message?: string | null;
  verified_at?: string | null;
  provider?: string | null;
  created_at: string;
  updated_at: string;
};

export type EvidenceVerificationResponse = Evidence & {
  detected_skills?: string[];
};

export type Project = {
  id: string;
  user_id: string;
  name: string;
  description: string;
  technologies: string[];
  project_url: string | null;
  github_url: string | null;
  created_at: string;
  updated_at: string;
};

export type Certification = {
  id: string;
  user_id: string;
  name: string;
  issuing_org: string;
  completion_year: number;
  certificate_url: string | null;
  created_at: string;
  updated_at: string;
};

export type EvidenceSummary = {
  total_sources: number;
  provided: number;
  evidence: Evidence[];
  projects: Project[];
  certifications: Certification[];
};

// Generic evidence
export function listEvidence() {
  return apiFetch<Evidence[]>("/evidence");
}

export function createEvidence(payload: {
  evidence_type: EvidenceType;
  source_url?: string | null;
  file_path?: string | null;
  title?: string | null;
  metadata?: Record<string, unknown> | null;
}) {
  return apiFetch<Evidence>("/evidence", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateEvidence(
  id: string,
  payload: Partial<{ source_url: string | null; file_path: string | null; title: string | null; metadata: Record<string, unknown> | null }>
) {
  return apiFetch<Evidence>(`/evidence/${id}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function deleteEvidence(id: string) {
  return apiFetch<void>(`/evidence/${id}`, { method: "DELETE" });
}

export function uploadEvidenceFile(form: FormData) {
  return apiFetch<Evidence>("/evidence/upload", {
    method: "POST",
    body: form,
  });
}

export function verifyEvidence(id: string) {
  return apiFetch<EvidenceVerificationResponse>(`/evidence/${id}/verify`, {
    method: "POST",
  });
}

// Projects
export function listProjects() {
  return apiFetch<Project[]>("/evidence/projects");
}

export function createProject(payload: {
  name: string;
  description: string;
  technologies: string[];
  project_url?: string | null;
  github_url?: string | null;
}) {
  return apiFetch<Project>("/evidence/projects", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function deleteProject(id: string) {
  return apiFetch<void>(`/evidence/projects/${id}`, { method: "DELETE" });
}

// Certifications
export function listCerts() {
  return apiFetch<Certification[]>("/evidence/certifications");
}

export function createCert(payload: {
  name: string;
  issuing_org: string;
  completion_year: number;
  certificate_url?: string | null;
}) {
  return apiFetch<Certification>("/evidence/certifications", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function deleteCert(id: string) {
  return apiFetch<void>(`/evidence/certifications/${id}`, { method: "DELETE" });
}

// Summary
export function getEvidenceSummary() {
  return apiFetch<EvidenceSummary>("/evidence/summary");
}
