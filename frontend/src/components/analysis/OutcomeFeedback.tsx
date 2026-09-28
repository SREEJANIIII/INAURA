import { useState } from "react";
import { getOutcomeFeedback, type SkillOutcomeRow } from "../../services/industry";

const titleCase = (v?: string | null) => v ? v.replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase()) : "Unknown";

// Small additive outcome-feedback view for the Industry Intelligence page:
// observed employer/placement aggregates with sample sizes, periods, and
// limitations. Observed outcomes are explicitly distinguished from causal
// impact; small samples stay suppressed.
export default function OutcomeFeedback({ role }: { role: string }) {
  const [district, setDistrict] = useState("");
  const [rows, setRows] = useState<SkillOutcomeRow[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const d = district.trim();
    if (!d) return;
    setLoading(true);
    setError(null);
    getOutcomeFeedback({ district: d, role })
      .then((r) => { setRows(r.skills); setLoading(false); })
      .catch((e) => { setError(e instanceof Error ? e.message : "Outcome feedback unavailable."); setLoading(false); });
  };

  return <section aria-label="Outcome feedback">
    <div className="an-overview__bar"><span><strong>Outcome feedback</strong><span className="an-faint"> · observed outcomes, not causal impact</span></span><form onSubmit={submit} style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}><label className="an-faint" htmlFor="of-district">District</label><input id="of-district" value={district} onChange={(e) => setDistrict(e.target.value)} placeholder="e.g. Bengaluru Urban" style={{ maxWidth: 220 }} /><button type="submit" className="an-link an-link--btn">Evaluate</button></form></div>
    {rows === null && !loading && !error && <p className="an-note">Enter a district to see observed placement and employer-feedback aggregates for {role}.</p>}
    {loading && <div className="an-skel an-skel--block" aria-label="Loading outcome feedback" />}
    {error && <p className="an-empty">{error}</p>}
    {rows !== null && !loading && !error && <>
      {rows.length === 0 && <p className="an-note">No outcome observations — insufficient evidence, not evidence of no outcome.</p>}
      <ul className="an-skills">{rows.slice(0, 12).map((s) => <li key={s.skill} className="an-skill"><div className="an-skill__row"><span className="an-skill__name">{s.display_name || s.skill}</span><span className="an-skill__status">{titleCase(s.signal)}</span></div><div className="an-skill__detail" style={{ display: "block" }}><dl className="an-facts">
        <div><dt>Placements observed</dt><dd>{s.sample.placement_count ?? "—"} <span className="an-faint">({s.sample.successful_placements ?? "—"} successful)</span></dd></div>
        <div><dt>Employer feedback</dt><dd>{s.sample.feedback_count ?? "—"} observations <span className="an-faint">(avg gap {s.employer_feedback.average_observed_minus_expected ?? "—"})</span></dd></div>
        <div><dt>Limitation</dt><dd>{s.limitation}</dd></div>
      </dl></div></li>)}</ul>
      {rows.length > 12 && <p className="an-note">Showing 12 of {rows.length} skills — full detail is available from the API.</p>}
    </>}
  </section>;
}
