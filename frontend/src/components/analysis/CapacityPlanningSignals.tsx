import { useState } from "react";
import { getCapacityPlanning, type CapacityPlanningRow } from "../../services/industry";

const titleCase = (v?: string | null) => v ? v.replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase()) : "Unknown";

// Small additive capacity view for the Industry Intelligence page: observed
// institutions/courses/learners/trainers per prioritized skill, each row
// carrying the explicit statement that seat capacity is not measured.
// Missing data is never shown as zero capacity or as a shortage.
export default function CapacityPlanningSignals({ role }: { role: string }) {
  const [district, setDistrict] = useState("");
  const [state, setState] = useState("");
  const [rows, setRows] = useState<CapacityPlanningRow[] | null>(null);
  const [note, setNote] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const d = district.trim();
    if (!d) return;
    setLoading(true);
    setError(null);
    getCapacityPlanning({ district: d, state: state.trim() || undefined, role })
      .then((r) => { setRows(r.capacity); setNote(r.planning_note); setLoading(false); })
      .catch((e) => { setError(e instanceof Error ? e.message : "Capacity signals unavailable."); setLoading(false); });
  };

  return <section aria-label="Capacity planning signals">
    <div className="an-overview__bar"><span><strong>Capacity planning signals</strong><span className="an-faint"> · observed inputs only, no seat claims</span></span><form onSubmit={submit} style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}><label className="an-faint" htmlFor="cap-district">District</label><input id="cap-district" value={district} onChange={(e) => setDistrict(e.target.value)} placeholder="e.g. Bengaluru Urban" style={{ maxWidth: 220 }} /><label className="an-faint" htmlFor="cap-state">State</label><input id="cap-state" value={state} onChange={(e) => setState(e.target.value)} placeholder="optional" style={{ maxWidth: 160 }} /><button type="submit" className="an-link an-link--btn">Evaluate</button></form></div>
    {rows === null && !loading && !error && <p className="an-note">Enter a district to see what capacity evidence exists for {role} priorities. Seat capacity is not measured anywhere in the repository.</p>}
    {loading && <div className="an-skel an-skel--block" aria-label="Loading capacity signals" />}
    {error && <p className="an-empty">{error}</p>}
    {rows !== null && !loading && !error && <>
      {rows.length === 0 && <p className="an-note">No capacity rows — no prioritized skills with evidence in this context.</p>}
      <ul className="an-skills">{rows.slice(0, 12).map((r) => <li key={r.skill} className="an-skill"><div className="an-skill__row"><span className="an-skill__name">{r.display_name || r.skill}</span><span className="an-skill__status">{titleCase(r.capacity_status)}</span></div><div className="an-skill__detail" style={{ display: "block" }}><dl className="an-facts">
        <div><dt>Courses teaching</dt><dd>{r.courses_teaching} <span className="an-faint">of {r.institutions_total} institutions</span></dd></div>
        <div><dt>Learners</dt><dd>{r.verified_learner_count} verified <span className="an-faint">of {r.learner_count}</span></dd></div>
        <div><dt>Trainers observed</dt><dd>{r.trainers_observed}</dd></div>
        <div><dt>Planning note</dt><dd>{r.planning_note}</dd></div>
      </dl></div></li>)}</ul>
      {rows.length > 12 && <p className="an-note">Showing 12 of {rows.length} rows — full detail is available from the API.</p>}
      {note && <p className="an-note">{note}</p>}
    </>}
  </section>;
}
