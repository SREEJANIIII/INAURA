/**
 * Pure helpers for Skill Evidence Cards.
 *
 * Framework-free and deterministic: given the same skill gap payload they
 * always produce the same classification, labels, and explanation bullets.
 * Every bullet is derived strictly from fields present in the payload --
 * nothing is invented, and absence of evidence is stated explicitly.
 */

import type { EvidenceSource } from "../services/analysis";

export type EvidenceStrengthKey =
  | "strong"
  | "moderate"
  | "weak"
  | "evidence-gap"
  | "no-evidence";

export interface EvidenceStrengthInfo {
  key: EvidenceStrengthKey;
  /** Short badge label, e.g. "Strong". */
  label: string;
  /** One-line honest description of what the band means. */
  description: string;
}

const STRENGTH_INFO: Record<EvidenceStrengthKey, EvidenceStrengthInfo> = {
  strong: {
    key: "strong",
    label: "Strong",
    description: "Implementation-depth or corroborated evidence.",
  },
  moderate: {
    key: "moderate",
    label: "Moderate",
    description: "Configuration-level or single-source evidence.",
  },
  weak: {
    key: "weak",
    label: "Weak",
    description: "Mention-level or single weak signal.",
  },
  "evidence-gap": {
    key: "evidence-gap",
    label: "Evidence gap",
    description:
      "Required but lacking independent proof. Absence of submitted evidence, not confirmed inability.",
  },
  "no-evidence": {
    key: "no-evidence",
    label: "No evidence",
    description:
      "Nothing submitted yet. Absence of submitted evidence, not confirmed inability.",
  },
};

export function strengthInfo(key: EvidenceStrengthKey): EvidenceStrengthInfo {
  return STRENGTH_INFO[key];
}

/**
 * Classify overall evidence strength for a skill card.
 * Order matters: absence is reported before any strength band, and an
 * evidence gap is reported even when weak signals exist.
 */
export function classifyEvidenceStrength(input: {
  evidenceCount: number;
  evidenceState?: string;
  gapType?: string;
  maxSourceStrength: number;
}): EvidenceStrengthInfo {
  const count = Number.isFinite(input.evidenceCount) ? input.evidenceCount : 0;
  if (count <= 0 || input.evidenceState === "no_evidence") {
    return STRENGTH_INFO["no-evidence"];
  }
  if (input.gapType === "evidence_gap") {
    return STRENGTH_INFO["evidence-gap"];
  }
  const best = Number.isFinite(input.maxSourceStrength)
    ? input.maxSourceStrength
    : 0;
  if (best >= 0.7) return STRENGTH_INFO["strong"];
  if (best >= 0.5) return STRENGTH_INFO["moderate"];
  return STRENGTH_INFO["weak"];
}

/** Confidence wording mirrors the backend proficiency explainer. */
export function confidenceLabel(confidence: number): "High" | "Moderate" | "Low" {
  if (confidence >= 0.7) return "High";
  if (confidence >= 0.4) return "Moderate";
  return "Low";
}

const DEPTH_NAMES: Record<number, string> = {
  0: "URL only",
  1: "Mention",
  2: "Configuration",
  3: "Implementation",
  4: "Substantial implementation",
};

/** Human-readable EvidenceDepth name; unknown values stay unverified. */
export function depthName(depth: unknown): string {
  return typeof depth === "number" && depth in DEPTH_NAMES
    ? DEPTH_NAMES[depth]
    : "Unverified";
}

const USAGE_STATUS_LABELS: Record<string, string> = {
  mentioned: "mentioned in documentation",
  declared: "declared as a dependency",
  imported: "imports observed",
  used: "API usage observed",
  substantial: "substantial multi-file usage",
};

/** Human-readable usage-status fragment, or "" when unknown. */
export function usageStatusLabel(status: unknown): string {
  return typeof status === "string" && status in USAGE_STATUS_LABELS
    ? USAGE_STATUS_LABELS[status]
    : "";
}

// --- Small runtime guards for the loosely-typed details payload ---

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((v): v is string => typeof v === "string");
}

function asNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function pluralize(count: number, singular: string, plural: string): string {
  return count === 1 ? singular : plural;
}

function repoWord(count: number): string {
  return pluralize(count, "repository", "repositories");
}

function githubBullets(
  skill: string,
  details: Record<string, unknown>,
): string[] {
  const bullets: string[] = [];
  const repos = Array.isArray(details["repositories"])
    ? details["repositories"].filter(isRecord)
    : [];
  const files = asStringArray(details["relevant_files"]);
  const importance = details["file_importance"];
  const usage = usageStatusLabel(details["usage_status"]);

  if (repos.length > 0) {
    const implCount = repos.filter((r) => {
      const depth = r["depth"];
      return typeof depth === "number" && depth >= 3;
    }).length;
    if (implCount > 0) {
      bullets.push(
        `${implCount} ${repoWord(implCount)} ` +
          `${implCount === 1 ? "contains" : "contain"} ${skill} implementation`,
      );
    } else {
      bullets.push(
        `${repos.length} ${repoWord(repos.length)} reference ${skill}`,
      );
    }
  } else {
    const repoCount = asNumber(details["repo_count"]);
    if (repoCount !== null && repoCount > 0) {
      bullets.push(
        `${repoCount} ${repoWord(repoCount)} evidence ${skill}`,
      );
    }
  }

  if (files.length > 0) {
    const shown = Math.min(files.length, 99);
    const kind =
      importance === "high" || importance === "very_high"
        ? "relevant implementation files"
        : "relevant files";
    bullets.push(`${shown} ${kind} detected`);
  }

  if (usage) {
    bullets.push(`Observed usage: ${usage}`);
  }
  return bullets;
}

function performanceBullets(
  skill: string,
  source: EvidenceSource,
  details: Record<string, unknown>,
): string[] {
  const label = source.source_label || source.source_type || "Coding platform";
  const solved =
    asNumber(details["solved"]) ??
    asNumber(details["total_solved"]) ??
    asNumber(details["totalSolved"]);
  if (solved !== null) {
    return [`${solved} ${skill} submissions on ${label}`];
  }
  return [`${label} performance evidence supports ${skill} usage`];
}

function assessmentBullets(source: EvidenceSource): string[] {
  const details = isRecord(source.details) ? source.details : {};
  const score =
    asNumber(details["score"]) ?? asNumber(details["assessment_score"]);
  if (score !== null) {
    const pct = Math.round(score <= 1 ? score * 100 : score);
    return [`INAURA assessment score ${pct}% (validated)`];
  }
  const correct = asNumber(details["correct_count"]);
  const total = asNumber(details["question_count"]);
  if (correct !== null && total !== null && total > 0) {
    return [
      `INAURA assessment ${correct}/${total} correct (validated)`,
    ];
  }
  return [`INAURA assessment completed (validated)`];
}

/**
 * Concise "why" bullets derived strictly from present evidence fields.
 * Returns [] when there is nothing to describe (caller states the absence).
 */
export function buildWhyBullets(
  skill: string,
  sources: EvidenceSource[],
): string[] {
  const bullets: string[] = [];
  for (const source of sources) {
    const details = isRecord(source.details) ? source.details : {};
    const type = (source.source_type || "").toLowerCase();
    if (type === "github") {
      bullets.push(...githubBullets(skill, details));
    } else if (type === "leetcode" || type === "codeforces" || type === "kaggle") {
      bullets.push(...performanceBullets(skill, source, details));
    } else if (type === "assessment") {
      bullets.push(...assessmentBullets(source));
    } else {
      const label = source.source_label || source.source_type || "Evidence";
      bullets.push(`${label} mentions ${skill}`);
    }
    if (bullets.length >= 6) break;
  }
  return bullets.slice(0, 6);
}
