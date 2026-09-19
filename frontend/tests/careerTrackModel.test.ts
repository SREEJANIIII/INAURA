import { describe, it } from "node:test";
import assert from "node:assert";
import {
  assessmentFor,
  buildTrack,
  currentSkill,
  estimateReadiness,
  findRole,
  levelName,
  orderByPrerequisites,
  phaseFor,
  statusOf,
  toId,
} from "../src/components/career-track/careerTrackModel.ts";
import type { AnalysisResult } from "../src/services/analysis.ts";
import type { AvailableAssessment } from "../src/services/assessment.ts";
import type { CapabilityMap, SkillCapability } from "../src/services/capability.ts";
import type { RoleSummary } from "../src/services/industry.ts";

const role = { title: "Frontend Developer", slug: "frontend_developer", category: "Software Engineering", description: "Builds UIs." } as RoleSummary;

const cap = (skill: string, proficiency: number, required: number, extra: Partial<SkillCapability> = {}) =>
  ({
    skill,
    slug: skill,
    role: role.title,
    proficiency,
    confidence: 0.5,
    required_level: required,
    importance: 0.8,
    status: "developing",
    category: "Frontend",
    prerequisites: [],
    capabilities: [],
    missing_capabilities: [],
    evidence_sources: [],
    ...extra,
  }) as unknown as SkillCapability;

const map = (skills: SkillCapability[]) => ({ role: role.title, skills }) as CapabilityMap;

describe("ids", () => {
  it("turns role titles and backend slugs into URL ids", () => {
    assert.equal(toId("Frontend Developer"), "frontend-developer");
    assert.equal(toId("html_css"), "html-css");
    assert.equal(findRole([role], "frontend-developer"), role);
    assert.equal(findRole([role], "vlsi-engineer"), undefined);
  });
});

describe("statusOf", () => {
  it("completes a skill only once it reaches the required level", () => {
    assert.equal(statusOf({ currentProgress: 90, requiredProgress: 90 }, true), "completed");
    assert.equal(statusOf({ currentProgress: 40, requiredProgress: 90 }, true), "in-progress");
  });
  it("locks only untouched skills with an unmet prerequisite", () => {
    assert.equal(statusOf({ currentProgress: 0, requiredProgress: 80 }, false), "locked");
    assert.equal(statusOf({ currentProgress: 0, requiredProgress: 80 }, true), "not-started");
    // Evidence for the skill itself beats the prerequisite rule
    assert.equal(statusOf({ currentProgress: 30, requiredProgress: 80 }, false), "in-progress");
  });
});

describe("buildTrack", () => {
  const skills = [
    cap("javascript", 0.72, 0.9, { category: "Programming", capabilities: [
      { id: "a", title: "Async", summary: "", status: "demonstrated" },
      { id: "b", title: "DOM", summary: "", status: "developing" },
      { id: "c", title: "Modules", summary: "", status: "unverified" },
    ] as SkillCapability["capabilities"] }),
    cap("html_css", 0.9, 0.85, { category: "Frontend" }),
    cap("react", 0, 0.85, { prerequisites: ["javascript", "html_css"] }),
    cap("typescript", 0.2, 0.7, { prerequisites: ["javascript"], importance: 0.6 }),
  ];

  it("derives progress, gap, levels, topics and status from the capability map", () => {
    const track = buildTrack({ role, map: map(skills) });
    const js = track.skills.find((s) => s.id === "javascript")!;
    assert.equal(js.currentProgress, 72);
    assert.equal(js.requiredProgress, 90);
    assert.equal(js.gap, 18);
    assert.equal(js.currentLevel, "Advanced");
    assert.equal(js.completedTopics, 1);
    assert.equal(js.totalTopics, 3);
    assert.equal(js.name, "JavaScript");
    const react = track.skills.find((s) => s.id === "react")!;
    assert.equal(react.status, "locked", "JavaScript isn't at the required level yet");
    assert.deepEqual(track.counts, { completed: 1, "in-progress": 2, "not-started": 0, locked: 1 });
  });

  it("ranks priority skills by required minus current", () => {
    const track = buildTrack({ role, map: map(skills) });
    // React is locked behind JavaScript, so it waits; TypeScript (started) and JavaScript lead
    assert.deepEqual(track.priority.map((s) => s.id), ["typescript", "javascript"]);
  });

  it("groups skills into ordered phases with prerequisites first", () => {
    const track = buildTrack({ role, map: map(skills) });
    assert.deepEqual(track.phases.map((p) => p.id), ["foundations", "core-stack"]);
    const core = track.phases.find((p) => p.id === "core-stack")!;
    assert.ok(core.skills.findIndex((s) => s.id === "html-css") < core.skills.findIndex((s) => s.id === "react"));
  });

  it("uses the official readiness when the latest analysis was for this role", () => {
    const official = buildTrack({ role, map: map(skills), analysis: { target_role: "Frontend Developer", readiness_score: 0.64 } as AnalysisResult });
    assert.deepEqual(official.readiness, { value: 64, source: "analysis" });
    const other = buildTrack({ role, map: map(skills), analysis: { target_role: "Data Analyst", readiness_score: 0.9 } as AnalysisResult });
    assert.equal(other.readiness.source, "estimate");
  });
});

describe("estimateReadiness", () => {
  it("weights each skill by importance and caps it at the requirement", () => {
    assert.equal(
      estimateReadiness([
        { currentProgress: 100, requiredProgress: 50, importance: 100 },
        { currentProgress: 0, requiredProgress: 80, importance: 100 },
      ]),
      50
    );
    assert.equal(estimateReadiness([]), 0);
  });
});

describe("helpers", () => {
  it("maps categories onto phases and levels onto names", () => {
    assert.equal(phaseFor("DevOps/Cloud").id, "production");
    assert.equal(phaseFor("DATA / DATABASE").id, "data");
    assert.equal(levelName(0), "Not started");
    assert.equal(levelName(90), "Expert");
  });

  it("orders any list so prerequisites come before dependants", () => {
    const track = buildTrack({ role, map: map([cap("react", 0, 0.8, { prerequisites: ["javascript"], importance: 1 }), cap("javascript", 0, 0.8, { importance: 0.1 })]) });
    assert.deepEqual(orderByPrerequisites(track.skills).map((s) => s.id), ["javascript", "react"]);
  });

  it("finds the assessment for a skill by key or name", () => {
    const track = buildTrack({ role, map: map([cap("html_css", 0.5, 0.8)]) });
    const found = assessmentFor(track.skills[0], [{ skill: "HTML/CSS", skill_key: "html_css" } as AvailableAssessment]);
    assert.equal(found?.skill_key, "html_css");
  });
});

describe("currentSkill", () => {
  it("points at the skill in progress, then the next one to start", () => {
    const track = buildTrack({
      role,
      map: map([
        cap("git", 0.9, 0.8, { category: "Tools" }),
        cap("javascript", 0.4, 0.9, { category: "Frontend" }),
        cap("react", 0, 0.85, { category: "Frontend" }),
      ]),
    });
    assert.equal(currentSkill(track.phases)?.id, "javascript");

    const done = buildTrack({ role, map: map([cap("git", 0.9, 0.8, { category: "Tools" }), cap("react", 0, 0.85, { category: "Frontend" })]) });
    assert.equal(currentSkill(done.phases)?.id, "react");

    const finished = buildTrack({ role, map: map([cap("git", 0.9, 0.8)]) });
    assert.equal(currentSkill(finished.phases), null);
  });
});
