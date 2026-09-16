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

const STATUS_TO_DEPTH: Record<string, number> = {
  mentioned: 1,
  declared: 2,
  imported: 3,
  used: 3,
  substantial: 4,
};

function statusDepth(status: unknown): number | null {
  if (typeof status !== "string") return null;
  const d = STATUS_TO_DEPTH[status.toLowerCase()];
  return typeof d === "number" ? d : null;
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
  const rawUsage = details["usage_status"];
  const usage = usageStatusLabel(rawUsage);
  const evidenceDepth = asNumber(details["evidence_depth"]);
  const evidenceCount = asNumber(details["evidence_count"]);
  const repoCount = asNumber(details["repo_count"]);

  // Source-level depth is the single coherent provenance contract.
  // Repository-level differences are shown in the detailed card, not flattened here.
  const sourceDepth = evidenceDepth;

  // Repository count bullet: distinguish overall vs accepted evidence count
  if (repos.length > 0) {
    // Prefer accepted evidence count (winning bucket) for implementation claims
    const acceptedCount = evidenceCount !== null ? evidenceCount : repos.length;
    const implDepth = sourceDepth !== null ? sourceDepth >= 3 : false;
    if (implDepth && acceptedCount > 0) {
      // Only claim implementation when source depth supports it
      bullets.push(
        `${acceptedCount} ${repoWord(acceptedCount)} ` +
          `${acceptedCount === 1 ? "contains" : "contain"} ${skill} implementation`,
      );
    } else {
      const total = repoCount !== null ? repoCount : repos.length;
      bullets.push(
        `${total} ${repoWord(total)} reference ${skill}`,
      );
      if (sourceDepth !== null && sourceDepth >= 3 && acceptedCount > 0) {
        // Fallback: if repos show impl but source depth is impl, still mention
        // (defensive – backend now guarantees coherence)
      }
    }
  } else {
    if (repoCount !== null && repoCount > 0) {
      bullets.push(
        `${repoCount} ${repoWord(repoCount)} evidence ${skill}`,
      );
    }
  }

  // Relevant files: only claim "implementation files" when source depth
  // and importance together support it; otherwise generic "relevant files".
  if (files.length > 0) {
    const shown = Math.min(files.length, 99);
    const isImplDepth = sourceDepth !== null ? sourceDepth >= 3 : false;
    const kind =
      isImplDepth && (importance === "high" || importance === "very_high")
        ? "relevant implementation files"
        : "relevant files";
    // Coherence guard: never claim substantial multi-file impl alongside Mention
    if (sourceDepth !== null && sourceDepth <= 1 && kind.includes("implementation")) {
      bullets.push(`${shown} relevant files detected`);
    } else {
      bullets.push(`${shown} ${kind} detected`);
    }
  }

  // Observed usage: only display when it is supported by final accepted depth.
  // Never show "substantial multi-file usage" alongside Mention evidence.
  if (usage) {
    const sDepth = statusDepth(rawUsage);
    const depthOk =
      sourceDepth === null || sDepth === null ? true : sDepth <= sourceDepth;
    if (depthOk) {
      bullets.push(`Observed usage: ${usage}`);
    } else {
      // Downgraded or censored to avoid contradiction – show capped label or omit
      // For depth 1, show only mentioned; for depth 2, declared, etc.
      // Here we simply omit the contradictory stronger claim.
    }
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
  // Layer-aware label (additive): knowledge/practical/interview stay
  // distinguishable; sources without a layer marker keep the legacy wording.
  const layer = typeof details["assessment_layer"] === "string" ? details["assessment_layer"] : "";
  const kind =
    layer === "practical"
      ? "practical assessment"
      : layer === "interview"
        ? "skill interview"
        : layer === "knowledge"
          ? "knowledge assessment"
          : "assessment";
  const score =
    asNumber(details["score"]) ?? asNumber(details["assessment_score"]);
  if (score !== null) {
    const pct = Math.round(score <= 1 ? score * 100 : score);
    return [`INAURA ${kind} score ${pct}% (validated)`];
  }
  const correct = asNumber(details["correct_count"]);
  const total = asNumber(details["question_count"]);
  if (correct !== null && total !== null && total > 0) {
    return [
      `INAURA ${kind} ${correct}/${total} correct (validated)`,
    ];
  }
  return [`INAURA ${kind} completed (validated)`];
}

/* =====================================================================
 * User-facing GitHub evidence presentation helpers (presentation layer only).
 *
 * These translate existing backend provenance into student-friendly
 * language WITHOUT changing the evidence model, scoring, or meaning.
 * Every helper derives strictly from backend fields (depth, usage_status,
 * fork, files). Nothing is invented; unknown values degrade to neutral
 * wording. Backend fields themselves are never renamed here.
 * ===================================================================== */

export type EvidenceCategory = "strong" | "supporting" | "limited" | "unknown";

/**
 * Group a repository by its OWN accepted depth (never the source aggregate).
 * - depth 4/3 -> strong (found used in implementation)
 * - depth 2   -> supporting (configured/referenced)
 * - depth 1/0 -> limited (mentions/metadata)
 */
export function getEvidenceCategory(depth: unknown): EvidenceCategory {
  if (typeof depth !== "number" || !Number.isFinite(depth)) return "unknown";
  if (depth >= 3) return "strong";
  if (depth === 2) return "supporting";
  if (depth <= 1) return "limited";
  return "unknown";
}

export function getEvidenceCategoryLabel(category: EvidenceCategory): string {
  switch (category) {
    case "strong":
      return "Strong evidence";
    case "supporting":
      return "Supporting evidence";
    case "limited":
      return "Limited evidence";
    default:
      return "Evidence";
  }
}

/** Short repo display name: "owner/Repo" -> "Repo". Falls back safely. */
export function shortRepoName(fullName: unknown, fallback = "Repository"): string {
  if (typeof fullName !== "string" || !fullName.trim()) return fallback;
  const trimmed = fullName.trim();
  const parts = trimmed.split("/");
  const last = parts[parts.length - 1]?.trim();
  return last || trimmed;
}

/**
 * User-friendly evidence headline derived from the repo's own depth.
 * Never claims implementation when depth is only config/mention.
 */
export function getEvidenceLabel(depth: unknown): string {
  const category = getEvidenceCategory(depth);
  switch (category) {
    case "strong":
      return "Used in your implementation";
    case "supporting":
      return "Configured in project";
    case "limited":
      return "Mentioned in project";
    default:
      return "Found in project";
  }
}

/**
 * User-friendly usage line. `usage` should already be coerced so it never
 * outranks depth (see coerce helpers in the card component).
 */
export function getUsageDescription(
  usageStatus: unknown,
  depth: unknown,
  fileCount: number,
): string {
  const raw = typeof usageStatus === "string" ? usageStatus.toLowerCase() : "";
  const category: EvidenceCategory = getEvidenceCategory(depth);
  if (category === "strong") {
    if (raw === "substantial") return "Used across multiple files";
    if (raw === "used" || raw === "imported") return "Used in implementation";
    if (raw === "declared") return "Added as a project dependency";
    if (raw === "mentioned") return "Referenced in project files";
    return fileCount > 1 ? "Used across multiple files" : "Used in implementation";
  }
  if (category === "supporting") {
    return "Added as a project dependency";
  }
  if (category === "limited") {
    return "Referenced in project files";
  }
  if (raw === "substantial") return "Used across multiple files";
  if (raw === "used" || raw === "imported") return "Used in implementation";
  if (raw === "declared") return "Added as a project dependency";
  if (raw === "mentioned") return "Referenced in project files";
  return "Found in project";
}

/** "INAURA found this skill across N source files." — count-driven only. */
export function getFilesSummaryLine(fileCount: number): string | null {
  if (!Number.isFinite(fileCount) || fileCount <= 0) return null;
  return fileCount === 1
    ? "INAURA found this skill in 1 source file."
    : `INAURA found this skill across ${fileCount} source files.`;
}

export function getOwnershipLabel(fork: unknown): string | null {
  if (fork === true) return "Forked repository";
  if (fork === false) return "Your repository";
  return null;
}

/** Concise filename: "frontend/src/services/api.ts" -> "api.ts". */
export function formatFileName(path: unknown): string {
  if (typeof path !== "string" || !path) return "file";
  const cleaned = path.replace(/\\/g, "/");
  const parts = cleaned.split("/").filter(Boolean);
  return parts.length > 0 ? (parts[parts.length - 1] as string) : path;
}

/**
 * "Why this counts" — strictly gated on the repo's own depth so a Mention
 * can never render as active implementation.
 */
export function getWhyCountsText(
  depth: unknown,
  isFork: boolean,
  fileCount: number,
): string {
  const category = getEvidenceCategory(depth);
  if (category === "strong") {
    const multi =
      fileCount > 1
        ? " It was found across multiple implementation files."
        : " It was found in your source code.";
    return `This skill was found being used in your actual source code.${isFork ? "" : multi}` +
      (isFork
        ? " This is a forked repository, so INAURA treats its evidence more cautiously."
        : "");
  }
  if (category === "supporting") {
    return (
      "This skill was found configured in the project, but configuration " +
      "alone is not treated as proof of active implementation." +
      (isFork
        ? " This is a forked repository, so INAURA treats its evidence more cautiously."
        : "")
    );
  }
  if (category === "limited") {
    return (
      "This skill was mentioned in the project, but INAURA found limited implementation evidence." +
      (isFork
        ? " This is a forked repository, so INAURA treats its evidence more cautiously."
        : "")
    );
  }
  return (
    "INAURA found a reference to this skill in this project." +
    (isFork
      ? " This is a forked repository, so INAURA treats its evidence more cautiously."
      : "")
  );
}

/**
 * "What INAURA observed" checklist — only claims supported by the repo's
 * own coerced usage_status. Never invents Imported/Used signals.
 */
export function getObservedChecks(
  usageStatus: unknown,
  depth: unknown,
  fileCount: number,
): string[] {
  const raw = typeof usageStatus === "string" ? usageStatus.toLowerCase() : "";
  const category = getEvidenceCategory(depth);
  if (category === "strong" && (raw === "substantial" || raw === "used" || raw === "imported")) {
    const checks = ["Imported in source code", "Used in source code"];
    if (raw === "substantial" || fileCount > 1) checks.push("Found across multiple files");
    return checks;
  }
  if (category === "strong") return ["Used in source code"];
  if (category === "supporting") return ["Declared as a dependency", "Found in project configuration"];
  if (category === "limited") return ["Mentioned in project"];
  return ["Referenced in project"];
}

export interface RepoEvidenceSummary {
  total: number;
  strong: number;
  supporting: number;
  limited: number;
}

/** Count repos by their OWN depth for the "found in N repositories" summary. */
export function summarizeRepoEvidence(depths: unknown[]): RepoEvidenceSummary {
  let strong = 0;
  let supporting = 0;
  let limited = 0;
  for (const d of depths) {
    const c = getEvidenceCategory(d);
    if (c === "strong") strong += 1;
    else if (c === "supporting") supporting += 1;
    else if (c === "limited") limited += 1;
  }
  return { total: depths.length, strong, supporting, limited };
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
