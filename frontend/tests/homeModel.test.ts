import { describe, it } from "node:test";
import assert from "node:assert";
import {
  buildActions,
  buildCoverage,
  buildSignal,
  classifySkill,
  relativeDay,
  roadmapWindow,
} from "../src/components/home/homeModel.ts";
import type { SkillGap } from "../src/services/analysis.ts";
import type { Evidence, Project } from "../src/services/evidence.ts";
import type { Roadmap, RoadmapWeek } from "../src/services/roadmap.ts";

const gap = (p: number, c: number, extra: Partial<SkillGap> = {}) =>
  ({ current_proficiency: p, confidence: c, gap: 0.2, priority_score: 1, ...extra }) as SkillGap;

describe("classifySkill", () => {
  it("treats missing or overridden evidence as no evidence", () => {
    assert.equal(classifySkill(gap(0, 0)), "none");
    assert.equal(classifySkill(gap(0.8, 0.9, { evidence_state: "no_evidence" })), "none");
    assert.equal(classifySkill(gap(0.8, 0.9, { is_overridden: true })), "none");
  });

  it("uses the same proficiency/confidence thresholds as the analysis page", () => {
    assert.equal(classifySkill(gap(0.7, 0.6)), "verified");
    assert.equal(classifySkill(gap(0.7, 0.3)), "claimed");
    assert.equal(classifySkill(gap(0.4, 0.4)), "evidence");
  });

  it("counts a passed assessment as verified", () => {
    assert.equal(classifySkill(gap(0.4, 0.3, { has_assessment: true, assessment_score: 0.75 })), "verified");
  });
});

describe("buildSignal", () => {
  it("ignores portfolio skills and groups the rest by stage", () => {
    const s = buildSignal([gap(0.7, 0.6), gap(0, 0), gap(0.7, 0.6, { is_portfolio: true })]);
    assert.equal(s.total, 2);
    assert.equal(s.byStage.verified.length, 1);
    assert.equal(s.byStage.none.length, 1);
  });
});

describe("buildCoverage", () => {
  it("reports verification state per source and counts what's present", () => {
    const evidence = [
      { evidence_type: "github", verification_status: "verified" },
      { evidence_type: "leetcode", verification_status: "unverified" },
      { evidence_type: "resume", verification_status: "failed" },
    ] as Evidence[];
    const cov = buildCoverage(evidence, [{ name: "App" } as Project], []);
    const state = Object.fromEntries(cov.items.map((i) => [i.key, i.state]));
    assert.deepEqual(state, {
      github: "verified",
      practice: "added",
      resume: "failed",
      coursework: "missing",
      projects: "included",
      certs: "missing",
    });
    assert.equal(cov.presentCount, 4);
    assert.equal(cov.items.find((i) => i.key === "practice")?.noun, "LeetCode profile");
  });

  it("ignores excluded evidence", () => {
    const cov = buildCoverage([{ evidence_type: "github", verification_status: "verified", is_excluded: true } as Evidence], [], []);
    assert.equal(cov.presentCount, 0);
  });
});

describe("buildActions", () => {
  const week = (n: number, status: RoadmapWeek["status"], tasks: unknown[] = []) =>
    ({ id: `w${n}`, week_number: n, status, tasks }) as RoadmapWeek;

  it("puts this week's open roadmap tasks first", () => {
    const weeks = [
      week(1, "completed"),
      week(2, "current", [
        { id: "a", title: "Done task", status: "completed", sequence_order: 1 },
        { id: "b", title: "Open task", status: "not_started", sequence_order: 2, estimated_minutes: 30, skill_name: "SQL" },
      ]),
    ];
    const actions = buildActions({
      analysis: { id: "x" } as never,
      roadmap: { current_week_index: 2 } as Roadmap,
      weeks,
      coverage: buildCoverage([], [], []).items,
      assessable: [],
    });
    assert.equal(actions[0].kind, "task");
    assert.equal(actions[0].title, "Open task");
    assert.equal(actions[0].meta, "SQL, 30 min");
  });

  it("leaves run-analysis to the step tracker and suggests specific evidence instead", () => {
    const actions = buildActions({ analysis: null, roadmap: null, weeks: [], coverage: buildCoverage([], [], []).items, assessable: [] });
    assert.equal(actions[0].id, "add-github");
    assert.ok(!actions.some((a) => a.id === "run-analysis" || a.id === "add-evidence" || a.id === "roadmap"));
  });
});

describe("roadmapWindow", () => {
  it("keeps the current week in view with one week of context before it", () => {
    const weeks = Array.from({ length: 10 }, (_, i) => ({ id: `w${i + 1}`, week_number: i + 1, status: "locked" }) as RoadmapWeek);
    const { shown, current } = roadmapWindow({ current_week_index: 6 } as Roadmap, weeks, 4);
    assert.equal(current?.week_number, 6);
    assert.deepEqual(shown.map((w) => w.week_number), [5, 6, 7, 8]);
  });
});

describe("relativeDay", () => {
  it("describes recent days in words", () => {
    const now = new Date(2026, 8, 17, 12);
    assert.equal(relativeDay(new Date(2026, 8, 17, 8).toISOString(), now), "Today");
    assert.equal(relativeDay(new Date(2026, 8, 16, 23).toISOString(), now), "Yesterday");
    assert.equal(relativeDay(new Date(2026, 8, 13).toISOString(), now), "4 days ago");
  });
});
