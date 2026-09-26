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

export type TimelineEvent = {
  to_status: string;
  created_at: string;
};

export type TimelineStage = {
  key: string;
  label: string;
  at?: string;
  done: boolean;
};

const TIMELINE_STAGES: ApplicationStatus[] = [
  "applied",
  "screening",
  "interview",
  "offer_received",
  "selected",
];

/**
 * Derive career-timeline stages from immutable application_events.
 * Pure derivation — no dates or events are fabricated; unreached stages
 * stay pending. The optional joining date comes from a placement record.
 */
export function deriveTimeline(
  events: TimelineEvent[],
  joiningDate?: string | null,
  joined = false
): TimelineStage[] {
  const reached = new Set((events ?? []).map((e) => e.to_status));
  const dateFor = (stage: string) => events.find((e) => e.to_status === stage)?.created_at;
  const stages: TimelineStage[] = TIMELINE_STAGES.map((s) => ({
    key: s,
    label: formatStatusLabel(s),
    at: dateFor(s),
    done: reached.has(s),
  }));
  stages.push({
    key: "joined",
    label: "Joining",
    at: joiningDate || undefined,
    done: joined,
  });
  return stages;
}
