import type { OutcomeOverlay } from "../../services/industry";

const pct = (v: number) => `${Math.round(v * 100)}%`;

/**
 * Phase 3 provenance block: employer demand signal as observed context.
 * Display-only: no scores, no predictions, no rankings. Always labeled
 * "Observed, not required" so it can never read as a requirement.
 */
export default function OutcomeSignal({ overlay }: { overlay: OutcomeOverlay }) {
  const s = overlay.outcome_sample;
  const w = overlay.outcome_window;
  const p = overlay.outcome_provenance;
  return (
    <section className="ct-panel" aria-label="Employer demand signal">
      <h2 className="ct-h3">Employer demand signal</h2>
      <p className="ct-muted">Observed, not required — context from recent employer outcomes, not a requirement.</p>
      <dl className="ct-gapblock__facts">
        {overlay.observed_demand != null && (
          <div>
            <dt>Observed demand</dt>
            <dd className="ct-num">{pct(overlay.observed_demand)}</dd>
          </div>
        )}
        {overlay.observed_skill_gap != null && (
          <div>
            <dt>Observed skill gap</dt>
            <dd className="ct-num">{pct(overlay.observed_skill_gap)}</dd>
          </div>
        )}
        <div>
          <dt>Sample</dt>
          <dd className="ct-num">
            {s.applied_n} applied · {s.feedback_count} observations
          </dd>
        </div>
        <div>
          <dt>Window</dt>
          <dd>
            {(w.window_from ?? "?") + " → " + (w.window_to ?? "?")}
            {overlay.stale && " (stale)"}
          </dd>
        </div>
        <div>
          <dt>Scope</dt>
          <dd>
            {p.scope}
            {p.location && p.location !== "GLOBAL" ? ` · ${p.location}` : ""}
          </dd>
        </div>
      </dl>
    </section>
  );
}
