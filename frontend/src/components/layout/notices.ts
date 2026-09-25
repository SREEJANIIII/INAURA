/**
 * What the bell in the top bar has to say: only things that are true right now and that you
 * can do something about, each with the page that fixes it. Pure, so it can be tested.
 */
import { freshness } from "../../lib/analysisFreshness.ts";

export type NoticeTone = "attention" | "progress" | "info";
export type Notice = { id: string; tone: NoticeTone; title: string; detail?: string; to: string };

export type NoticeInput = {
  analysis?: { target_role?: string | null; evidence_changed?: boolean | null; scoring_outdated?: boolean } | null;
  /** The role you're aiming for now */
  targetRole?: string | null;
  /** Whether an analysis has ever finished for this account */
  analysedBefore?: boolean;
  evidence?: { id: string; evidence_type: string; verification_status?: string; is_excluded?: boolean }[];
  projectCount?: number;
  certCount?: number;
  /** A background re-run started from Career Track or Analysis */
  sync?: { stage: string; role: string | null; message: string | null };
  revisionDue?: number;
};

const SOURCE_NAME: Record<string, string> = {
  github: "GitHub profile",
  leetcode: "LeetCode profile",
  codeforces: "Codeforces profile",
  kaggle: "Kaggle profile",
  linkedin: "LinkedIn profile",
};

export function buildNotices(input: NoticeInput): Notice[] {
  const notices: Notice[] = [];
  const { sync } = input;
  const running = sync && (sync.stage === "analysing" || sync.stage === "building");

  if (running && sync?.role) {
    notices.push({
      id: "sync",
      tone: "progress",
      title: sync.stage === "building" ? `Building your roadmap for ${sync.role}` : `Re-running your analysis for ${sync.role}`,
      detail: "Usually under a minute. You can keep using INAURA.",
      to: "/career-track",
    });
  } else if (sync?.stage === "failed" && sync.message) {
    notices.push({ id: "sync-failed", tone: "attention", title: "Your analysis couldn’t be updated", detail: sync.message, to: "/analysis" });
  }

  const stale = freshness({ analysis: input.analysis, targetRole: input.targetRole });
  if (stale.stale && !running) {
    notices.push({ id: "stale", tone: "attention", title: "Your analysis is out of date", detail: stale.message ?? undefined, to: "/analysis/results" });
  }

  const active = (input.evidence ?? []).filter((e) => !e.is_excluded);
  const hasEvidence = active.length > 0 || (input.projectCount ?? 0) > 0 || (input.certCount ?? 0) > 0;
  if (!input.analysedBefore && !input.analysis && hasEvidence && !running) {
    notices.push({
      id: "first-run",
      tone: "info",
      title: "Your evidence is ready to analyse",
      detail: "Run your analysis to see your readiness and your biggest gaps.",
      to: "/analysis",
    });
  }

  for (const e of active) {
    if (e.verification_status === "failed" && SOURCE_NAME[e.evidence_type]) {
      notices.push({
        id: `verify-${e.id}`,
        tone: "attention",
        title: `Your ${SOURCE_NAME[e.evidence_type]} couldn’t be verified`,
        detail: "Check the link or username, then verify it again.",
        to: "/analysis#profile-urls",
      });
    }
  }

  const due = input.revisionDue ?? 0;
  if (due > 0) {
    notices.push({
      id: "revision",
      tone: "info",
      title: `${due} revision card${due === 1 ? " is" : "s are"} due`,
      detail: "A few minutes keeps what you’ve learned from slipping.",
      to: "/revision",
    });
  }

  return notices;
}
