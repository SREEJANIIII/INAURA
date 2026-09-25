import Button from "../ui/app-button";

export type LedgerSource = { key: string; label: string; present: boolean };

type EvidenceLedgerProps = {
  sources: LedgerSource[];
  /** The role everything here is being compared against */
  role: string | null;
  /** When the last analysis finished, already formatted, or null if it never has */
  lastRun: string | null;
  running: boolean;
  onRun: () => void;
  /** Why the run button can't be pressed yet, or null when it can */
  blocked: string | null;
};

/**
 * What the student has gathered, and the button that uses it.
 *
 * The tally is a count and never a score — ten strokes for ten named sources. The page is
 * explicit that this isn't readiness, so it must not look like a percentage or a meter.
 */
export default function EvidenceLedger({ sources, role, lastRun, running, onRun, blocked }: EvidenceLedgerProps) {
  const gathered = sources.filter((s) => s.present);
  const missing = sources.filter((s) => !s.present);

  return (
    <aside className="ledger" aria-labelledby="ledger-title">
      <h2 className="ledger__title" id="ledger-title">
        What you’ve gathered
      </h2>

      <ul className="ledger__tally">
        {sources.map((s) => (
          <li key={s.key} className={`ledger__mark${s.present ? " is-in" : ""}`}>
            <span className="ledger__mark-label">{s.label}</span>
          </li>
        ))}
      </ul>

      <p className="ledger__count">
        <span className="ledger__count-num">{gathered.length}</span>
        <span className="ledger__count-of">of {sources.length} kinds of proof</span>
      </p>

      {missing.length > 0 && (
        <p className="ledger__missing">
          Still to add: {missing.map((s) => s.label).join(", ")}
        </p>
      )}

      <div className="ledger__run">
        <Button variant="primary" size="md" onClick={onRun} disabled={running || !!blocked}>
          {running ? "Running…" : lastRun ? "Run analysis again" : "Run analysis"}
        </Button>
        <p className="ledger__run-note">
          {blocked
            ? blocked
            : running
              ? "Reading your evidence against the role."
              : lastRun
                ? `Last run ${lastRun}. Run it again to take in what you've added since.`
                : role
                  ? `INAURA will compare all of this against ${role} and build your roadmap.`
                  : "INAURA will compare all of this against your role and build your roadmap."}
        </p>
      </div>
    </aside>
  );
}
