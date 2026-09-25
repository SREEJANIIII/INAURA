import { useEffect, useState } from "react";
import "./Person2.css";
import FeedbackLoopPanel from "../components/outcomes/FeedbackLoopPanel";
import {
  createApplication,
  getApplication,
  listApplications,
  transitionApplication,
  type Application,
  type ApplicationDetail,
  type ApplicationStatus,
} from "../services/outcomes";

const messageOf = (e: unknown) => (e instanceof Error ? e.message : String(e));

const NEXT_BY_STATUS: Record<string, ApplicationStatus[]> = {
  saved: ["applied", "withdrawn"],
  applied: ["withdrawn"],
  screening: ["withdrawn"],
  interview: ["withdrawn"],
  offer_received: ["withdrawn"],
  selected: [],
  rejected: [],
  withdrawn: [],
};

export default function Applications() {
  const [apps, setApps] = useState<Application[]>([]);
  const [detail, setDetail] = useState<ApplicationDetail | null>(null);
  const [requirementId, setRequirementId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const refresh = () =>
    listApplications()
      .then(setApps)
      .catch((e) => setError(messageOf(e)));

  useEffect(() => {
    void refresh();
  }, []);

  const add = async () => {
    if (!requirementId.trim()) {
      setError("Paste a hiring requirement ID (from the Employers page)");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await createApplication(requirementId.trim());
      setRequirementId("");
      await refresh();
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setSaving(false);
    }
  };

  const open = async (id: string) => {
    setError(null);
    try {
      setDetail(await getApplication(id));
    } catch (e) {
      setError(messageOf(e));
    }
  };

  const transition = async (to_status: ApplicationStatus) => {
    if (!detail) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await transitionApplication(detail.id, to_status);
      setDetail(await getApplication(updated.id));
      await refresh();
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <main className="p2">
      <header className="p2__head">
        <h1>Applications</h1>
        <p>Track each application from saved to final outcome. History is append-only.</p>
      </header>
      {error && <p className="p2__error">{error}</p>}
      <div className="p2__cols">
        <section>
          <h2>Your applications</h2>
          <ul className="p2__list">
            {apps.map((a) => (
              <li key={a.id}>
                <button
                  type="button"
                  className={`p2__pick${detail?.id === a.id ? " is-active" : ""}`}
                  onClick={() => open(a.id)}
                >
                  <strong>{a.status}</strong>
                  {a.outcome && <span> · {a.outcome}</span>}
                  <span> · {a.id.slice(0, 8)}…</span>
                </button>
              </li>
            ))}
            {apps.length === 0 && <li>No applications yet.</li>}
          </ul>
          <div className="p2__form">
            <input
              aria-label="Hiring requirement ID"
              placeholder="Hiring requirement ID"
              value={requirementId}
              onChange={(e) => setRequirementId(e.target.value)}
            />
            <button type="button" onClick={add} disabled={saving}>
              {saving ? "Saving…" : "Save application"}
            </button>
          </div>
        </section>
        <section>
          <h2>Timeline</h2>
          {!detail ? (
            <p>Select an application to see its event history.</p>
          ) : (
            <>
              <p>
                Status: <strong>{detail.status}</strong>
                {detail.outcome && (
                  <>
                    {" "}· outcome: <strong>{detail.outcome}</strong>
                  </>
                )}
              </p>
              <ol className="p2__timeline">
                {detail.events.map((ev) => (
                  <li key={ev.id}>
                    {ev.from_status ?? "—"} → <strong>{ev.to_status}</strong>
                    {ev.note && <span> · {ev.note}</span>}
                  </li>
                ))}
                {detail.events.length === 0 && <li>No events yet.</li>}
              </ol>
              {NEXT_BY_STATUS[detail.status]?.length > 0 && (
                <div className="p2__row">
                  {NEXT_BY_STATUS[detail.status].map((s) => (
                    <button key={s} type="button" onClick={() => transition(s)} disabled={saving}>
                      {s === "applied" ? "Apply" : s === "withdrawn" ? "Withdraw" : s}
                    </button>
                  ))}
                </div>
              )}
              <p className="p2__hint">
                Screening, interview, offer, selection, and rejection are set by the employer —
                your controls here are applying and withdrawing.
              </p>
              <FeedbackLoopPanel applicationId={detail.id} />
            </>
          )}
        </section>
      </div>
    </main>
  );
}
