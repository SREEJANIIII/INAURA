import { useState } from "react";
import {
  getCurriculumProposals,
  getProposalReviews,
  createProposalReview,
  type CurriculumProposalRow,
} from "../../services/industry";

const titleCase = (v?: string | null) => v ? v.replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase()) : "Unknown";

// Small additive proposals view for the Industry Intelligence page: real
// P1.2 proposal records with P1.5 review status and reviewer controls.
// Proposed / approved / rejected / deferred are visually distinct; approval
// records a decision only (never implementation), and there is deliberately
// no "Apply Change" button.
type ReviewState = { status: string; reason?: string | null; reviewer?: string | null; created_at?: string };

export default function CurriculumProposals({ role }: { role: string }) {
  const [district, setDistrict] = useState("");
  const [state, setState] = useState("");
  const [rows, setRows] = useState<CurriculumProposalRow[] | null>(null);
  const [reviews, setReviews] = useState<Record<string, ReviewState>>({});
  const [reasonFor, setReasonFor] = useState<string | null>(null);
  const [pendingDecision, setPendingDecision] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [pendingAction, setPendingAction] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refreshReviews = (d: string) =>
    getProposalReviews({ district: d }).then((all) => {
      const latest: Record<string, ReviewState> = {};
      for (const r of all) {
        const prev = latest[r.proposal_id];
        if (!prev || String(r.created_at) >= String(prev.created_at ?? "")) {
          latest[r.proposal_id] = { status: r.to_status, reason: r.reason, reviewer: r.reviewer_id, created_at: r.created_at };
        }
      }
      setReviews(latest);
    });

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const d = district.trim();
    if (!d) return;
    setLoading(true);
    setError(null);
    getCurriculumProposals({ district: d, state: state.trim() || undefined, role })
      .then((r) => { setRows(r.proposals); setLoading(false); return refreshReviews(d); })
      .catch((e) => { setError(e instanceof Error ? e.message : "Proposals unavailable."); setLoading(false); });
  };

  const decide = (proposal: CurriculumProposalRow, decision: string) => {
    if ((decision === "REJECTED" || decision === "DEFERRED") && reasonFor !== proposal.proposal_id) {
      setReasonFor(proposal.proposal_id);
      setPendingDecision(decision);
      return;
    }
    setPendingAction(proposal.proposal_id);
    createProposalReview({
      proposal_id: proposal.proposal_id,
      district: proposal.district,
      role: proposal.role,
      decision,
      reason: reason.trim() || undefined,
    })
      .then(() => refreshReviews(district.trim()).finally(() => {
        setPendingAction(null);
        setReasonFor(null);
        setPendingDecision(null);
        setReason("");
      }))
      .catch((e) => { setError(e instanceof Error ? e.message : "Review failed."); setPendingAction(null); });
  };

  const statusOf = (p: CurriculumProposalRow) => reviews[p.proposal_id]?.status ?? "PENDING_REVIEW";

  return <section aria-label="Curriculum change proposals">
    <div className="an-overview__bar"><span><strong>Curriculum change proposals</strong><span className="an-faint"> · human review required</span></span><form onSubmit={submit} style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}><label className="an-faint" htmlFor="cprop-district">District</label><input id="cprop-district" value={district} onChange={(e) => setDistrict(e.target.value)} placeholder="e.g. Bengaluru Urban" style={{ maxWidth: 220 }} /><label className="an-faint" htmlFor="cprop-state">State</label><input id="cprop-state" value={state} onChange={(e) => setState(e.target.value)} placeholder="optional" style={{ maxWidth: 160 }} /><button type="submit" className="an-link an-link--btn">Evaluate</button></form></div>
    {rows === null && !loading && !error && <p className="an-note">Enter a district to list evidence-backed curriculum proposals for {role}. Proposals never modify curriculum data.</p>}
    {loading && <div className="an-skel an-skel--block" aria-label="Loading proposals" />}
    {error && <p className="an-empty">{error}</p>}
    {rows !== null && !loading && !error && <>
      {rows.length === 0 && <p className="an-note">No actionable proposals — low priority and insufficient evidence stay informational.</p>}
      <ul className="an-skills">{rows.slice(0, 12).map((p) => {
        const st = statusOf(p);
        const terminal = st === "APPROVED" || st === "REJECTED";
        return <li key={p.proposal_id} className="an-skill"><div className="an-skill__row"><span className="an-skill__name">{titleCase(p.priority.level)} · {p.skill.name}</span><span className="an-skill__status">{titleCase(p.action.type)} · {titleCase(st)}</span></div><div className="an-skill__detail" style={{ display: "block" }}><dl className="an-facts">
          <div><dt>Proposal</dt><dd>{p.title}</dd></div>
          <div><dt>Course</dt><dd>{p.course_name || p.course_id}</dd></div>
          <div><dt>Evidence</dt><dd>{p.priority.reasons.join(" · ") || "See evidence packet via API."}</dd></div>
          <div><dt>Review status</dt><dd>{titleCase(st)}{reviews[p.proposal_id]?.reason && <> — {reviews[p.proposal_id]?.reason}</>}{reviews[p.proposal_id]?.reviewer && <span className="an-faint"> · by {String(reviews[p.proposal_id]?.reviewer).slice(0, 8)}</span>}<span className="an-faint"> (approval records a decision only — never implementation)</span></dd></div>
          {!terminal && <div><dt>Review</dt><dd>
            <span style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <button type="button" className="an-link an-link--btn" disabled={pendingAction === p.proposal_id} onClick={() => decide(p, "APPROVED")}>Approve</button>
              <button type="button" className="an-link an-link--btn" disabled={pendingAction === p.proposal_id} onClick={() => decide(p, "REJECTED")}>Reject</button>
              <button type="button" className="an-link an-link--btn" disabled={pendingAction === p.proposal_id} onClick={() => decide(p, "DEFERRED")}>Defer</button>
            </span>
            {reasonFor === p.proposal_id && <span style={{ display: "flex", gap: 8, marginTop: 8 }}><input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason required for reject / defer" style={{ maxWidth: 320 }} /><button type="button" className="an-link an-link--btn" disabled={pendingAction === p.proposal_id} onClick={() => decide(p, pendingDecision ?? "REJECTED")}>Confirm</button></span>}
          </dd></div>}
        </dl></div></li>;
      })}</ul>
      {rows.length > 12 && <p className="an-note">Showing 12 of {rows.length} proposals — full detail is available from the API.</p>}
    </>}
  </section>;
}
