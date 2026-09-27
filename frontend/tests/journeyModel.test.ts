import { describe, it } from "node:test";
import assert from "node:assert";
import {
  buildHorizon,
  buildJourney,
  groupIntoStages,
  keyOf,
  project,
  readinessModel,
  shortName,
  skillReasons,
  splitBalanced,
  stageCount,
  stageTitle,
  stateOf,
} from "../src/components/roadmap/journeyModel.ts";
import type { AnalysisResult, SkillGap } from "../src/services/analysis.ts";
import type { Roadmap, RoadmapTask, RoadmapWeek } from "../src/services/roadmap.ts";

let taskId = 0;
const task = (skill: string, type: RoadmapTask["task_type"], minutes: number, extra: Partial<RoadmapTask> = {}) =>
  ({
    id: `t${++taskId}`,
    roadmap_week_id: "w",
    skill_slug: skill,
    skill_name: skill.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
    task_type: type,
    title: `${type} ${skill}`,
    description: "",
    estimated_minutes: minutes,
    sequence_order: taskId,
    status: "not_started",
    completion_percentage: 0,
    resources: [],
    validation_method: "",
    why_this_task: "",
    ...extra,
  }) as RoadmapTask;

const week = (n: number, tasks: RoadmapTask[]) =>
  ({ id: `w${n}`, roadmap_id: "r", week_number: n, title: `Week ${n}`, objective: "", estimated_hours: 10, skills: [], status: "current", completion_percentage: 0, tasks }) as RoadmapWeek;

const gap = (name: string, current: number, required: number, extra: Partial<SkillGap> = {}) =>
  ({
    id: name,
    skill_id: name,
    skills: { canonical_name: name, display_name: name, category: "Programming" },
    current_proficiency: current,
    required_level: required,
    gap: Math.max(0, required - current),
    importance: 0.8,
    confidence: 0.5,
    priority_category: "critical",
    gap_type: "skill_gap",
    evidence_state: current > 0 ? "evidence_estimate" : "no_evidence",
    evidence_count: current > 0 ? 1 : 0,
    is_portfolio: false,
    ...extra,
  }) as unknown as SkillGap;

const explanations = (pairs: Record<string, string[]>) =>
  ({
    skill_explanations: Object.entries(pairs).map(([skill_slug, prerequisites_required]) => ({ skill_slug, prerequisites_required })),
  }) as unknown as Pick<Roadmap, "skill_explanations">;

describe("names", () => {
  it("normalises skill names to one key", () => {
    assert.equal(keyOf("REST APIs"), "rest_apis");
    assert.equal(keyOf("rest-apis"), "rest_apis");
    assert.equal(keyOf(" Node.js "), "node_js");
  });

  it("shortens long names for map labels only when it knows how", () => {
    assert.equal(shortName("Data Structures & Algorithms"), "DSA");
    assert.equal(shortName("System Design"), "System Design");
  });

  it("titles a checkpoint by its skills, cutting long lists short", () => {
    assert.equal(stageTitle(["Python"]), "Python");
    assert.equal(stageTitle(["Python", "DSA"]), "Python & DSA");
    assert.equal(stageTitle(["OOP", "Java", "SQL", "Git"]), "OOP, Java, SQL & Git");
    assert.equal(stageTitle(["Responsive Design", "AWS", "NumPy", "Caching", "Pandas"]), "Responsive Design, AWS + 3 more");
  });
});

describe("checkpoints", () => {
  it("gives a plan at least three checkpoints when it can, and at most six", () => {
    assert.deepEqual([0, 1, 2, 5, 13, 24, 40].map(stageCount), [0, 1, 2, 3, 4, 6, 6]);
  });

  it("splits by effort without reordering or leaving a group empty", () => {
    const items = [30, 30, 30, 90, 10, 10].map((minutes, i) => ({ minutes, i }));
    const groups = splitBalanced(items, 3);
    assert.equal(groups.length, 3);
    assert.deepEqual(groups.flat().map((g) => g.i), [0, 1, 2, 3, 4, 5]);
    assert.ok(groups.every((g) => g.length > 0));
  });

  it("cuts at priority tiers first", () => {
    const skills = [
      { minutes: 60, tier: "critical" as const, n: "a" },
      { minutes: 60, tier: "critical" as const, n: "b" },
      { minutes: 60, tier: "critical" as const, n: "c" },
      { minutes: 60, tier: "high" as const, n: "d" },
      { minutes: 60, tier: "other" as const, n: "e" },
      { minutes: 60, tier: "other" as const, n: "f" },
    ];
    const stages = groupIntoStages(skills);
    assert.equal(stages.length, 3);
    for (const stage of stages) assert.equal(new Set(stage.map((s) => s.tier)).size, 1, "a checkpoint never mixes tiers here");
    assert.deepEqual(stages.flat().map((s) => s.n), ["a", "b", "c", "d", "e", "f"]);
  });
});

describe("skill states", () => {
  const base = { gap: null, evidence: null, tier: "critical" as const, started: false, tasksDone: false, inCurrentWeek: false, blocked: false };

  it("is proven only when the analysis confirms the level with strong evidence", () => {
    const met = gap("python", 0.8, 0.75, { confidence: 0.7 });
    assert.equal(stateOf({ ...base, gap: met, evidence: "verified" }), "proven");
    // Level met, evidence weak: the skill may be there, the proof isn't
    assert.equal(stateOf({ ...base, gap: met, evidence: "claimed" }), "needs-proof");
  });

  it("is building while you're on it, and needs proof once the tasks are done", () => {
    assert.equal(stateOf({ ...base, started: true }), "building");
    assert.equal(stateOf({ ...base, inCurrentWeek: true }), "building");
    assert.equal(stateOf({ ...base, tasksDone: true, gap: gap("python", 0.5, 0.75) }), "needs-proof");
  });

  it("flags an important skill with no evidence as a priority gap, ahead of it being locked", () => {
    const missing = gap("dsa", 0, 0.85);
    assert.equal(stateOf({ ...base, gap: missing, evidence: "none", blocked: true }), "priority-gap");
    assert.equal(stateOf({ ...base, gap: missing, evidence: "none", tier: "other", blocked: true }), "locked");
    assert.equal(stateOf({ ...base, gap: gap("java", 0.4, 0.75), evidence: "evidence" }), "upcoming");
  });
});

describe("building the journey", () => {
  const weeks = [
    week(1, [task("python", "learn", 60, { status: "completed", completion_percentage: 100 }), task("python", "build", 60)]),
    week(2, [task("python", "validate", 60), task("rest_apis", "learn", 120)]),
    week(3, [task("rest_apis", "build", 120, { status: "skipped" }), task("git", "learn", 90)]),
  ];
  const gaps = [gap("python", 0.5, 0.75), gap("rest_apis", 0.2, 0.8), gap("git", 0, 0.7, { priority_category: "high" })];

  it("puts skills in schedule order and measures progress by planned time, leaving skipped work out", () => {
    const j = buildJourney({ weeks, roadmap: explanations({ rest_apis: ["python"] }), gaps });
    assert.deepEqual(j.skills.map((s) => s.key), ["python", "rest_apis", "git"]);
    assert.equal(j.totalMinutes, 60 + 60 + 60 + 120 + 90);
    assert.equal(j.doneMinutes, 60);
    assert.equal(j.currentWeek, 1);
    assert.equal(j.currentSkill?.key, "python");
  });

  it("locks a skill behind an unfinished prerequisite and records what it unlocks", () => {
    const j = buildJourney({ weeks, roadmap: explanations({ rest_apis: ["python"] }), gaps });
    const rest = j.skills.find((s) => s.key === "rest_apis")!;
    assert.equal(rest.state, "locked");
    assert.deepEqual(rest.prerequisites, [{ key: "python", name: "Python", met: false }]);
    assert.deepEqual(j.skills[0].unlocks, ["Rest Apis"]);
    assert.equal(j.skills.find((s) => s.key === "git")?.state, "priority-gap");
  });

  it("moves the marker along as tasks are finished", () => {
    const j = buildJourney({ weeks, gaps });
    assert.ok(j.position > 0 && j.position < 1, "part-way to the first checkpoint");
    const allPython = weeks.map((w) => ({
      ...w,
      tasks: (w.tasks ?? []).map((t) => (t.skill_slug === "python" ? { ...t, status: "completed" as const, completion_percentage: 100 } : t)),
    }));
    const after = buildJourney({ weeks: allPython, gaps });
    assert.equal(after.stages[0].status, "done");
    assert.equal(after.currentStage, 1);
    assert.equal(after.skills[0].state, "needs-proof", "done work waits for the analysis to confirm it");
  });

  it("explains a skill from its real numbers", () => {
    const j = buildJourney({ weeks, roadmap: explanations({ rest_apis: ["python"] }), gaps });
    const reasons = skillReasons(j.skills[1], j, "Backend Developer");
    assert.deepEqual(reasons.map((r) => r.label), ["Target role", "Skill gap", "Evidence", "Prerequisite", "Sequence"]);
    assert.match(reasons[1].text, /20%, 60 points short/);
    assert.match(reasons[3].text, /after Python/);
  });
});

describe("readiness projection", () => {
  const gaps = [
    gap("python", 0.5, 0.75, { importance: 0.8 }),
    gap("dsa", 0, 0.85, { importance: 1 }),
    gap("react", 0.3, 0.5, { importance: 0.3, is_portfolio: true }),
  ];
  const scored = gaps.filter((g) => !g.is_portfolio);
  const imp = scored.reduce((s, g) => s + g.importance, 0);
  const skill = scored.reduce((s, g) => s + g.importance * g.current_proficiency, 0) / imp;
  const industry = scored.reduce((s, g) => s + g.importance * (1 - Math.min(1, g.gap / g.required_level)), 0) / imp;
  const evidence = 0.3;
  const analysis = {
    target_role: "Software Engineer",
    skill_component: skill,
    industry_component: industry,
    evidence_component: evidence,
    readiness_score: 0.45 * skill + 0.25 * industry + 0.3 * evidence,
    created_at: "2026-09-01T00:00:00Z",
  } as AnalysisResult;

  it("projects only when it can reproduce the analysis's own score", () => {
    const model = readinessModel("Software Engineer", analysis, gaps);
    assert.ok(model.ok);
    const off = readinessModel("Software Engineer", { ...analysis, readiness_score: analysis.readiness_score + 0.05 }, gaps);
    assert.equal(off.ok, false);
    assert.equal(readinessModel("Data Scientist", analysis, gaps).ok, false);
    assert.equal(readinessModel("Software Engineer", null, gaps).ok, false);
  });

  it("adds up each chosen skill reaching its level, and portfolio extras add nothing", () => {
    const model = readinessModel("Software Engineer", analysis, gaps);
    assert.ok(model.ok);
    const weeks = [week(1, [task("python", "learn", 120), task("dsa", "learn", 180), task("react", "learn", 60)])];
    const j = buildJourney({ weeks, gaps });
    const both = project(model, j, new Set(["python", "dsa"]));
    // With every scored skill at its level, skill = weighted required level and industry = 1
    const full = 0.45 * ((0.8 * 0.75 + 1 * 0.85) / imp) + 0.25 * 1 + 0.3 * evidence;
    assert.equal(both.projected, Math.round(full * 100));
    assert.equal(both.minutes, 300);
    assert.equal(project(model, j, new Set(["react"])).delta, 0);
  });

  it("reports coverage from the role's own skills and counts work done since the analysis", () => {
    const weeks = [week(1, [task("python", "learn", 60, { status: "completed", completion_percentage: 100, completed_at: "2026-09-10T00:00:00Z" })])];
    const h = buildHorizon("Software Engineer", analysis, gaps, weeks);
    assert.deepEqual(h.coverage, { withEvidence: 1, total: 2 });
    assert.equal(h.readiness, Math.round(analysis.readiness_score * 100));
    assert.equal(h.tasksSinceAnalysis, 1);
    assert.equal(buildHorizon("Data Scientist", analysis, gaps, weeks).readiness, null);
  });
});
