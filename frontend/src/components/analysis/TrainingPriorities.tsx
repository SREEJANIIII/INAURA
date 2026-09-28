import { useState } from "react";
import { getTrainingPriorities, type TrainingPrioritiesResponse } from "../../services/industry";

const titleCase = (v?: string | null) => v ? v.replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase()) : "Unknown";
const share = (v?: number | null) => v === null || v === undefined ? "—" : `${Math.round(v * 100)}%`;

// Small additive priorities view for the Industry Intelligence page: HIGH /
// MEDIUM / LOW / INSUFFICIENT_EVIDENCE rows with evidence and reasons.
// Statuses (aligned/actionable_gap/insufficient_evidence) stay distinct from
// urgency; the market match type is always shown.
export default function TrainingPriorities({ role }: { role: string }) {
  const [district, setDistrict] = useState("");
  const [state, setState] = useState("");
  const [applied, setApplied] = useState<{ district: string; state?: string } | null>(null);
  const [data, setData] = useState<TrainingPrioritiesResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const d = district.trim();
    if (!d) return;
    const next = { district: d, state: state.trim() || undefined };
    setApplied(next);
    setLoading(true);
    setError(null);
    getTrainingPriorities({ ...next, role })
      .then((r) => { setData(r); setLoading(false); })
      .catch((e) => { setError(e instanceof Error ? e.message : "Training priorities unavailable."); setLoading(false); });
  };

  return <section aria-label="Training priorities">
    <div className="an-overview__bar"><span><strong>Training priorities</strong><span className="an-faint"> · evidence-based planning signals, not policy decisions</span></span><form onSubmit={submit} style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}><label className="an-faint" htmlFor="prio-district">District</label><input id="prio-district" value={district} onChange={(e) => setDistrict(e.target.value)} placeholder="e.g. Bengaluru Urban" style={{ maxWidth: 220 }} /><label className="an-faint" htmlFor="prio-state">State</label><input id="prio-state" value={state} onChange={(e) => setState(e.target.value)} placeholder="optional" style={{ maxWidth: 160 }} /><button type="submit" className="an-link an-link--btn">Evaluate</button></form></div>
    {!applied && <p className="an-note">Enter a district to prioritize its training gaps for {role}.</p>}
    {loading && <div className="an-skel an-skel--block" aria-label="Loading training priorities" />}
    {error && <p className="an-empty">{error}</p>}
    {!loading && !error && data && <>
      {data.district_status === "unknown" && <p className="an-note"><strong>District unknown.</strong> No institutions recorded — nothing fabricated.</p>}
      <p className="an-note"><strong>{data.district}</strong><span className="an-faint"> · high: {data.summary?.HIGH ?? 0} · medium: {data.summary?.MEDIUM ?? 0} · low: {data.summary?.LOW ?? 0} · insufficient evidence: {data.summary?.INSUFFICIENT_EVIDENCE ?? 0} · demand source: {titleCase(data.market_context?.match_type)}{data.market_context?.match_type === "fallback_global" ? " (global fallback)" : ""}</span></p>
      {data.priorities.length === 0 && <p className="an-note">No priorities — {data.note || "insufficient evidence."}</p>}
      <ul className="an-skills">{data.priorities.slice(0, 12).map((p) => <li key={p.skill} className="an-skill"><div className="an-skill__row"><span className="an-skill__name">{p.display_name || p.skill}</span><span className="an-skill__status">{titleCase(p.priority)}</span></div><div className="an-skill__detail" style={{ display: "block" }}><dl className="an-facts">
        <div><dt>Status</dt><dd>{titleCase(p.status)}</dd></div>
        <div><dt>Demand</dt><dd>{p.evidence.market.trend ? <>{titleCase(p.evidence.market.trend)} <span className="an-faint">(share {share(p.evidence.market.skill_share)})</span></> : "No market evidence"}</dd></div>
        <div><dt>Verified supply</dt><dd>{share(p.evidence.learner_supply.verified_coverage)} <span className="an-faint">({p.evidence.learner_supply.verified_learner_count} of {p.evidence.learner_supply.learner_count})</span></dd></div>
        {p.reasons.length > 0 && <div><dt>Reasons</dt><dd>{p.reasons.join(" · ")}</dd></div>}
      </dl></div></li>)}</ul>
      <p className="an-note">{data.capacity_note}</p>
    </>}
  </section>;
}
