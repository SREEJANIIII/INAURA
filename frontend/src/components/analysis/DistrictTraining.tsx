import { useState } from "react";
import { getDistrictTraining, type DistrictTrainingResponse } from "../../services/industry";

const titleCase = (v?: string | null) => v ? v.replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase()) : "Unknown";
const share = (v?: number | null) => v === null || v === undefined ? "—" : `${Math.round(v * 100)}%`;

// Small additive district view for the Industry Intelligence page: district
// aggregates (institutions/courses/learners, market context) plus a compact
// per-skill table. Uncertainty is shown, never hidden; no seat numbers exist.
export default function DistrictTraining({ role }: { role: string }) {
  const [district, setDistrict] = useState("");
  const [state, setState] = useState("");
  const [applied, setApplied] = useState<{ district: string; state?: string } | null>(null);
  const [data, setData] = useState<DistrictTrainingResponse | null>(null);
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
    getDistrictTraining({ ...next, role })
      .then((r) => { setData(r); setLoading(false); })
      .catch((e) => { setError(e instanceof Error ? e.message : "District intelligence unavailable."); setLoading(false); });
  };

  return <section aria-label="District training intelligence">
    <div className="an-overview__bar"><span><strong>District training intelligence</strong><span className="an-faint"> · evidence-backed planning inputs</span></span><form onSubmit={submit} style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}><label className="an-faint" htmlFor="dist-name">District</label><input id="dist-name" value={district} onChange={(e) => setDistrict(e.target.value)} placeholder="e.g. Bengaluru Urban" style={{ maxWidth: 220 }} /><label className="an-faint" htmlFor="dist-state">State</label><input id="dist-state" value={state} onChange={(e) => setState(e.target.value)} placeholder="optional" style={{ maxWidth: 160 }} /><button type="submit" className="an-link an-link--btn">Evaluate</button></form></div>
    {!applied && <p className="an-note">Enter a district to aggregate its institutions, courses, learners, and market context for {role}.</p>}
    {loading && <div className="an-skel an-skel--block" aria-label="Loading district intelligence" />}
    {error && <p className="an-empty">{error}</p>}
    {!loading && !error && data && <>
      {data.district_status === "unknown" && <p className="an-note"><strong>District unknown.</strong> No institutions recorded for this district — nothing fabricated.</p>}
      <p className="an-note"><strong>{data.district}</strong><span className="an-faint"> · institutions: {data.institutions.length} · courses: {(data.summary?.course_count as number) ?? 0} · learners: {(data.summary?.learner_count as number) ?? 0} · market: {titleCase(data.market_context?.match_type)}{data.market_context?.match_type === "fallback_global" ? " (global fallback — not district-measured demand)" : ""}{data.suppressed ? " · skill detail suppressed (small sample)" : ""}</span></p>
      {data.skills.length === 0 && <p className="an-note">No skill-level detail — {data.note || "insufficient evidence."}</p>}
      <ul className="an-skills">{data.skills.slice(0, 12).map((s) => <li key={s.skill} className="an-skill"><div className="an-skill__row"><span className="an-skill__name">{s.display_name || s.skill}</span><span className="an-skill__status">{titleCase(s.priority.level)}</span></div><div className="an-skill__detail" style={{ display: "block" }}><dl className="an-facts">
        <div><dt>Demand</dt><dd>{s.market ? <>{titleCase(s.market.trend)} <span className="an-faint">(share {share(s.market.skill_share)})</span></> : "No market evidence"}</dd></div>
        <div><dt>Learner supply</dt><dd>{share(s.training_supply.verified_coverage)} <span className="an-faint">verified ({s.training_supply.verified_learner_count} of {s.training_supply.learner_count})</span></dd></div>
        <div><dt>Curriculum</dt><dd>{s.curriculum.courses_teaching > 0 ? <>Taught in {s.curriculum.courses_teaching} <span className="an-faint">(missing in {s.curriculum.courses_missing})</span></> : "Not taught"}</dd></div>
        <div><dt>Attainment</dt><dd>{titleCase(s.gap.attainment)}</dd></div>
        <div><dt>Trainer signal</dt><dd>{titleCase(s.trainer.trainer_signal)} <span className="an-faint">({s.trainer.trainer_count} trainers)</span></dd></div>
        {s.priority.reasons.length > 0 && <div><dt>Reasons</dt><dd>{s.priority.reasons.join(" · ")}</dd></div>}
      </dl></div></li>)}</ul>
      <p className="an-note">{data.capacity.seat_note}</p>
    </>}
  </section>;
}
