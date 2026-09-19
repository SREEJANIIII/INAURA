/**
 * Keeps the analysis and the roadmap in step with the target role.
 *
 * A roadmap is built from one analysis, and an analysis is run against one role,
 * so changing your career leaves both behind unless they're redone. Changing it
 * on Career Track starts that here, in the background: the analysis is re-run for
 * the new role and a fresh roadmap is built from it. Pages read the progress from
 * this store so they can say what's happening instead of showing the old plan.
 */
import { runAnalysis } from "../services/analysis";
import { generateRoadmap } from "../services/roadmap";
import { profileData, resultsPageData, roadmapPageData } from "./pageData";

export type RoleSyncStage = "idle" | "analysing" | "building" | "done" | "failed";

export type RoleSyncState = {
  stage: RoleSyncStage;
  /** The role being caught up to. */
  role: string | null;
  /** Something worth telling the user beyond the stage itself. */
  message: string | null;
};

const IDLE: RoleSyncState = { stage: "idle", role: null, message: null };

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

function analysisProblem(error: unknown) {
  const message = messageOf(error);
  const lower = message.toLowerCase();
  if (lower.includes("no evidence") || lower.includes("evidence source")) {
    return "Your role was changed, but there’s no evidence to analyse yet. Add your evidence, then run your analysis.";
  }
  if (lower.includes("profile not found")) {
    return "Your role was changed, but your profile isn’t finished. Complete it, then run your analysis.";
  }
  if (message.includes("401")) return "Your role was changed, but your session expired. Log in again and run your analysis.";
  return "Your role was changed, but your analysis couldn’t be re-run. Open Evidence and run it yourself.";
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
let queued: string | null = null;

/**
 * Catch the analysis and roadmap up to `role`. Safe to call repeatedly: one runs at
 * a time, and a role chosen while another is running is picked up straight after.
 */
export function rebuildForRole(role: string) {
  queued = role;
  if (!running) void drain();
}

async function drain() {
  running = true;
  try {
    while (queued) {
      const role = queued;
      queued = null;
      await rebuild(role);
    }
  } finally {
    running = false;
  }
}

async function rebuild(role: string) {
  set({ stage: "analysing", role, message: null });
  try {
    await runAnalysis(role);
    await resultsPageData.fetch(true);
  } catch (error) {
    set({ stage: "failed", role, message: analysisProblem(error) });
    return;
  }

  set({ stage: "building", role, message: null });
  try {
    const profile = profileData.peek() ?? (await profileData.fetch().catch(() => null));
    await generateRoadmap(role, profile?.hours_per_week);
    await roadmapPageData.fetch(true);
    set({ stage: "done", role, message: null });
  } catch (error) {
    const problem = roadmapProblem(error);
    // The old plan is left untouched when generating fails, so reload whatever is there
    await roadmapPageData.fetch(true).catch(() => undefined);
    if (problem === null) {
      set({
        stage: "done",
        role,
        message: `You already meet the assessed requirements for ${role}, so there’s nothing to plan yet.`,
      });
    } else {
      set({ stage: "failed", role, message: problem });
    }
  }
}
