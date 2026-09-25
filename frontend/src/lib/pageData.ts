/**
 * Remembers the last data each logged-in page loaded, so switching pages shows it
 * instantly while fresh data is fetched in the background.
 */
import { getLatestAnalysis, getGaps, type SkillGap } from "../services/analysis";
import { getAvailableAssessments, getDsaChecklist, type AvailableAssessment } from "../services/assessment";
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

import { forgetAll, remember, rememberByKey, subscribeRemembered } from "./remembered";

/** Lets components (e.g. the top bar name) update when remembered data changes. */
export const subscribePageData = subscribeRemembered;

/** Forget everything — call on logout so the next user never sees old data. */
export const clearPageData = forgetAll;

const cached = remember;
const cachedByKey = rememberByKey;

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

/**
 * The skills INAURA suggests proving. Kept apart from the analysis bundle so Skill Assessment
 * still opens for someone who hasn't run an analysis yet.
 */
export const assessmentsData = cached("assessments", () =>
  getAvailableAssessments()
    .then((d) => d.available || [])
    .catch(() => [] as AvailableAssessment[])
);

export const resultsPageData = cached("results-page", async () => {
  const [analysis, gaps, evidence, projects, githubRepos, assessable] = await Promise.all([
    getLatestAnalysis(),
    getGaps().catch(() => [] as SkillGap[]),
    listEvidence().catch(() => [] as Evidence[]),
    listProjects().catch(() => [] as Project[]),
    listGithubRepos().catch(() => [] as GithubRepo[]),
    // Fresh whenever the results are, and shared with the Skill Assessment page
    assessmentsData.fetch(true),
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

/** The DSA question bank and what you've solved — Revision builds cards from it */
export const dsaChecklistData = cached("dsa-checklist", getDsaChecklist);

/** Career Track: the capability map for one role (skills, progress, topics) */
export const capabilityMapData = cachedByKey("capability-map", (role) => getCapabilityMap({ target_role: role }));

/** Warm up every sidebar page in the background right after login. */
export function preloadPageData() {
  for (const d of [profileData, roleCatalogData, evidencePageData, resultsPageData, roadmapPageData, dsaChecklistData]) {
    d.fetch().catch(() => {
      // the page itself shows the error when opened
    });
  }
  // Career Track is the home screen, and its capability map is the slowest thing the app asks
  // for. Start it here off the small target-role call, so it's ready before the first click.
  analysisStateData
    .fetch()
    .then((state) => (state?.target_role ? capabilityMapData(state.target_role).fetch() : undefined))
    .catch(() => undefined);
}

/** Re-fetch every page's data now — e.g. after the profile changes, since several pages show it. */
export function refreshPageData() {
  for (const d of [profileData, analysisStateData, evidencePageData, resultsPageData, roadmapPageData]) {
    d.fetch(true).catch(() => undefined);
  }
  // Career Track reads these, and they're built from the evidence that just changed
  capabilityMapData.refreshAll();
}
