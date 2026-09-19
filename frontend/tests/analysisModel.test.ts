import { describe, it } from "node:test";
import assert from "node:assert";
import {
  evidenceKindsFor,
  joinOr,
  quadrantOf,
  roadmapLinkFor,
  sourceUsage,
  splitGaps,
} from "../src/components/analysis/analysisModel.ts";
import type { SkillGap } from "../src/services/analysis.ts";
import type { Evidence, GithubRepo, Project } from "../src/services/evidence.ts";
import type { RoadmapWeek } from "../src/services/roadmap.ts";

const gap = (name: string, extra: Partial<SkillGap> = {}) =>
  ({
    id: name,
    skills: { display_name: name, canonical_name: name.toLowerCase(), category: "x" },
    current_proficiency: 0.3,
    confidence: 0.3,
    required_level: 0.7,
    gap: 0.4,
    priority_score: 10,
    ...extra,
  }) as SkillGap;

describe("quadrantOf", () => {
  it("uses the backend's quadrant when present", () => {
    assert.equal(quadrantOf(gap("A", { quadrant: "confirmed_gap", current_proficiency: 0.9, confidence: 0.9 })), "confirmed_gap");
  });
  it("falls back to the 0.60 / 0.50 thresholds", () => {
    assert.equal(quadrantOf(gap("A", { current_proficiency: 0.6, confidence: 0.5 })), "strong_validated");
    assert.equal(quadrantOf(gap("A", { current_proficiency: 0.6, confidence: 0.49 })), "unverified_claim");
    assert.equal(quadrantOf(gap("A", { current_proficiency: 0.59, confidence: 0.5 })), "confirmed_gap");
    assert.equal(quadrantOf(gap("A", { current_proficiency: 0.1, confidence: 0.1 })), "exploratory");
  });
});

describe("splitGaps", () => {
  it("ranks critical gaps first even when another gap scores higher", () => {
    const { priority } = splitGaps([
      gap("High", { priority_category: "high", priority_score: 90 }),
      gap("Critical", { priority_category: "critical", priority_score: 40 }),
      gap("Covered", { gap: 0 }),
    ]);
    assert.deepEqual(priority.map((g) => g.id), ["Critical", "High"]);
  });

  it("keeps secondary skills out of the role lists and flags unproven claims as evidence gaps", () => {
    const groups = splitGaps([
      gap("Claim", { current_proficiency: 0.8, confidence: 0.2, gap: 0 }),
      gap("Extra", { is_portfolio: true }),
    ]);
    assert.deepEqual(groups.target.map((g) => g.id), ["Claim"]);
    assert.deepEqual(groups.secondary.map((g) => g.id), ["Extra"]);
    assert.deepEqual(groups.evidence.map((g) => g.id), ["Claim"]);
  });
});

describe("evidenceKindsFor", () => {
  it("maps evidence sources and assessments onto the kinds of proof", () => {
    const kinds = evidenceKindsFor(
      gap("A", {
        has_assessment: true,
        evidence_sources: [
          { source_type: "github", source_label: "repo" },
          { source_type: "leetcode", source_label: "lc" },
        ] as SkillGap["evidence_sources"],
      })
    );
    const present = kinds.filter((k) => k.present).map((k) => k.kind.key);
    assert.deepEqual(present, ["github", "coding", "assessment"]);
  });
});

describe("roadmapLinkFor", () => {
  const weeks = [
    { id: "w1", week_number: 1, title: "Basics", skills: ["Git"], tasks: [] },
    { id: "w4", week_number: 4, title: "Design", skills: [], tasks: [{ skill_name: "System Design" }] },
  ] as unknown as RoadmapWeek[];

  it("finds the week a gap is planned in, by skill or task", () => {
    const link = roadmapLinkFor(gap("System Design"), true, weeks);
    assert.equal(link.state, "planned");
    assert.equal(link.state === "planned" && link.week.week_number, 4);
  });
  it("distinguishes 'not in roadmap' from 'no roadmap'", () => {
    assert.equal(roadmapLinkFor(gap("Docker"), true, weeks).state, "missing");
    assert.equal(roadmapLinkFor(gap("Docker"), false, []).state, "none");
  });
});

describe("sourceUsage", () => {
  it("counts used items and kinds, treating repositories as GitHub", () => {
    const usage = sourceUsage(
      [{ evidence_type: "resume" }, { evidence_type: "syllabus", is_excluded: true }] as Evidence[],
      [{ id: "p" }] as Project[],
      [{ full_name: "a/b", is_excluded: false }, { full_name: "a/c", is_excluded: true }] as GithubRepo[]
    );
    assert.deepEqual(usage, { kinds: 3, used: 3, total: 5, excluded: 2 });
  });
});

describe("joinOr", () => {
  it("joins lists in plain English", () => {
    assert.equal(joinOr(["GitHub"]), "GitHub");
    assert.equal(joinOr(["GitHub", "projects", "coursework"]), "GitHub, projects or coursework");
  });
});
