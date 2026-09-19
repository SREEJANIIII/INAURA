/**
 * Remembers the last data each logged-in page loaded, so switching pages shows it
 * instantly while fresh data is fetched in the background.
 */
import { getLatestAnalysis, getGaps, type SkillGap } from "../services/analysis";
import { getAvailableAssessments } from "../services/assessment";
import {
  listCerts,
  listEvidence,
  listGithubRepos,
  listProjects,
  type Certification,
  type Evidence,
  type GithubRepo,
  type Project,
} from "../services/evidence";
import { getAnalysisState, getRolesCatalog, listRoles, type AnalysisState } from "../services/industry";
import { getCapabilityMap } from "../services/capability";
import { getProfile } from "../services/profile";
import { getLatestRoadmap, getRoadmapWeeks } from "../services/roadmap";

const store = new Map<string, unknown>();
const inflight = new Map<string, Promise<unknown>>();
const listeners = new Set<() => void>();
const notify = () => listeners.forEach((l) => l());

/** Lets components (e.g. the top bar name) update when remembered data changes. */
export function subscribePageData(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

// Shares one request between callers (e.g. background preload + page opening at the same time).
// Pass force=true after saving something, so an older in-progress request isn't reused.
function cached<T>(key: string, load: () => Promise<T>) {
  const peek = () => store.get(key) as T | undefined;
  const fetch = (force = false) => {
    let p = force ? undefined : (inflight.get(key) as Promise<T> | undefined);
    if (!p) {
      const request: Promise<T> = load()
        .then((data) => {
          // Ignore an older request finishing after a newer one started (or after logout)
          if (inflight.get(key) === request) {
            store.set(key, data);
            notify();
          }
          return data;
        })
        .finally(() => {
          if (inflight.get(key) === request) inflight.delete(key);
        });
      inflight.set(key, request);
      p = request;
    }
    return p;
  };
  return { peek, fetch };
}

/** One remembered copy per key, e.g. per role — same sharing and logout clearing as above */
function cachedByKey<T>(prefix: string, load: (key: string) => Promise<T>) {
  const made = new Map<string, ReturnType<typeof cached<T>>>();
  return (key: string) => {
    let entry = made.get(key);
    if (!entry) {
      entry = cached(`${prefix}:${key}`, () => load(key));
      made.set(key, entry);
    }
    return entry;
  };
}

/** Forget everything — call on logout so the next user never sees old data. */
export function clearPageData() {
  store.clear();
  inflight.clear();
  notify();
}

export const profileData = cached("profile", getProfile);

/** Just the chosen target role and analysis status — small, so Career Track can redirect without waiting for all evidence */
export const analysisStateData = cached("analysis-state", getAnalysisState);

export const evidencePageData = cached("evidence-page", async () => {
  const [evidence, projects, certs, roles, analysisState, profile] = await Promise.all([
    listEvidence().catch(() => [] as Evidence[]),
    listProjects().catch(() => [] as Project[]),
    listCerts().catch(() => [] as Certification[]),
    listRoles().catch(() => [] as string[]),
    analysisStateData.fetch(true).catch(() => null as AnalysisState | null),
    getProfile().catch(() => null),
  ]);
  return { evidence, projects, certs, roles, analysisState, profile };
});

export const resultsPageData = cached("results-page", async () => {
  const [analysis, gaps, evidence, projects, githubRepos, assessable] = await Promise.all([
    getLatestAnalysis(),
    getGaps().catch(() => [] as SkillGap[]),
    listEvidence().catch(() => [] as Evidence[]),
    listProjects().catch(() => [] as Project[]),
    listGithubRepos().catch(() => [] as GithubRepo[]),
    getAvailableAssessments()
      .then((d) => d.available || [])
      .catch(() => []),
  ]);
  return { analysis, gaps, evidence, projects, githubRepos, assessable };
});

export const roadmapPageData = cached("roadmap-page", async () => {
  const [profile, analysis, roadmapBundle] = await Promise.all([
    getProfile().catch(() => null),
    getLatestAnalysis().catch(() => null),
    getLatestRoadmap()
      .then(async (roadmap) => ({ roadmap, weeks: await getRoadmapWeeks(roadmap.id) }))
      .catch((e: unknown) => {
        // Missing tables is a real error; "no roadmap yet" just means none generated
        if (e instanceof Error && e.message.includes("503")) throw e;
        return null;
      }),
  ]);
  return { profile, analysis, roadmap: roadmapBundle?.roadmap ?? null, weeks: roadmapBundle?.weeks ?? [] };
});

export const roleCatalogData = cached("role-catalog", getRolesCatalog);

/** Career Track: the capability map for one role (skills, progress, topics) */
export const capabilityMapData = cachedByKey("capability-map", (role) => getCapabilityMap({ target_role: role }));

/** Warm up every sidebar page in the background right after login. */
export function preloadPageData() {
  for (const d of [profileData, evidencePageData, resultsPageData, roadmapPageData]) {
    d.fetch().catch(() => {
      // the page itself shows the error when opened
    });
  }
}

/** Re-fetch every page's data now — e.g. after the profile changes, since several pages show it. */
export function refreshPageData() {
  for (const d of [profileData, evidencePageData, resultsPageData, roadmapPageData]) {
    d.fetch(true).catch(() => undefined);
  }
}
