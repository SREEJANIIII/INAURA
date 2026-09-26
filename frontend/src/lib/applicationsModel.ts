import type { ApplicationStatus } from "../services/outcomes";

export const STUDENT_TRANSITIONS: Record<ApplicationStatus, ApplicationStatus[]> = {
  saved: ["applied", "withdrawn"],
  applied: ["withdrawn"],
  screening: ["withdrawn"],
  interview: ["withdrawn"],
  offer_received: ["withdrawn"],
  selected: [],
  rejected: [],
  withdrawn: [],
};

export const EMPLOYER_TRANSITIONS: Record<ApplicationStatus, ApplicationStatus[]> = {
  saved: [],
  applied: ["screening", "rejected"],
  screening: ["interview", "rejected"],
  interview: ["offer_received", "selected", "rejected"],
  offer_received: ["selected", "rejected"],
  selected: [],
  rejected: [],
  withdrawn: [],
};

export const TERMINAL_STATUSES = new Set<ApplicationStatus>(["selected", "rejected", "withdrawn"]);

export function isTerminalStatus(status: ApplicationStatus): boolean {
  return TERMINAL_STATUSES.has(status);
}

export function getAllowedStudentTransitions(status: ApplicationStatus): ApplicationStatus[] {
  return STUDENT_TRANSITIONS[status] || [];
}

export function getAllowedEmployerTransitions(status: ApplicationStatus): ApplicationStatus[] {
  return EMPLOYER_TRANSITIONS[status] || [];
}

export function formatStatusLabel(status: string): string {
  if (!status) return "";
  return status
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(" ");
}

export function formatOutcomeLabel(outcome: string | null | undefined): string {
  if (!outcome) return "";
  if (outcome === "declined_offer") return "Declined Offer";
  return outcome.charAt(0).toUpperCase() + outcome.slice(1).toLowerCase();
}
