/**
 * Journey model: turns the weekly roadmap into the career journey the Roadmap page draws —
 * the plan's skills in the order you'll learn them, grouped into checkpoints, each skill with
 * a state and the reasons it's there, where you are on the road, and what readiness would
 * become if you closed a few gaps.
 *
 * Every number comes from existing data: the tasks (progress, effort, schedule), the latest
 * analysis (levels, evidence, priority, readiness) and the skill prerequisite graph the plan
 * was built with. Nothing is estimated here that the page can't trace back to one of those.
 * Pure functions only, so it can be tested without React or the API.
 */
import type { AnalysisResult, SkillGap } from "../../services/analysis";
import type { Roadmap, RoadmapTask, RoadmapWeek } from "../../services/roadmap";
import { levelName, pct, phaseFor } from "../career-track/careerTrackModel.ts";
import { classifySkill, SIGNAL_STAGES, type SignalStage } from "../home/homeModel.ts";

/* ---------------- Types ---------------- */

export type SkillState = "proven" | "building" | "needs-proof" | "priority-gap" | "locked" | "upcoming";

/** Order the legend and the counts use: done, doing, then what's ahead by urgency */
export const STATE_ORDER: SkillState[] = ["proven", "building", "needs-proof", "priority-gap", "locked", "upcoming"];

export const STATE_META: Record<SkillState, { label: string; hint: string }> = {
  proven: { label: "Proven", hint: "Meets the level the role needs, backed by strong evidence" },
  building: { label: "Building", hint: "You're working on this now" },
  "needs-proof": { label: "Needs proof", hint: "You may have this skill, but the evidence for it is weak" },
  "priority-gap": { label: "Priority gap", hint: "Important for the role, and nothing shows it yet" },
  locked: { label: "Locked", hint: "Waits for a skill that comes before it" },
  upcoming: { label: "Upcoming", hint: "Not started yet" },
};

export type Tier = "critical" | "high" | "other";

export type JourneyTask = { task: RoadmapTask; week: number };

export type JourneySkill = {
  /** Normalised skill key, e.g. "rest_apis" — what tasks, gaps and prerequisites are matched on */
  key: string;
  name: string;
  shortName: string;
  /** Position in the plan, 0-based */
  order: number;
  tasks: JourneyTask[];
  firstWeek: number;
  lastWeek: number;
  /** Planned minutes, skipped tasks left out */
  minutes: number;
  doneMinutes: number;
  remainingMinutes: number;
  /** 0–100, by planned time */
  progress: number;
  started: boolean;
  tasksDone: boolean;
  /** This skill's row in the latest analysis, when there is one */
  gap: SkillGap | null;
  /** 0–100 from the analysis, or null when the analysis doesn't cover this skill */
  current: number | null;
  required: number | null;
  evidence: SignalStage | null;
  tier: Tier;
  /** Career Track's phase for the skill's category, e.g. "Foundations" */
  phase: string;
  /** Prerequisites that are also in this plan */
  prerequisites: { key: string; name: string; met: boolean }[];
  /** Later skills in this plan that build on this one */
  unlocks: string[];
  state: SkillState;
  stage: number;
};

export type StageStatus = "done" | "current" | "ahead";

export type JourneyStage = {
  index: number;
  /** "01" */
  number: string;
  title: string;
  phase: string;
  tier: Tier;
  skills: JourneySkill[];
  minutes: number;
  doneMinutes: number;
  remainingMinutes: number;
  progress: number;
  status: StageStatus;
  firstWeek: number;
  lastWeek: number;
  /** 0–1: how far below the role's level these skills sit, weighted by importance — the terrain's height */
  elevation: number;
  counts: Record<SkillState, number>;
};

export type Journey = {
  skills: JourneySkill[];
  stages: JourneyStage[];
  /** Index of the checkpoint you're heading to; stages.length once every stage is done */
  currentStage: number;
  /** The skill you're on: the first one in the plan that isn't finished */
  currentSkill: JourneySkill | null;
  /** Where the marker sits: 0 is the start, k is checkpoint k, fractions are part-way along */
  position: number;
  /** 0–100 of the planned hours done */
  progress: number;
  totalMinutes: number;
  doneMinutes: number;
  remainingMinutes: number;
  /** The first week with anything left to do */
  currentWeek: number | null;
  weekCount: number;
  counts: Record<SkillState, number>;
};

/* ---------------- Small helpers ---------------- */

/** "REST APIs" / "rest-apis" / "rest_apis" → "rest_apis" */
export const keyOf = (s: string | null | undefined) =>
  (s ?? "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");

const SHORT_NAMES: Record<string, string> = {
  data_structures_algorithms: "DSA",
  object_oriented_programming: "OOP",
};

/** Long skill names shortened for map labels: "Data Structures & Algorithms" → "DSA" */
export const shortName = (name: string) => SHORT_NAMES[keyOf(name)] ?? name;

const clamp01 = (v: number) => Math.max(0, Math.min(1, Number.isFinite(v) ? v : 0));

const emptyCounts = (): Record<SkillState, number> => ({
  proven: 0,
  building: 0,
  "needs-proof": 0,
  "priority-gap": 0,
  locked: 0,
  upcoming: 0,
});

/** A task no longer in the way: done, or skipped */
export const isCleared = (t: RoadmapTask) => t.status === "completed" || t.status === "skipped" || t.completion_percentage >= 100;

/** How much of a task counts as done, 0–1 (skipped tasks are left out of the totals instead) */
const doneShare = (t: RoadmapTask) => (t.status === "completed" ? 1 : clamp01((t.completion_percentage || 0) / 100));

export const tierOf = (g: SkillGap | null): Tier | null => {
  if (!g) return null;
  const c = (g.priority_category || "").toLowerCase();
  return c === "critical" ? "critical" : c === "high" ? "high" : "other";
};

export function tierLabel(tier: Tier, role: string) {
  if (tier === "critical") return `Critical for ${role}`;
  if (tier === "high") return "High priority";
  return "Lower priority";
}

/** One index over the analysis's gaps, by every name a skill goes by */
function indexGaps(gaps: SkillGap[]) {
  const byKey = new Map<string, SkillGap>();
  for (const g of gaps) {
    for (const name of [g.skills?.canonical_name, g.canonical_name, g.skill, g.skills?.display_name]) {
      const k = keyOf(name);
      if (k && !byKey.has(k)) byKey.set(k, g);
    }
  }
  return byKey;
}

/** Prerequisites the plan was ordered with (the backend's skill graph), keyed by skill */
function indexPrerequisites(roadmap: Pick<Roadmap, "skill_explanations"> | null) {
  const byKey = new Map<string, string[]>();
  for (const e of roadmap?.skill_explanations ?? []) {
    const k = keyOf(e.skill_slug || e.canonical_name || e.skill_name);
    if (k) byKey.set(k, (e.prerequisites_required ?? []).map(keyOf).filter(Boolean));
  }
  return byKey;
}

/* ---------------- State ---------------- */

type StateInput = {
  gap: SkillGap | null;
  evidence: SignalStage | null;
  tier: Tier;
  started: boolean;
  tasksDone: boolean;
  inCurrentWeek: boolean;
  blocked: boolean;
};

/**
 * One state per skill, most telling first: proven by the analysis, being worked on, finished
 * but not yet confirmed, missing and important, waiting on a prerequisite, weak evidence, or
 * simply not started.
 */
export function stateOf(s: StateInput): SkillState {
  const g = s.gap;
  const meets = !!g && g.required_level > 0 && (g.current_proficiency >= g.required_level - 1e-6 || g.gap <= 1e-6);
  if (meets && s.evidence === "verified") return "proven";
  if (!s.tasksDone && (s.started || s.inCurrentWeek)) return "building";
  // The work is done; the analysis hasn't confirmed the level yet
  if (s.tasksDone) return "needs-proof";
  if (g && s.tier !== "other" && s.evidence === "none") return "priority-gap";
  if (s.blocked) return "locked";
  if (g && (meets || s.evidence === "claimed" || (g.gap_type === "evidence_gap" && g.current_proficiency > 0))) return "needs-proof";
  return "upcoming";
}

/* ---------------- Checkpoints ---------------- */

/** How many checkpoints a plan of n skills gets: at least 3 (when it can), at most 6 */
export function stageCount(n: number) {
  if (n <= 0) return 0;
  return Math.min(n, Math.max(Math.min(3, n), Math.min(6, Math.ceil(n / 4))));
}

/** Split items into k runs in order, each as close to an equal share of minutes as it can be */
export function splitBalanced<T extends { minutes: number }>(items: T[], k: number): T[][] {
  const groups: T[][] = [];
  let start = 0;
  for (let left = Math.min(k, items.length); left > 1; left--) {
    const rest = items.slice(start);
    const target = rest.reduce((sum, i) => sum + i.minutes, 0) / left;
    let acc = 0;
    let end = start;
    // Leave at least one item for each group still to come
    while (end < items.length - (left - 1)) {
      const next = acc + items[end].minutes;
      if (end > start && Math.abs(next - target) > Math.abs(acc - target)) break;
      acc = next;
      end += 1;
    }
    groups.push(items.slice(start, end));
    start = end;
  }
  groups.push(items.slice(start));
  return groups.filter((g) => g.length > 0);
}

/**
 * Group the plan's skills into checkpoints without reordering them. Priority tiers
 * (critical → high → the rest) are cut first, since that's what the plan was sorted by;
 * then each tier is split into checkpoints of roughly equal effort.
 */
export function groupIntoStages<T extends { minutes: number; tier: Tier }>(skills: T[]): T[][] {
  const target = stageCount(skills.length);
  if (!target) return [];

  type Run = { items: T[]; minutes: number };
  let runs: Run[] = [];
  for (const s of skills) {
    const last = runs[runs.length - 1];
    if (last && last.items[last.items.length - 1].tier === s.tier) {
      last.items.push(s);
      last.minutes += s.minutes;
    } else {
      runs.push({ items: [s], minutes: s.minutes });
    }
  }

  // Too many runs (tiers interleaved by prerequisites): merge the lightest neighbours
  while (runs.length > target) {
    let best = 0;
    for (let i = 1; i < runs.length - 1; i++) {
      if (runs[i].minutes + runs[i + 1].minutes < runs[best].minutes + runs[best + 1].minutes) best = i;
    }
    const merged = { items: [...runs[best].items, ...runs[best + 1].items], minutes: runs[best].minutes + runs[best + 1].minutes };
    runs = [...runs.slice(0, best), merged, ...runs.slice(best + 2)];
  }

  // Share the remaining checkpoints out by effort (largest remainder), never more than a run has skills
  const total = runs.reduce((sum, r) => sum + r.minutes, 0) || 1;
  const counts = runs.map(() => 1);
  let spare = target - runs.length;
  const want = runs.map((r) => (r.minutes / total) * target);
  while (spare > 0) {
    let pick = -1;
    let bestNeed = -Infinity;
    runs.forEach((r, i) => {
      if (counts[i] >= r.items.length) return;
      const need = want[i] - counts[i];
      if (need > bestNeed) {
        bestNeed = need;
        pick = i;
      }
    });
    if (pick === -1) break;
    counts[pick] += 1;
    spare -= 1;
  }

  return runs.flatMap((r, i) => splitBalanced(r.items, counts[i]));
}

/** "Python", "Python & DSA", "OOP, Java, SQL & Git", or "Responsive Design, AWS + 4 more" */
export function stageTitle(names: string[]) {
  if (names.length <= 1) return names[0] ?? "";
  const all = `${names.slice(0, -1).join(", ")} & ${names[names.length - 1]}`;
  if (all.length <= 34) return all;
  const two = `${names[0]}, ${names[1]}`;
  return names.length === 2 ? all : `${two} + ${names.length - 2} more`;
}

/** The label most of a checkpoint's effort falls under, e.g. "Foundations" */
function dominant(entries: { label: string; weight: number }[]) {
  const totals = new Map<string, number>();
  for (const e of entries) if (e.label) totals.set(e.label, (totals.get(e.label) ?? 0) + e.weight);
  let best = "";
  let bestWeight = -1;
  for (const [label, weight] of totals) {
    if (weight > bestWeight) {
      best = label;
      bestWeight = weight;
    }
  }
  return best;
}

/* ---------------- Building the journey ---------------- */

export function buildJourney(args: {
  weeks: RoadmapWeek[];
  roadmap?: Pick<Roadmap, "skill_explanations"> | null;
  gaps?: SkillGap[];
}): Journey {
  const weeks = [...args.weeks].sort((a, b) => a.week_number - b.week_number);
  const gapByKey = indexGaps(args.gaps ?? []);
  const prereqByKey = indexPrerequisites(args.roadmap ?? null);

  // The first week with anything left: where the plan says you are
  const currentWeek = weeks.find((w) => (w.tasks ?? []).some((t) => !isCleared(t)))?.week_number ?? null;

  // Skills in the order the plan schedules them
  type Draft = { key: string; name: string; tasks: JourneyTask[] };
  const drafts: Draft[] = [];
  const draftByKey = new Map<string, Draft>();
  for (const w of weeks) {
    const tasks = [...(w.tasks ?? [])].sort((a, b) => a.sequence_order - b.sequence_order);
    for (const task of tasks) {
      const key = keyOf(task.skill_slug || task.skill_name);
      if (!key) continue;
      let d = draftByKey.get(key);
      if (!d) {
        d = { key, name: task.skill_name || task.skill_slug, tasks: [] };
        draftByKey.set(key, d);
        drafts.push(d);
      }
      d.tasks.push({ task, week: w.week_number });
    }
  }

  let lastTier: Tier = "critical";
  const skills: JourneySkill[] = drafts.map((d, order) => {
    const gap = gapByKey.get(d.key) ?? gapByKey.get(keyOf(d.name)) ?? null;
    const counted = d.tasks.filter((t) => t.task.status !== "skipped");
    const minutes = counted.reduce((sum, t) => sum + (t.task.estimated_minutes || 0), 0);
    const doneMinutes = counted.reduce((sum, t) => sum + (t.task.estimated_minutes || 0) * doneShare(t.task), 0);
    const tier = tierOf(gap) ?? lastTier;
    lastTier = tier;
    return {
      key: d.key,
      name: d.name,
      shortName: shortName(d.name),
      order,
      tasks: d.tasks,
      firstWeek: d.tasks[0]?.week ?? 0,
      lastWeek: d.tasks[d.tasks.length - 1]?.week ?? 0,
      minutes,
      doneMinutes,
      remainingMinutes: Math.max(0, minutes - doneMinutes),
      progress: minutes ? Math.round((doneMinutes / minutes) * 100) : d.tasks.every((t) => isCleared(t.task)) ? 100 : 0,
      started: d.tasks.some((t) => t.task.status === "in_progress" || t.task.status === "completed" || t.task.completion_percentage > 0),
      tasksDone: d.tasks.length > 0 && d.tasks.every((t) => isCleared(t.task)),
      gap,
      current: gap ? pct(gap.current_proficiency) : null,
      required: gap ? pct(gap.required_level) : null,
      evidence: gap ? classifySkill(gap) : null,
      tier,
      phase: gap ? phaseFor(gap.skills?.category || "").title : "",
      prerequisites: [],
      unlocks: [],
      state: "upcoming",
      stage: 0,
    };
  });

  const byKey = new Map(skills.map((s) => [s.key, s]));
  // Prerequisites first (they decide "locked"), then states in plan order
  for (const s of skills) {
    const needs = (prereqByKey.get(s.key) ?? []).map((k) => byKey.get(k)).filter((p): p is JourneySkill => !!p && p !== s);
    s.prerequisites = needs.map((p) => ({ key: p.key, name: p.shortName, met: false }));
    for (const p of needs) p.unlocks.push(s.shortName);
  }
  for (const s of skills) {
    for (const p of s.prerequisites) {
      const pre = byKey.get(p.key);
      p.met = !!pre && (pre.tasksDone || pre.state === "proven");
    }
    s.state = stateOf({
      gap: s.gap,
      evidence: s.evidence,
      tier: s.tier,
      started: s.started,
      tasksDone: s.tasksDone,
      inCurrentWeek: currentWeek !== null && s.tasks.some((t) => t.week === currentWeek && !isCleared(t.task)),
      blocked: s.prerequisites.some((p) => !p.met),
    });
  }

  const groups = groupIntoStages(skills);
  let currentStage = groups.length;
  const stages: JourneyStage[] = groups.map((group, index) => {
    const minutes = group.reduce((sum, s) => sum + s.minutes, 0);
    const doneMinutes = group.reduce((sum, s) => sum + s.doneMinutes, 0);
    const done = group.every((s) => s.tasksDone || s.state === "proven");
    if (!done && currentStage === groups.length) currentStage = index;
    const counts = emptyCounts();
    for (const s of group) {
      s.stage = index;
      counts[s.state] += 1;
    }
    const withGap = group.filter((s) => s.gap);
    const importance = withGap.reduce((sum, s) => sum + (s.gap?.importance ?? 0), 0);
    const elevation = importance
      ? withGap.reduce((sum, s) => sum + (s.gap?.importance ?? 0) * clamp01(s.gap?.gap ?? 0), 0) / importance
      : 0;
    return {
      index,
      number: String(index + 1).padStart(2, "0"),
      title: stageTitle(group.map((s) => s.shortName)),
      phase: dominant(group.map((s) => ({ label: s.phase, weight: s.minutes }))),
      tier: dominant(group.map((s) => ({ label: s.tier, weight: s.minutes }))) as Tier,
      skills: group,
      minutes,
      doneMinutes,
      remainingMinutes: Math.max(0, minutes - doneMinutes),
      progress: minutes ? Math.round((doneMinutes / minutes) * 100) : done ? 100 : 0,
      status: done ? "done" : "ahead",
      firstWeek: Math.min(...group.map((s) => s.firstWeek)),
      lastWeek: Math.max(...group.map((s) => s.lastWeek)),
      elevation,
      counts,
    };
  });
  if (currentStage < stages.length) stages[currentStage].status = "current";

  const totalMinutes = skills.reduce((sum, s) => sum + s.minutes, 0);
  const doneMinutes = skills.reduce((sum, s) => sum + s.doneMinutes, 0);
  const at = stages[currentStage];
  const position = at ? currentStage + (at.minutes ? Math.min(1, at.doneMinutes / at.minutes) : 0) : stages.length;

  const counts = emptyCounts();
  for (const s of skills) counts[s.state] += 1;

  return {
    skills,
    stages,
    currentStage,
    currentSkill: skills.find((s) => !s.tasksDone && s.state !== "proven") ?? null,
    position,
    progress: totalMinutes ? Math.round((doneMinutes / totalMinutes) * 100) : 0,
    totalMinutes,
    doneMinutes,
    remainingMinutes: Math.max(0, totalMinutes - doneMinutes),
    currentWeek,
    weekCount: weeks.length,
    counts,
  };
}

/** How a checkpoint reads on the map: reached, in progress / up next, or ahead */
export const stageStatusLabel = (s: Pick<JourneyStage, "status" | "progress">) =>
  s.status === "done" ? "Reached" : s.status === "current" ? (s.progress > 0 ? "In progress" : "Up next") : "Ahead";

/* ---------------- Reasons ---------------- */

export type Reason = { label: string; text: string };

const joinNames = (names: string[]) =>
  names.length <= 1 ? names[0] ?? "" : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;

const PRIORITY_WORD: Record<Tier, string> = { critical: "critical", high: "high priority", other: "lower priority" };

/**
 * "Why is this on my roadmap?" — the reasons INAURA placed a skill where it is, each traced
 * to its source: the role's requirement, the gap, the evidence, the prerequisite graph and the
 * schedule.
 */
export function skillReasons(skill: JourneySkill, journey: Pick<Journey, "skills" | "weekCount">, role: string): Reason[] {
  const reasons: Reason[] = [];
  const g = skill.gap;
  if (g && skill.required !== null && skill.current !== null) {
    reasons.push({
      label: "Target role",
      text: `${role} needs this at ${skill.required}% (${levelName(skill.required).toLowerCase()}), and your analysis rates it ${PRIORITY_WORD[skill.tier]} for the role.`,
    });
    const short = skill.required - skill.current;
    reasons.push({
      label: "Skill gap",
      text:
        skill.current === 0
          ? "Nothing in your evidence shows this skill yet."
          : short > 0
            ? `You're at ${skill.current}%, ${short} points short of the level.`
            : `You're at ${skill.current}%, which meets the level. What's left is proving it.`,
    });
    const stage = SIGNAL_STAGES.find((s) => s.key === skill.evidence);
    if (stage) {
      const sources = g.evidence_count ? ` It rests on ${g.evidence_count} source${g.evidence_count === 1 ? "" : "s"}.` : "";
      const checked = g.has_assessment && typeof g.assessment_score === "number" ? ` Your knowledge check scored ${pct(g.assessment_score)}%.` : "";
      reasons.push({ label: "Evidence", text: `${stage.label}: ${stage.hint.charAt(0).toLowerCase()}${stage.hint.slice(1)}.${sources}${checked}` });
    }
  } else {
    reasons.push({ label: "Target role", text: `Part of the plan INAURA built for ${role}. Your latest analysis doesn't score this skill.` });
  }

  const unmet = skill.prerequisites.filter((p) => !p.met).map((p) => p.name);
  const met = skill.prerequisites.filter((p) => p.met).map((p) => p.name);
  const order: string[] = [];
  if (unmet.length) order.push(`It comes after ${joinNames(unmet)}, which ${unmet.length === 1 ? "isn't" : "aren't"} finished yet.`);
  else if (met.length) order.push(`It builds on ${joinNames(met)}, which you've finished.`);
  if (skill.unlocks.length) order.push(`${joinNames(skill.unlocks)} ${skill.unlocks.length === 1 ? "builds" : "build"} on it, so it's scheduled first.`);
  if (order.length) reasons.push({ label: "Prerequisite", text: order.join(" ") });

  const span = skill.firstWeek === skill.lastWeek ? `week ${skill.firstWeek}` : `weeks ${skill.firstWeek}–${skill.lastWeek}`;
  reasons.push({
    label: "Sequence",
    text: `Skill ${skill.order + 1} of ${journey.skills.length} in your plan, scheduled for ${span} of ${journey.weekCount}.`,
  });
  return reasons;
}

/** Why a checkpoint sits where it does, in two or three plain sentences */
export function stageReasons(stage: JourneyStage, journey: Pick<Journey, "stages" | "weekCount">, role: string): string[] {
  const out: string[] = [];
  const tiers = new Set(stage.skills.map((s) => s.tier));
  if (tiers.size === 1) {
    const t = stage.skills[0].tier;
    out.push(
      t === "critical"
        ? `Your analysis rates every skill here critical for ${role}.`
        : t === "high"
          ? `Your analysis rates these skills high priority for ${role}.`
          : `These skills are lower priority for ${role}, so they come after the critical and high-priority ones.`
    );
  } else {
    out.push(`It mixes priorities because some skills here are needed before later ones.`);
  }
  const openers = stage.skills.filter((s) => s.unlocks.length > 0);
  if (openers.length) {
    const first = openers[0];
    out.push(`${first.shortName} comes early because ${joinNames(first.unlocks)} ${first.unlocks.length === 1 ? "builds" : "build"} on it.`);
  }
  const span = stage.firstWeek === stage.lastWeek ? `week ${stage.firstWeek}` : `weeks ${stage.firstWeek}–${stage.lastWeek}`;
  out.push(`Checkpoint ${stage.index + 1} of ${journey.stages.length}, planned for ${span} of ${journey.weekCount}.`);
  return out;
}

/** The analysis's own next step for a skill, when it gave one */
export const missingFor = (skill: JourneySkill) => skill.gap?.actionable_advice?.trim() || null;

/* ---------------- Career horizon ---------------- */

export type Horizon = {
  role: string;
  /** False when the latest analysis was run for a different role than this plan */
  sameRole: boolean;
  readiness: number | null;
  /** Average confidence behind the analysis's skill scores, 0–100 */
  confidence: number | null;
  coverage: { withEvidence: number; total: number } | null;
  analysedAt: string | null;
  /** Evidence changed, or scoring was updated, since the analysis ran */
  outdated: boolean;
  /** Tasks finished since the analysis ran, which it can't reflect yet */
  tasksSinceAnalysis: number;
};

/** The skills readiness is scored on: the role's own requirements, not portfolio extras */
const roleGaps = (gaps: SkillGap[]) => {
  const target = gaps.filter((g) => !g.is_portfolio);
  return target.length ? target : gaps;
};

export function buildHorizon(role: string, analysis: AnalysisResult | null, gaps: SkillGap[], weeks: RoadmapWeek[]): Horizon {
  const sameRole = !!analysis && keyOf(analysis.target_role) === keyOf(role);
  const scored = sameRole ? roleGaps(gaps) : [];
  const since = sameRole && analysis?.created_at ? new Date(analysis.created_at).getTime() : NaN;
  const tasksSinceAnalysis = Number.isNaN(since)
    ? 0
    : weeks
        .flatMap((w) => w.tasks ?? [])
        .filter((t) => t.status === "completed" && t.completed_at && new Date(t.completed_at).getTime() > since).length;
  return {
    role,
    sameRole,
    readiness: sameRole && analysis ? pct(analysis.readiness_score) : null,
    confidence: sameRole && analysis ? pct(analysis.evidence_component) : null,
    coverage: scored.length ? { withEvidence: scored.filter((g) => classifySkill(g) !== "none").length, total: scored.length } : null,
    analysedAt: sameRole && analysis ? analysis.created_at : null,
    outdated: sameRole && !!analysis && (analysis.evidence_changed === true || analysis.scoring_outdated === true),
    tasksSinceAnalysis,
  };
}

/* ---------------- "What changes if you move?" ---------------- */

/**
 * The readiness formula, as the analysis engine applies it (backend skill_engine.readiness):
 * 0.45 × skill + 0.25 × industry + 0.30 × evidence. It is checked against each analysis's own
 * stored numbers before anything is projected, so a change on the server switches projection
 * off instead of showing a wrong number.
 */
export const READINESS_WEIGHTS = { skill: 0.45, industry: 0.25, evidence: 0.3 } as const;

export type ReadinessModel =
  | { ok: false; reason: string }
  | {
      ok: true;
      /** Readiness now, 0–1 */
      now: number;
      /** Evidence confidence, held where it is in every projection (0–100) */
      evidence: number;
      /** How much reaching the required level in one skill adds, 0–1, by skill key */
      impact: Map<string, number>;
    };

export function readinessModel(role: string, analysis: AnalysisResult | null, gaps: SkillGap[]): ReadinessModel {
  if (!analysis) return { ok: false, reason: "Run your analysis to see how each skill would move your readiness." };
  if (keyOf(analysis.target_role) !== keyOf(role)) {
    return { ok: false, reason: `Your latest analysis is for ${analysis.target_role}, not ${role}. Run it for ${role} to see projections.` };
  }
  if (analysis.scoring_outdated) {
    return { ok: false, reason: "Your analysis was scored with an older formula. Re-run it to see projections." };
  }
  const scored = roleGaps(gaps);
  const totalImportance = scored.reduce((sum, g) => sum + Math.max(0, g.importance || 0), 0);
  if (!scored.length || totalImportance <= 0) {
    return { ok: false, reason: "Your analysis has no role requirements to project from. Re-run it to see projections." };
  }

  const share = (g: SkillGap) => (g.required_level <= 0 ? 1 : 1 - Math.min(1, clamp01(g.gap) / g.required_level));
  const skill = scored.reduce((sum, g) => sum + g.importance * clamp01(g.current_proficiency), 0) / totalImportance;
  const industry = scored.reduce((sum, g) => sum + g.importance * share(g), 0) / totalImportance;
  const formula =
    READINESS_WEIGHTS.skill * analysis.skill_component +
    READINESS_WEIGHTS.industry * analysis.industry_component +
    READINESS_WEIGHTS.evidence * analysis.evidence_component;
  const matches =
    Math.abs(skill - analysis.skill_component) < 0.01 &&
    Math.abs(industry - analysis.industry_component) < 0.01 &&
    Math.abs(formula - analysis.readiness_score) < 0.005;
  if (!matches) {
    return { ok: false, reason: "INAURA can't reproduce your last readiness score exactly, so it won't guess. Re-run your analysis to see projections." };
  }

  const impact = new Map<string, number>();
  for (const g of scored) {
    const toLevel = Math.max(0, g.required_level - clamp01(g.current_proficiency));
    const gain =
      (READINESS_WEIGHTS.skill * g.importance * toLevel + READINESS_WEIGHTS.industry * g.importance * (1 - share(g))) / totalImportance;
    for (const name of [g.skills?.canonical_name, g.canonical_name, g.skill, g.skills?.display_name]) {
      const k = keyOf(name);
      if (k && !impact.has(k)) impact.set(k, gain);
    }
  }
  return { ok: true, now: clamp01(analysis.readiness_score), evidence: pct(analysis.evidence_component), impact };
}

/** What readiness a skill adds, 0–1 (0 for skills the role's score doesn't include) */
export const impactOf = (model: Extract<ReadinessModel, { ok: true }>, skill: Pick<JourneySkill, "key" | "name">) =>
  model.impact.get(skill.key) ?? model.impact.get(keyOf(skill.name)) ?? 0;

export type ProjectionResult = {
  now: number;
  projected: number;
  /** Whole points, the way the page shows readiness */
  delta: number;
  minutes: number;
  /** Checkpoints every one of whose skills would then be done */
  clears: number[];
  /** Chosen skills still waiting on a prerequisite that isn't chosen or done */
  waiting: { skill: string; needs: string[] }[];
};

export function project(
  model: Extract<ReadinessModel, { ok: true }>,
  journey: Pick<Journey, "skills" | "stages">,
  keys: Set<string>
): ProjectionResult {
  const chosen = journey.skills.filter((s) => keys.has(s.key));
  const gain = chosen.reduce((sum, s) => sum + impactOf(model, s), 0);
  const projected = Math.min(1, model.now + gain);
  const now = Math.round(model.now * 100);
  const after = Math.round(projected * 100);
  return {
    now,
    projected: after,
    delta: after - now,
    minutes: chosen.reduce((sum, s) => sum + s.remainingMinutes, 0),
    clears: journey.stages
      .filter((st) => st.status !== "done" && st.skills.every((s) => s.tasksDone || s.state === "proven" || keys.has(s.key)))
      .map((st) => st.index),
    waiting: chosen
      .map((s) => ({ skill: s.shortName, needs: s.prerequisites.filter((p) => !p.met && !keys.has(p.key)).map((p) => p.name) }))
      .filter((w) => w.needs.length > 0),
  };
}

/** Readable hours: "45 min", "6 h", "12.5 h" */
export function readableHours(minutes: number) {
  if (minutes < 60) return `${Math.round(minutes)} min`;
  const h = minutes / 60;
  return `${h >= 10 ? Math.round(h) : Math.round(h * 2) / 2} h`;
}
