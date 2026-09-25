/**
 * Keeps the analysis and the roadmap in step with the target role.
 *
 * A roadmap is built from one analysis, and an analysis is run against one role,
 * so changing your career leaves both behind unless they're redone. Changing it
 * on Career Track starts that here, in the background: the analysis is re-run for
 * the new role and a fresh roadmap is built from it. Pages read the progress from
 * this store so they can say what's happening instead of showing the old plan.
 *
 * The same runner also refreshes an analysis whose evidence changed since it ran
 * ("refresh"): only the analysis is re-run, so the roadmap and its ticked tasks stay.
 */
import { runAnalysis } from "../services/analysis";
import { generateRoadmap } from "../services/roadmap";
import { capabilityMapData, profileData, resultsPageData, roadmapPageData } from "./pageData";

export type RoleSyncStage = "idle" | "analysing" | "building" | "done" | "failed";

/** "role": a new career was chosen. "refresh": same career, the analysis was out of date. */
export type RoleSyncReason = "role" | "refresh";

export type RoleSyncState = {
  stage: RoleSyncStage;
  /** The role being caught up to. */
  role: string | null;
  reason: RoleSyncReason;
  /** Something worth telling the user beyond the stage itself. */
  message: string | null;
};

const IDLE: RoleSyncState = { stage: "idle", role: null, reason: "role", message: null };

let state: RoleSyncState = IDLE;
const listeners = new Set<() => void>();

function set(next: RoleSyncState) {
  state = next;
  listeners.forEach((listener) => listener());
}

export function subscribeRoleSync(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function getRoleSync() {
  return state;
}

/** Clear a finished notice — e.g. the user dismissed it, or logged out. */
export function resetRoleSync() {
  if (state !== IDLE) set(IDLE);
}

const messageOf = (error: unknown) => (error instanceof Error ? error.message : "");

function analysisProblem(error: unknown, reason: RoleSyncReason) {
  const message = messageOf(error);
  const lower = message.toLowerCase();
  const lead = reason === "role" ? "Your role was changed, but" : "Your analysis couldn’t be re-run:";
  if (lower.includes("no evidence") || lower.includes("evidence source")) {
    return `${lead} there’s no evidence to analyse yet. Add your evidence, then run your analysis.`;
  }
  if (lower.includes("profile not found")) {
    return `${lead} your profile isn’t finished. Complete it, then run your analysis.`;
  }
  if (message.includes("401")) return `${lead} your session expired. Log in again and run your analysis.`;
  return reason === "role"
    ? "Your role was changed, but your analysis couldn’t be re-run. Open Evidence and run it yourself."
    : "Your analysis couldn’t be re-run just now. Try again, or run it from Evidence.";
}

function roadmapProblem(error: unknown) {
  const message = messageOf(error);
  const lower = message.toLowerCase();
  // Not really a failure: there's nothing to plan because you already meet the role
  if (lower.includes("no priority gaps") || lower.includes("meeting the assessed requirements")) {
    return null;
  }
  if (lower.includes("hours")) {
    return "Your analysis is up to date, but a plan needs your weekly hours. Set them in your profile, then build your roadmap.";
  }
  return "Your analysis is up to date, but the new roadmap couldn’t be built. Open Roadmap and try again.";
}

let running = false;
let queued: { role: string; reason: RoleSyncReason } | null = null;

/**
 * Catch the analysis and roadmap up to `role`. Safe to call repeatedly: one runs at
 * a time, and a role chosen while another is running is picked up straight after.
 */
export function rebuildForRole(role: string) {
  queued = { role, reason: "role" };
  if (!running) void drain();
}

/** Re-run the analysis for the current role (e.g. evidence changed); the roadmap is left as it is. */
export function refreshAnalysis(role: string) {
  // A career change already waiting re-runs the analysis anyway
  if (queued?.reason !== "role") queued = { role, reason: "refresh" };
  if (!running) void drain();
}

async function drain() {
  running = true;
  try {
    while (queued) {
      const { role, reason } = queued;
      queued = null;
      await rebuild(role, reason);
    }
  } finally {
    running = false;
  }
}

async function rebuild(role: string, reason: RoleSyncReason) {
  set({ stage: "analysing", role, reason, message: null });
  try {
    await runAnalysis(role);
    await resultsPageData.fetch(true);
    // The career track's skills and readiness are built from this analysis, so reload them too
    capabilityMapData(role).fetch(true).catch(() => undefined);
  } catch (error) {
    set({ stage: "failed", role, reason, message: analysisProblem(error, reason) });
    return;
  }

  if (reason === "refresh") {
    set({ stage: "done", role, reason, message: null });
    return;
  }

  set({ stage: "building", role, reason, message: null });
  try {
    const profile = profileData.peek() ?? (await profileData.fetch().catch(() => null));
    await generateRoadmap(role, profile?.hours_per_week);
    await roadmapPageData.fetch(true);
    set({ stage: "done", role, reason, message: null });
  } catch (error) {
    const problem = roadmapProblem(error);
    // The old plan is left untouched when generating fails, so reload whatever is there
    await roadmapPageData.fetch(true).catch(() => undefined);
    if (problem === null) {
      set({
        stage: "done",
        role,
        reason,
        message: `You already meet the assessed requirements for ${role}, so there’s nothing to plan yet.`,
      });
    } else {
      set({ stage: "failed", role, reason, message: problem });
    }
  }
}
