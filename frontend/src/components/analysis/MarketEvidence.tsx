import { useEffect, useState } from "react";
import { getLabourMarketSignals, type LabourMarketSignal } from "../../services/industry";

const pct1 = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${(v * 100).toFixed(1)}%`;
const titleCase = (v?: string | null) =>
  v ? v.replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase()) : "Unknown";
const periodLabel = (s: LabourMarketSignal) => {
  const d = new Date(`${s.period_start}T00:00:00Z`);
  return Number.isNaN(d.getTime())
    ? `${s.period_start} → ${s.period_end}`
    : d.toLocaleDateString(undefined, { month: "short", year: "numeric" });
};

/** Small additive "Market evidence" block for the Industry Intelligence view.
 *
 * Shows imported/aggregated labour-market observations (or demo-seeded rows)
 * WITHOUT touching the existing baseline UI. Demo rows are always labelled
 * as synthetic — never "live".
 */
export default function MarketEvidence({ role, location }: { role: string; location?: string | null }) {
  const [signals, setSignals] = useState<LabourMarketSignal[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setSignals(null);
    setError(null);
    getLabourMarketSignals({ role })
      .then((rows) => {
        if (!cancelled) setSignals(rows);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Market evidence unavailable.");
      });
    return () => {
      cancelled = true;
    };
  }, [role]);

  if (error) return <p className="an-note">Market evidence unavailable: {error}</p>;
  if (signals === null) return <div className="an-skel an-skel--block" aria-label="Loading market evidence" />;
  if (signals.length === 0)
    return (
      <p className="an-note">
        No imported market observations for {role} yet. Baselines above remain O*NET/ESCO-grounded.
      </p>
    );

  // Latest period first, strongest share first; show a compact top-5.
  const latest = signals.reduce((a, b) => (a.period_start > b.period_start ? a : b)).period_start;
  const top = signals
    .filter((s) => s.period_start === latest)
    .sort((a, b) => (b.skill_share ?? 0) - (a.skill_share ?? 0))
    .slice(0, 5);
  const head = top[0];
  const locLabel =
    head.city || head.region || head.country || (head.location_scope === "global" ? "Global" : head.location_scope);
  const demoOnly = top.every((s) => s.data_origin === "demo_seeded");

  return (
    <section aria-label="Market evidence" style={{ marginTop: 16 }}>
      <h4 style={{ margin: "12px 0 4px" }}>Market evidence (imported observations)</h4>
      <p className="an-note">
        Role: {head.role_key} · Location: {location?.trim() || locLabel} · Period: {periodLabel(head)} ·
        Observed postings: {head.posting_count} · Source: {head.provider_id} · Data origin:{" "}
        {head.data_origin}
        {demoOnly && " (synthetic demo data — not live market data)"}
      </p>
      <ul className="an-skills">
        {top.map((s) => (
          <li key={`${s.skill_slug ?? s.source_concept}-${s.period_start}`} className="an-skill">
            <div className="an-skill__row">
              <span className="an-skill__name">{s.skill_slug ?? s.source_concept}</span>
              <span className="an-skill__nums an-num">
                <span>
                  Mentioned in {s.skill_posting_count} of {s.posting_count} postings
                </span>
                <span className="an-faint">Skill share {pct1(s.skill_share)}</span>
              </span>
              <span className="an-skill__status">{titleCase(s.trend)}</span>
            </div>
            <div className="an-skill__detail" style={{ display: "block" }}>
              <dl className="an-facts">
                <div>
                  <dt>Trend</dt>
                  <dd>
                    {titleCase(s.trend)}
                    {s.evidence_suppressed && <span className="an-faint"> · Insufficient data</span>}
                  </dd>
                </div>
                <div>
                  <dt>Confidence</dt>
                  <dd className="an-num">{pct1(s.confidence)}</dd>
                </div>
                <div>
                  <dt>Provenance</dt>
                  <dd>{s.evidence_context ?? `${s.provider_id} · ${s.period_start} → ${s.period_end}`}</dd>
                </div>
              </dl>
            </div>
          </li>
        ))}
      </ul>
      {demoOnly && (
        <p className="an-note">Demo-seeded illustration values — not verified real-time market data.</p>
      )}
    </section>
  );
}
