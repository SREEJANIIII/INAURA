import { useState } from "react";
import { getTrainerDevelopmentSignals, type TrainerDevelopmentSignalRow } from "../../services/industry";

const titleCase = (v?: string | null) => v ? v.replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase()) : "Unknown";

// Small additive trainer-signal view for the Industry Intelligence page:
// real P1.3 signal records (mapping evidence vs teaching context) with
// reasons and linked proposals. No trainer identities, no assignment.
export default function TrainerDevelopmentSignals({ role }: { role: string }) {
  const [district, setDistrict] = useState("");
  const [state, setState] = useState("");
  const [rows, setRows] = useState<TrainerDevelopmentSignalRow[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const d = district.trim();
    if (!d) return;
    setLoading(true);
    setError(null);
    getTrainerDevelopmentSignals({ district: d, state: state.trim() || undefined, role })
      .then((r) => { setRows(r.signals); setLoading(false); })
      .catch((e) => { setError(e instanceof Error ? e.message : "Trainer signals unavailable."); setLoading(false); });
  };

  return <section aria-label="Trainer development signals">
    <div className="an-overview__bar"><span><strong>Trainer development signals</strong><span className="an-faint"> · mapping evidence only, never assignment</span></span><form onSubmit={submit} style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}><label className="an-faint" htmlFor="tdev-district">District</label><input id="tdev-district" value={district} onChange={(e) => setDistrict(e.target.value)} placeholder="e.g. Bengaluru Urban" style={{ maxWidth: 220 }} /><label className="an-faint" htmlFor="tdev-state">State</label><input id="tdev-state" value={state} onChange={(e) => setState(e.target.value)} placeholder="optional" style={{ maxWidth: 160 }} /><button type="submit" className="an-link an-link--btn">Evaluate</button></form></div>
    {rows === null && !loading && !error && <p className="an-note">Enter a district to see which actionable priorities lack observed trainer mappings for {role}. Absence of a mapping is not evidence of inability.</p>}
    {loading && <div className="an-skel an-skel--block" aria-label="Loading trainer signals" />}
    {error && <p className="an-empty">{error}</p>}
    {rows !== null && !loading && !error && <>
      {rows.length === 0 && <p className="an-note">No trainer signals — no actionable priorities or no district data.</p>}
      <ul className="an-skills">{rows.slice(0, 12).map((s) => <li key={s.skill} className="an-skill"><div className="an-skill__row"><span className="an-skill__name">{s.display_name || s.skill}</span><span className="an-skill__status">{titleCase(s.signal)}</span></div><div className="an-skill__detail" style={{ display: "block" }}><dl className="an-facts">
        <div><dt>Signal</dt><dd>{titleCase(s.signal_type)}</dd></div>
        <div><dt>Trainer evidence</dt><dd>{s.trainer_evidence.trainer_count} mapped <span className="an-faint">in {s.trainer_evidence.institutions_with_skill_trainers} of {s.trainer_evidence.institutions_teaching} teaching institutions</span></dd></div>
        {s.reasons.length > 0 && <div><dt>Reasons</dt><dd>{s.reasons.join(" · ")}</dd></div>}
        {s.related_proposals.length > 0 && <div><dt>Proposals</dt><dd>{s.related_proposals.map((p) => `${p.action_type} (${p.course_id.slice(0, 8)})`).join(" · ")}</dd></div>}
      </dl></div></li>)}</ul>
      {rows.length > 12 && <p className="an-note">Showing 12 of {rows.length} signals — full detail is available from the API.</p>}
    </>}
  </section>;
}
