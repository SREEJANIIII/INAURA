/**
 * Whether the analysis you're looking at still describes you.
 *
 * Everything downstream — your readiness, your gaps, your roadmap, your revision deck — is
 * computed from one analysis run. Change the evidence underneath it, or change the role
 * you're aiming for, and all of it quietly stops being true. Nothing about the numbers on
 * screen says so, which is the dangerous part: they look exactly as authoritative as before.
 *
 * So one rule lives here, and every page that shows analysis output asks it the same
 * question. Pure, so it can be tested without a backend.
 */

export type StaleReason = "role" | "evidence" | "scoring";

export type Freshness = {
  /** True when the analysis exists but no longer matches your evidence or your role */
  stale: boolean;
  reason: StaleReason | null;
  /** One sentence, in the interface's voice, saying what changed */
  message: string | null;
  /** What to do about it, as a button would say it */
  action: string | null;
};

const FRESH: Freshness = { stale: false, reason: null, message: null, action: null };

export type FreshnessInput = {
  analysis: {
    target_role?: string | null;
    evidence_changed?: boolean | null;
    scoring_outdated?: boolean;
  } | null | undefined;
  /** The role you're aiming for now, which may not be the one the analysis ran against */
  targetRole?: string | null;
};

const same = (a: string | null | undefined, b: string | null | undefined) =>
  (a || "").trim().toLowerCase() === (b || "").trim().toLowerCase();

/**
 * Read against the analysis you have. An account with no analysis yet isn't stale — there's
 * nothing to be out of date — and the pages handle that emptiness on their own.
 */
export function freshness({ analysis, targetRole }: FreshnessInput): Freshness {
  if (!analysis) return FRESH;

  // Aiming somewhere else entirely matters more than anything the old run says
  if (targetRole && analysis.target_role && !same(targetRole, analysis.target_role)) {
    return {
      stale: true,
      reason: "role",
      message: `This was run against ${analysis.target_role}, and you're aiming for ${targetRole} now.`,
      action: "Run it for your new role",
    };
  }

  if (analysis.evidence_changed) {
    return {
      stale: true,
      reason: "evidence",
      message: "Your evidence has changed since this was run, so these results don't include it yet.",
      action: "Run the analysis again",
    };
  }

  if (analysis.scoring_outdated) {
    return {
      stale: true,
      reason: "scoring",
      message: "INAURA's scoring has improved since this was run.",
      action: "Run the analysis again",
    };
  }

  return FRESH;
}

/** The short form, for a tooltip or a dot's label */
export const staleLabel = (reason: StaleReason | null): string =>
  reason === "role"
    ? "Your target role changed"
    : reason === "evidence"
      ? "Your evidence changed"
      : reason === "scoring"
        ? "Scoring improved"
        : "";
