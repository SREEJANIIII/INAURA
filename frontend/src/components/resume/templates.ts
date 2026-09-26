/**
 * Single source of truth for resume template metadata.
 *
 * Templates are presentation-only: every template renders the same canonical
 * ResumeData. No template generates, parses, filters, or mutates content,
 * and no template calls backend APIs.
 */

export type ResumeTemplateId = "classic-ats" | "modern-engineering" | "academic-cv";

export type ResumeTemplateMeta = {
  id: ResumeTemplateId;
  name: string;
  description: string;
};

export const TEMPLATES: ResumeTemplateMeta[] = [
  {
    id: "classic-ats",
    name: "Classic ATS",
    description: "Clean, conservative, ATS-friendly",
  },
  {
    id: "modern-engineering",
    name: "Modern Engineering",
    description: "Modern software-engineering layout",
  },
  {
    id: "academic-cv",
    name: "Academic CV",
    description: "Dense technical and academic layout",
  },
];

export const DEFAULT_TEMPLATE: ResumeTemplateId = "classic-ats";

export function isResumeTemplateId(value: unknown): value is ResumeTemplateId {
  return (
    value === "classic-ats" || value === "modern-engineering" || value === "academic-cv"
  );
}

export function templateName(id: ResumeTemplateId): string {
  return TEMPLATES.find((t) => t.id === id)?.name ?? "Classic ATS";
}

/**
 * Map the backend resume `template` field (classic | modern | minimal) to a
 * visual template. Unknown values fall back to Classic ATS.
 */
export function mapBackendTemplate(value: unknown): ResumeTemplateId {
  if (value === "modern") return "modern-engineering";
  if (value === "minimal") return "academic-cv";
  return "classic-ats";
}

const STORAGE_PREFIX = "inaura:resume-template:";

export function loadStoredTemplate(resumeId: string): ResumeTemplateId | null {
  try {
    const stored = localStorage.getItem(`${STORAGE_PREFIX}${resumeId}`);
    return isResumeTemplateId(stored) ? stored : null;
  } catch {
    return null;
  }
}

export function storeTemplate(resumeId: string, id: ResumeTemplateId): void {
  try {
    localStorage.setItem(`${STORAGE_PREFIX}${resumeId}`, id);
  } catch {
    /* storage unavailable (private mode, etc.) — selection stays in memory */
  }
}
