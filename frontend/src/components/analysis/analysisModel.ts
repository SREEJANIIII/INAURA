/**
 * Shapes the analysis data INAURA already returns (skill gaps, evidence, roadmap) for the analysis page.
 * Pure functions only, so the page stays declarative and the rules are testable.
 * Thresholds mirror the backend's skill engine (proficiency 0.60, confidence 0.50).
 */
import type { AnalysisResult, SkillGap } from "../../services/analysis";
import type { Evidence, GithubRepo, Project } from "../../services/evidence";
import type { RoadmapWeek } from "../../services/roadmap";

export const PROFICIENCY_THRESHOLD = 0.6;
export const CONFIDENCE_THRESHOLD = 0.5;

export const pct = (v: number | null | undefined) => Math.round(Math.max(0, Math.min(1, v ?? 0)) * 100);

export const skillName = (g: SkillGap) =>
  g.skills?.display_name || g.skills?.canonical_name || g.canonical_name || g.skill || "Unnamed skill";

/* ---------------- Quadrants ---------------- */

export type QuadrantKey = "strong_validated" | "unverified_claim" | "confirmed_gap" | "exploratory";

export const QUADRANTS: Record<QuadrantKey, { title: string; short: string; guidance: string }> = {
  strong_validated: {
    title: "Strong and proven",
    short: "Strong",
    guidance: "High skill backed by solid independent evidence. Lead with it in applications and interviews.",
  },
  unverified_claim: {
    title: "Claimed, not yet proven",
    short: "Unproven",
    guidance: "Looks strong, but little independent evidence supports it. An assessment or a public project would confirm it.",
  },
  confirmed_gap: {
    title: "Proven gap",
    short: "Gap",
    guidance: "Your evidence clearly shows this is below what the role needs. This is a real learning target.",
  },
  exploratory: {
    title: "Unclear",
    short: "Unclear",
    guidance: "Too little evidence to judge either way. Add evidence or take an assessment before drawing conclusions.",
  },
};

export function quadrantOf(g: SkillGap): QuadrantKey {
  if (g.quadrant && g.quadrant in QUADRANTS) return g.quadrant as QuadrantKey;
  const strong = g.current_proficiency >= PROFICIENCY_THRESHOLD;
  const confident = g.confidence >= CONFIDENCE_THRESHOLD;
  if (strong) return confident ? "strong_validated" : "unverified_claim";
  return confident ? "confirmed_gap" : "exploratory";
}

/* ---------------- Priority and confidence wording ---------------- */

export type Priority = { label: string; tone: "critical" | "high" | "medium" | "low" | "covered" };

export function priorityOf(g: SkillGap): Priority {
  const c = g.priority_category;
  if (c === "critical") return { label: "Critical", tone: "critical" };
  if (c === "high") return { label: "High priority", tone: "high" };
  if (c === "medium") return { label: "Medium priority", tone: "medium" };
  if (c === "low") return { label: "Low priority", tone: "low" };
  if (c === "covered") return { label: "Covered", tone: "covered" };
  // Same score bands as the previous results page
  const s = g.priority_score ?? 0;
  if (s >= 40) return { label: "Critical", tone: "critical" };
  if (s >= 25) return { label: "High priority", tone: "high" };
  if (s >= 10) return { label: "Medium priority", tone: "medium" };
  if (s > 0) return { label: "Low priority", tone: "low" };
  return { label: "Covered", tone: "covered" };
}

export function confidenceWord(conf: number) {
  if (conf >= 0.7) return "High";
  if (conf >= 0.4) return "Medium";
  if (conf > 0) return "Low";
  return "None";
}

export function levelWord(prof: number) {
  if (prof >= 0.75) return "Advanced";
  if (prof >= 0.5) return "Intermediate";
  if (prof > 0.2) return "Basic";
  if (prof > 0) return "Beginner";
  return "Not shown";
}

/* ---------------- Evidence kinds behind a skill ---------------- */

/** phrase: how the kind reads mid-sentence, e.g. "no GitHub or coursework" */
export type EvidenceKind = { key: string; label: string; phrase: string };

/** The kinds of proof INAURA weighs, in the order students add them */
export const EVIDENCE_KINDS: EvidenceKind[] = [
  { key: "github", label: "GitHub", phrase: "GitHub" },
  { key: "projects", label: "Projects", phrase: "projects" },
  { key: "coding", label: "Coding platforms", phrase: "coding platforms" },
  { key: "coursework", label: "Coursework", phrase: "coursework" },
  { key: "certifications", label: "Certifications", phrase: "certifications" },
  { key: "resume", label: "Resume or LinkedIn", phrase: "resume or LinkedIn" },
  { key: "assessment", label: "INAURA assessment", phrase: "an INAURA assessment" },
];

export function kindOfSource(sourceType: string | undefined | null): string | null {
  const s = (sourceType || "").toLowerCase();
  if (!s) return null;
  if (s.includes("assessment")) return "assessment";
  if (s.includes("github") || s.includes("repo")) return "github";
  if (s.includes("project")) return "projects";
  if (s.includes("leetcode") || s.includes("codeforces") || s.includes("kaggle")) return "coding";
  if (s.includes("syllabus") || s.includes("coursework")) return "coursework";
  if (s.includes("cert")) return "certifications";
  if (s.includes("resume") || s.includes("linkedin") || s.includes("self")) return "resume";
  return null;
}

/** Which kinds of proof back this skill, e.g. GitHub ✓, Assessment ✕ */
export function evidenceKindsFor(g: SkillGap): { kind: EvidenceKind; present: boolean }[] {
  const present = new Set((g.evidence_sources ?? []).map((s) => kindOfSource(s.source_type)).filter(Boolean));
  if (g.has_assessment) present.add("assessment");
  return EVIDENCE_KINDS.map((kind) => ({ kind, present: present.has(kind.key) }));
}

export const sourceLabels = (g: SkillGap, limit = 4) =>
  Array.from(new Set((g.evidence_sources ?? []).map((s) => s.source_label).filter(Boolean))).slice(0, limit);

/* ---------------- Grouping the gaps ---------------- */

export function splitGaps(gaps: SkillGap[]) {
  const sorted = [...gaps].sort((a, b) => (b.priority_score ?? 0) - (a.priority_score ?? 0));
  const target = sorted.filter((g) => !g.is_portfolio);
  const secondary = sorted.filter((g) => g.is_portfolio);
  // Critical before high before medium, then by score within each band
  const rank = { critical: 0, high: 1, medium: 2, low: 3, covered: 4 } as const;
  const priority = target
    .filter((g) => g.gap > 0)
    .sort((a, b) => rank[priorityOf(a).tone] - rank[priorityOf(b).tone] || (b.priority_score ?? 0) - (a.priority_score ?? 0));
  // Skills that are claimed or required but lack independent proof — same rules as before, plus unproven claims
  const evidence = target.filter(
    (g) => g.gap_type === "evidence_gap" || (g.gap > 0 && g.confidence < 0.2) || quadrantOf(g) === "unverified_claim"
  );
  const strengths = target
    .filter(
      (g) =>
        (g.gap <= 1e-9 || g.current_proficiency >= g.required_level) &&
        g.confidence >= 0.35 &&
        g.current_proficiency >= 0.5 &&
        g.gap_type !== "evidence_gap"
    )
    .sort((a, b) => b.current_proficiency * b.confidence - a.current_proficiency * a.confidence);
  return { target, secondary, priority, evidence, strengths };
}

/* ---------------- Evidence sources ---------------- */

const EVIDENCE_TYPE_LABEL: Record<string, string> = {
  github: "GitHub",
  leetcode: "LeetCode",
  codeforces: "Codeforces",
  kaggle: "Kaggle",
  linkedin: "LinkedIn",
  resume: "Resume",
  syllabus: "Coursework",
  certification_file: "Certificate",
  project_doc: "Project document",
};

export const evidenceTypeLabel = (type: string) => EVIDENCE_TYPE_LABEL[type] ?? type;

export function sourceUsage(evidence: Evidence[], projects: Project[], repos: GithubRepo[]) {
  const usedEvidence = evidence.filter((e) => !e.is_excluded);
  const usedProjects = projects.filter((p) => !p.is_excluded);
  const usedRepos = repos.filter((r) => !r.is_excluded);
  const kinds = new Set<string>(usedEvidence.map((e) => e.evidence_type));
  if (usedProjects.length) kinds.add("projects");
  // Repositories are GitHub evidence, even if the GitHub profile itself was switched off
  if (usedRepos.length) kinds.add("github");
  const total = evidence.length + projects.length + repos.length;
  const used = usedEvidence.length + usedProjects.length + usedRepos.length;
  return { kinds: kinds.size, used, total, excluded: total - used };
}

/* ---------------- Roadmap connection ---------------- */

export type RoadmapLink =
  | { state: "none" }
  | { state: "missing" }
  | { state: "planned"; week: RoadmapWeek };

const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "");

export function roadmapLinkFor(g: SkillGap, hasRoadmap: boolean, weeks: RoadmapWeek[]): RoadmapLink {
  if (!hasRoadmap) return { state: "none" };
  const names = [skillName(g), g.skills?.canonical_name, g.canonical_name].filter(Boolean).map((n) => norm(n as string));
  const week = [...weeks]
    .sort((a, b) => a.week_number - b.week_number)
    .find(
      (w) =>
        (w.skills ?? []).some((s) => names.includes(norm(s))) ||
        (w.tasks ?? []).some((t) => names.includes(norm(t.skill_name || "")) || names.includes(norm(t.skill_slug || "")))
    );
  return week ? { state: "planned", week } : { state: "missing" };
}

/* ---------------- Overview ---------------- */

export function headlineInsight(analysis: AnalysisResult, groups: ReturnType<typeof splitGaps>) {
  const strong = groups.strengths.slice(0, 2).map(skillName);
  const top = groups.priority[0];
  const parts: string[] = [];
  if (strong.length === 2) parts.push(`Your strongest evidence is in ${strong[0]} and ${strong[1]}.`);
  else if (strong.length === 1) parts.push(`Your strongest evidence is in ${strong[0]}.`);
  else parts.push(`None of the skills ${analysis.target_role} roles ask for are strongly proven yet.`);
  if (top) parts.push(`${skillName(top)} is currently your largest gap.`);
  else parts.push("You have no open gaps against this role's requirements.");
  return parts.join(" ");
}

/** "a, b or c" */
export function joinOr(items: string[]) {
  if (items.length <= 1) return items.join("");
  return `${items.slice(0, -1).join(", ")} or ${items[items.length - 1]}`;
}
