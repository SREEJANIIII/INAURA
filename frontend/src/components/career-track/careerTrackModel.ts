/**
 * Career Track model: turns INAURA's per-role capability map into a career track —
 * skills with progress, gaps, status and topics, grouped into learning phases.
 *
 * Every number comes from existing data:
 *   evidence → skill profile (proficiency) → role benchmark (required_level) → gap → readiness.
 * Pure functions only, so it can be tested without React or the API.
 */
import type { AnalysisResult } from "../../services/analysis";
import type { AvailableAssessment } from "../../services/assessment";
import type { CapabilityMap, CapabilityResource, SkillCapability } from "../../services/capability";
import type { RoleSummary } from "../../services/industry";

/* ---------------- Types ---------------- */

export type SkillStatus = "completed" | "in-progress" | "not-started" | "locked";

export type TopicState = "done" | "developing" | "todo";

export type TrackTopic = { id: string; title: string; summary: string; state: TopicState };

export type TrackSkill = {
  /** URL-friendly id, e.g. "html-css" */
  id: string;
  /** Backend canonical slug, e.g. "html_css" */
  slug: string;
  name: string;
  description: string;
  category: string;
  currentProgress: number;
  requiredProgress: number;
  gap: number;
  currentLevel: string;
  requiredLevel: string;
  confidence: number;
  importance: number;
  status: SkillStatus;
  topics: TrackTopic[];
  completedTopics: number;
  totalTopics: number;
  /** Prerequisites that are part of this track */
  prerequisites: { id: string; name: string; met: boolean }[];
  nextActions: string[];
  resources: CapabilityResource[];
  evidenceCount: number;
  raw: SkillCapability;
};

export type TrackPhase = {
  id: string;
  title: string;
  skills: TrackSkill[];
  progress: number;
  status: "completed" | "in-progress" | "not-started";
};

export type CareerTrack = {
  id: string;
  title: string;
  description: string;
  category: string;
  skills: TrackSkill[];
  phases: TrackPhase[];
  priority: TrackSkill[];
  readiness: { value: number; source: "analysis" | "estimate" };
  counts: Record<SkillStatus, number>;
};

/* ---------------- Ids ---------------- */

/** "Frontend Developer" / "frontend_developer" → "frontend-developer" */
export const toId = (s: string) =>
  s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");

export const roleId = (role: Pick<RoleSummary, "slug" | "title">) => toId(role.slug || role.title);

export function findRole(catalog: RoleSummary[], id: string | undefined) {
  if (!id) return undefined;
  return catalog.find((r) => roleId(r) === id || toId(r.title) === id);
}

/* ---------------- Levels ---------------- */

export const pct = (v: number | null | undefined) => Math.round(Math.max(0, Math.min(1, v ?? 0)) * 100);

export function levelName(percent: number) {
  if (percent >= 85) return "Expert";
  if (percent >= 70) return "Advanced";
  if (percent >= 45) return "Intermediate";
  if (percent > 0) return "Beginner";
  return "Not started";
}

/* ---------------- Phases ---------------- */

/**
 * Categories from the industry requirements are grouped into learning phases in a fixed,
 * teachable order. Works for every role; empty phases are dropped.
 */
const PHASES: { id: string; title: string; match: RegExp }[] = [
  { id: "foundations", title: "Foundations", match: /programming|computer science|core|tools|collaboration|soft|communication/i },
  { id: "core-stack", title: "Core stack", match: /frontend|mobile|backend|software development/i },
  { id: "data", title: "Data and intelligence", match: /data|database|ai|ml|machine/i },
  { id: "quality", title: "Architecture and quality", match: /architecture|design|quality|testing/i },
  { id: "production", title: "Production and security", match: /devops|cloud|security|cyber|infra/i },
];

export function phaseFor(category: string) {
  return PHASES.find((p) => p.match.test(category || "")) ?? PHASES[1];
}

/* ---------------- Building a track ---------------- */

export const displayName = (skill: string) => {
  // Canonical names come lowercase with underscores from the engine ("html_css")
  if (/[A-Z]/.test(skill)) return skill;
  const special: Record<string, string> = {
    html_css: "HTML & CSS",
    javascript: "JavaScript",
    typescript: "TypeScript",
    sql: "SQL",
    dsa: "Data Structures & Algorithms",
    rest_apis: "REST APIs",
    aws_gcp: "AWS / GCP",
    cicd: "CI/CD",
    nodejs: "Node.js",
    scikit_learn: "scikit-learn",
    numpy: "NumPy",
  };
  return special[skill] ?? skill.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
};

const topicState = (status: string | undefined): TopicState =>
  status === "demonstrated" ? "done" : status === "developing" ? "developing" : "todo";

function baseSkill(c: SkillCapability): TrackSkill {
  const current = pct(c.proficiency);
  const required = pct(c.required_level);
  const topics: TrackTopic[] = (c.capabilities ?? []).map((cap) => ({
    id: cap.id,
    title: cap.title,
    summary: cap.summary,
    state: topicState(cap.status),
  }));
  return {
    id: toId(c.slug || c.skill),
    slug: c.slug,
    name: displayName(c.skill),
    description:
      c.requirement?.evidence_context ||
      c.industry_expectations?.[0]?.detail ||
      c.what_inaura_knows?.summary ||
      "",
    category: c.category || "",
    currentProgress: current,
    requiredProgress: required,
    gap: Math.max(0, required - current),
    currentLevel: levelName(current),
    requiredLevel: levelName(required),
    confidence: pct(c.confidence),
    importance: pct(c.importance),
    status: "not-started",
    topics,
    completedTopics: topics.filter((t) => t.state === "done").length,
    totalTopics: topics.length,
    prerequisites: [],
    nextActions: Array.from(new Set((c.missing_capabilities ?? []).flatMap((m) => m.next_actions ?? []))).slice(0, 5),
    resources: (c.missing_capabilities ?? []).flatMap((m) => m.resources ?? []).slice(0, 6),
    evidenceCount: (c.evidence_sources ?? []).length,
    raw: c,
  };
}

export function statusOf(skill: Pick<TrackSkill, "currentProgress" | "requiredProgress">, prerequisitesMet: boolean): SkillStatus {
  const { currentProgress: cur, requiredProgress: req } = skill;
  if (req > 0 && cur >= req) return "completed";
  if (cur > 0) return "in-progress";
  // Only lock untouched skills, and only when a real prerequisite in this track isn't done yet
  return prerequisitesMet ? "not-started" : "locked";
}

/** Importance-weighted share of each required level you've reached (0–100) */
export function estimateReadiness(skills: Pick<TrackSkill, "currentProgress" | "requiredProgress" | "importance">[]) {
  let weighted = 0;
  let total = 0;
  for (const s of skills) {
    if (s.requiredProgress <= 0) continue;
    const w = Math.max(0.1, s.importance / 100);
    weighted += w * Math.min(1, s.currentProgress / s.requiredProgress);
    total += w;
  }
  return total ? Math.round((weighted / total) * 100) : 0;
}

export function buildTrack(args: {
  role: RoleSummary;
  map: CapabilityMap;
  /** Latest analysis: its official readiness is used when it was run for this role */
  analysis?: AnalysisResult | null;
}): CareerTrack {
  const { role, map, analysis } = args;
  const skills = (map.skills ?? []).map(baseSkill);
  const bySlug = new Map(skills.map((s) => [s.slug, s]));

  // Prerequisites and status need every skill in place first
  for (const s of skills) {
    s.prerequisites = (s.raw.prerequisites ?? [])
      .map((p) => bySlug.get(p))
      .filter((p): p is TrackSkill => !!p)
      .map((p) => ({ id: p.id, name: p.name, met: p.requiredProgress > 0 && p.currentProgress >= p.requiredProgress }));
  }
  for (const s of skills) {
    s.status = statusOf(s, s.prerequisites.every((p) => p.met));
  }

  const counts: Record<SkillStatus, number> = { completed: 0, "in-progress": 0, "not-started": 0, locked: 0 };
  for (const s of skills) counts[s.status] += 1;

  // Priority: biggest gap between required and current, most important first on ties.
  // Locked skills wait for their prerequisites, which carry the priority instead.
  const priority = skills
    .filter((s) => s.status !== "completed" && s.status !== "locked" && s.gap > 0)
    .sort((a, b) => b.gap - a.gap || b.importance - a.importance)
    .slice(0, 3);

  // Phases: fixed order; within a phase, prerequisites before the skills that need them
  const phases: TrackPhase[] = PHASES.map((p) => {
    const inPhase = skills.filter((s) => phaseFor(s.category).id === p.id);
    const ordered = orderByPrerequisites(inPhase);
    const progress = ordered.length
      ? Math.round(ordered.reduce((sum, s) => sum + (s.requiredProgress ? Math.min(1, s.currentProgress / s.requiredProgress) : 0), 0) / ordered.length * 100)
      : 0;
    return {
      id: p.id,
      title: p.title,
      skills: ordered,
      progress,
      status: (progress >= 100 ? "completed" : progress > 0 ? "in-progress" : "not-started") as TrackPhase["status"],
    };
  }).filter((p) => p.skills.length > 0);

  const official = analysis && analysis.target_role.toLowerCase() === role.title.toLowerCase();
  return {
    id: roleId(role),
    title: role.title,
    description: role.description,
    category: role.category,
    skills: orderByPrerequisites(skills),
    phases,
    priority,
    readiness: official
      ? { value: pct(analysis.readiness_score), source: "analysis" }
      : { value: estimateReadiness(skills), source: "estimate" },
    counts,
  };
}

/** Stable order: a skill never appears before a prerequisite that's also in the list */
export function orderByPrerequisites(skills: TrackSkill[]) {
  const ids = new Set(skills.map((s) => s.id));
  const placed = new Set<string>();
  const out: TrackSkill[] = [];
  const remaining = [...skills].sort((a, b) => b.importance - a.importance);
  let guard = 0;
  while (remaining.length && guard++ < 500) {
    const idx = remaining.findIndex((s) => s.prerequisites.every((p) => !ids.has(p.id) || placed.has(p.id)));
    const [next] = remaining.splice(idx === -1 ? 0 : idx, 1);
    out.push(next);
    placed.add(next.id);
  }
  return out;
}

/** Where you are on the path: the skill you're working on, or the next one to start */
export function currentSkill(phases: TrackPhase[]): TrackSkill | null {
  const inOrder = phases.flatMap((p) => p.skills);
  return (
    inOrder.find((s) => s.status === "in-progress") ??
    inOrder.find((s) => s.status === "not-started") ??
    inOrder.find((s) => s.status === "locked") ??
    null
  );
}

/* ---------------- Skill page helpers ---------------- */

export function assessmentFor(skill: TrackSkill, assessable: AvailableAssessment[]) {
  const keys = [skill.slug, skill.name, skill.raw.skill].map((k) => toId(k || ""));
  return assessable.find((a) => keys.includes(toId(a.skill_key)) || keys.includes(toId(a.skill)));
}

export const STATUS_LABEL: Record<SkillStatus, string> = {
  completed: "Completed",
  "in-progress": "In progress",
  "not-started": "Not started",
  locked: "Locked",
};

export const CTA_LABEL: Record<SkillStatus, string> = {
  completed: "Review skill",
  "in-progress": "Continue learning",
  "not-started": "Start learning",
  locked: "View prerequisites",
};
