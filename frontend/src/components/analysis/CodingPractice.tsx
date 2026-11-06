/* eslint-disable @typescript-eslint/no-explicit-any */
// LeetCode DSA coverage and Codeforces panels, moved unchanged from the previous results page.
import { useState } from "react";
import type { codingPracticeData } from "./codingPracticeData";
import { verifyEvidence } from "../../services/evidence";
import { evidencePageData, refreshPageData } from "../../lib/pageData";

type Data = ReturnType<typeof codingPracticeData>;

export function DsaCoverage({
  data,
  onSync,
}: {
  data: Data;
  onSync?: () => Promise<void> | void;
}) {
  const { lcEvidenceId, lcTopicMeta, lcUsername, lcTotal, lcEasy, lcMed, lcHard } = data;
  const [syncing, setSyncing] = useState(false);
  const [syncStatus, setSyncStatus] = useState<{ type: "ok" | "err"; msg: string } | null>(null);

  if (!data.hasDsa) return null;

  const handleSync = async () => {
    if (!lcEvidenceId || syncing) return;
    setSyncing(true);
    setSyncStatus(null);
    try {
      await verifyEvidence(lcEvidenceId, true);
      if (onSync) {
        await onSync();
      } else {
        refreshPageData();
        await evidencePageData.fetch(true);
      }
      setSyncStatus({ type: "ok", msg: "✓ Profile refreshed with latest LeetCode questions!" });
      setTimeout(() => setSyncStatus(null), 4000);
    } catch {
      setSyncStatus({ type: "err", msg: "⚠ Could not reach LeetCode right now. Please try again shortly." });
      setTimeout(() => setSyncStatus(null), 5000);
    } finally {
      setSyncing(false);
    }
  };

  return (
    <div className="results__leetcode-card">
      <div className="results__leetcode-header">
        <div>
          <h3 style={{ margin: 0, fontSize: "1.05rem" }}>LeetCode DSA Topic Coverage · {lcUsername}</h3>
          <div style={{ fontSize: "0.82rem", color: "var(--muted)", marginTop: 2 }}>
            Topic breadth & depth across 9 canonical DSA pillars
          </div>
        </div>
        <div className="results__leetcode-diffs">
          <span className="results__badge-diff results__badge-diff--easy">Easy: {lcEasy}</span>
          <span className="results__badge-diff results__badge-diff--medium">Medium: {lcMed}</span>
          <span className="results__badge-diff results__badge-diff--hard">Hard: {lcHard}</span>
          <span style={{ fontWeight: 700, fontSize: "0.82rem", marginLeft: 4 }}>Total: {lcTotal}</span>
          {lcEvidenceId && (
            <button
              type="button"
              className="results__leetcode-sync-btn"
              onClick={handleSync}
              disabled={syncing}
              title="Sync latest questions from LeetCode"
            >
              {syncing ? "Syncing…" : "↻ Sync questions"}
            </button>
          )}
        </div>
      </div>

      {syncStatus && (
        <div
          style={{
            marginTop: 8,
            fontSize: "0.82rem",
            color: syncStatus.type === "ok" ? "var(--ok-ink, #047857)" : "var(--warn-ink, #b91c1c)",
            fontWeight: 500,
          }}
        >
          {syncStatus.msg}
        </div>
      )}

      <div className="results__leetcode-meta-row">
        <span>
          Topic Breadth: <strong>{Math.round((lcTopicMeta.breadth_score ?? lcTopicMeta.topic_breadth_score ?? 0) * 100)}%</strong> ({lcTopicMeta.covered_pillars?.length || lcTopicMeta.covered_topics?.length || 0} covered, {lcTopicMeta.moderate_pillars?.length || lcTopicMeta.moderate_topics?.length || 0} moderate, {lcTopicMeta.missing_pillars?.length || lcTopicMeta.missing_topics?.length || 0} unpracticed)
        </span>
        <span>·</span>
        <span>
          Topic Depth: <strong>{Math.round((lcTopicMeta.depth_score ?? lcTopicMeta.topic_depth_score ?? 0) * 100)}%</strong>
        </span>
      </div>

      <div className="results__leetcode-pillars-grid">
        {Object.entries(lcTopicMeta.pillar_breakdown).map(([pillar, data]: [string, any]) => {
          const badgeClass =
            data.status === "covered"
              ? "results__pillar-badge--covered"
              : data.status === "moderate"
              ? "results__pillar-badge--moderate"
              : data.status === "weak"
              ? "results__pillar-badge--weak"
              : "results__pillar-badge--missing";
          const pctBar = Math.min(100, Math.round((data.solved / 15) * 100));
          return (
            <div key={pillar} className="results__pillar-box">
              <div className="results__pillar-top">
                <strong>{pillar}</strong>
                <span className={`results__pillar-badge ${badgeClass}`}>{data.status}</span>
              </div>
              <div className="results__pillar-count">
                {data.solved} problems solved {lcTotal > 0 ? `(${data.percentage}%)` : ""}
              </div>
              <div className="results__pillar-bar-wrap">
                <div className="results__pillar-bar" style={{ width: `${pctBar}%` }} />
              </div>
            </div>
          );
        })}
      </div>

      <div style={{ marginTop: 12, fontSize: "0.78rem", color: "var(--muted-2)", fontStyle: "italic" }}>
        * INAURA assesses algorithmic competency based on balanced pillar breadth and depth. High problem volume concentrated in single topics does not substitute for practice across Trees, Graphs, Dynamic Programming, and Backtracking.
      </div>
    </div>
  );
}

export function CodeforcesPanel({
  data,
  onSync,
}: {
  data: Data;
  onSync?: () => Promise<void> | void;
}) {
  const { cfEvidenceId, cfInspection, cfProfile, cfFacts, cfWarnings, cfVerifiedSignals } = data;
  const [syncing, setSyncing] = useState(false);
  const [syncStatus, setSyncStatus] = useState<{ type: "ok" | "err"; msg: string } | null>(null);

  if (!cfInspection) return null;

  const handleSync = async () => {
    if (!cfEvidenceId || syncing) return;
    setSyncing(true);
    setSyncStatus(null);
    try {
      await verifyEvidence(cfEvidenceId, true);
      if (onSync) {
        await onSync();
      } else {
        refreshPageData();
        await evidencePageData.fetch(true);
      }
      setSyncStatus({ type: "ok", msg: "✓ Profile refreshed with latest Codeforces stats!" });
      setTimeout(() => setSyncStatus(null), 4000);
    } catch {
      setSyncStatus({ type: "err", msg: "⚠ Could not reach Codeforces right now. Please try again shortly." });
      setTimeout(() => setSyncStatus(null), 5000);
    } finally {
      setSyncing(false);
    }
  };

  return (
    <div className="results__leetcode-card" style={{ borderLeft: "4px solid #1f8acb" }}>
      <div className="results__leetcode-header">
        <div>
          <h3 style={{ margin: 0, fontSize: "1.05rem" }}>Codeforces · {cfInspection?.handle || cfProfile?.handle || "Candidate"}</h3>
          <div style={{ fontSize: "0.82rem", color: "var(--muted)", marginTop: 2 }}>
            Verified competitive programming rating, contest participation and solved problem tags
          </div>
        </div>
        <div className="results__leetcode-diffs" style={{ alignItems: "center" }}>
          <span style={{ fontWeight: 700, fontSize: "0.9rem", background: cfInspection?.rating ? "#e0f2fe" : "#f1f5f9", border: "1px solid #bae6fd", padding: "4px 8px", borderRadius: 6 }}>
            Rating: {cfInspection?.rating ?? 0} {cfInspection?.rank ? `· ${cfInspection.rank}` : ""}
          </span>
          <span style={{ fontWeight: 600, fontSize: "0.82rem" }}>Max: {cfInspection?.max_rating ?? 0}</span>
          {cfEvidenceId && (
            <button
              type="button"
              className="results__leetcode-sync-btn"
              onClick={handleSync}
              disabled={syncing}
              title="Sync latest stats from Codeforces"
            >
              {syncing ? "Syncing…" : "↻ Sync profile"}
            </button>
          )}
        </div>
      </div>

      {syncStatus && (
        <div
          style={{
            marginTop: 8,
            fontSize: "0.82rem",
            color: syncStatus.type === "ok" ? "var(--ok-ink, #047857)" : "var(--warn-ink, #b91c1c)",
            fontWeight: 500,
          }}
        >
          {syncStatus.msg}
        </div>
      )}

      <div className="results__leetcode-meta-row">
        <span>Contests: <strong>{cfInspection?.contest_count ?? 0}</strong> rated</span>
        <span>·</span>
        <span>Solved: <strong>{cfInspection?.solved_count ?? 0}</strong> verified problems</span>
        {cfVerifiedSignals.length > 0 && (
          <>
            <span>·</span>
            <span>Signals: <strong>{cfVerifiedSignals.length}</strong> ({cfVerifiedSignals.map((s: any) => s.skill).join(", ")})</span>
          </>
        )}
      </div>

      {cfInspection?.problem_tags && Object.keys(cfInspection.problem_tags).length > 0 && (
        <div style={{ marginTop: 10 }}>
          <div style={{ fontSize: "0.82rem", fontWeight: 600, color: "var(--muted)", marginBottom: 6 }}>Verified problem tags (top):</div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {Object.entries(cfInspection.problem_tags)
              .sort((a: any, b: any) => (b[1] as number) - (a[1] as number))
              .slice(0, 8)
              .map(([tag, cnt]: any) => (
                <span key={tag} style={{ background: "var(--paper-2)", border: "1px solid var(--line-strong)", padding: "3px 8px", borderRadius: 12, fontSize: "0.78rem" }}>
                  {tag} · {cnt as number}
                </span>
              ))}
          </div>
        </div>
      )}

      <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 4 }}>
        {cfFacts.map((fact: string, idx: number) => (
          <div key={idx} style={{ fontSize: "0.82rem", color: "var(--muted)" }}>• {fact}</div>
        ))}
        {cfWarnings.map((w: string, idx: number) => (
          <div key={`w-${idx}`} style={{ fontSize: "0.78rem", color: "var(--warn-ink)", background: "var(--warn-bg)", border: "1px solid var(--warn-line)", padding: "4px 8px", borderRadius: 6 }}>⚠ {w}</div>
        ))}
        {cfVerifiedSignals.length === 0 && (
          <div style={{ fontSize: "0.78rem", color: "var(--muted-2)", fontStyle: "italic", marginTop: 4 }}>
            No rated contests or verified solves yet — profile exists but does not yet demonstrate competitive programming proficiency. Solve problems and enter rated contests to generate skill signals.
          </div>
        )}
      </div>

      <div style={{ marginTop: 12, fontSize: "0.78rem", color: "var(--muted-2)", fontStyle: "italic" }}>
        * Codeforces rating is a rigorous peer-ranked signal. Even unrated profiles are verified; proficiency is only credited when contests and solves are present.
      </div>
    </div>
  );
}
