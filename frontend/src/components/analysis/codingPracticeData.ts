/* eslint-disable @typescript-eslint/no-explicit-any */
// Reads LeetCode and Codeforces details from verified evidence metadata
import type { Evidence } from "../../services/evidence";

export function codingPracticeData(evidence: Evidence[]) {
  const leetcodeEv = evidence.find(
    (e) =>
      e.evidence_type === "leetcode" &&
      (e.verification_status === "verified" ||
        (e.metadata as Record<string, unknown> | null)?.verification_status === "verified")
  );

  const lcMeta = leetcodeEv?.metadata as Record<string, any> | null;
  const lcInspection = lcMeta?.inspection;
  const lcTopicMeta =
    lcInspection?.topic_coverage ||
    (lcMeta?.verified_signals as any[])?.find((s: any) => s.skill?.includes("Data Structures"))?.metadata ||
    lcMeta?.topic_coverage;

  const lcUsername = lcInspection?.username || "LeetCode Candidate";
  const lcTotal = lcInspection?.total_solved ?? (lcTopicMeta?.total_solved ?? 0);
  const lcEasy = lcInspection?.easy_solved ?? (lcTopicMeta?.easy ?? 0);
  const lcMed = lcInspection?.medium_solved ?? (lcTopicMeta?.medium ?? 0);
  const lcHard = lcInspection?.hard_solved ?? (lcTopicMeta?.hard ?? 0);

  const codeforcesEv = evidence.find(
    (e) =>
      e.evidence_type === "codeforces" &&
      (e.verification_status === "verified" ||
        (e.metadata as Record<string, unknown> | null)?.verification_status === "verified")
  );
  const cfMeta = codeforcesEv?.metadata as Record<string, any> | null;
  const cfInspection = cfMeta?.inspection as Record<string, any> | null;
  const cfProfile = cfMeta?.profile as Record<string, any> | null;
  const cfFacts = (cfMeta?.facts as string[] | undefined) || [];
  const cfWarnings = (cfMeta?.warnings as string[] | undefined) || [];
  const cfVerifiedSignals = (cfMeta?.verified_signals as any[] | undefined) || [];

  const hasDsa = !!(lcTopicMeta && lcTopicMeta.status === "available" && lcTopicMeta.pillar_breakdown);
  return { lcTopicMeta, lcUsername, lcTotal, lcEasy, lcMed, lcHard, hasDsa, cfInspection, cfProfile, cfFacts, cfWarnings, cfVerifiedSignals };
}
