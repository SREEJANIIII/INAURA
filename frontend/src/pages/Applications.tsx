import { useEffect, useState } from "react";
import "./Person2.css";
import FeedbackLoopPanel from "../components/outcomes/FeedbackLoopPanel";
import {
  createApplication,
  getApplication,
  listApplications,
  transitionApplication,
  listPlacements,
  createPlacement,
  updatePlacement,
  type Application,
  type ApplicationDetail,
  type ApplicationStatus,
  type Placement,
} from "../services/outcomes";
import {
  formatStatusLabel,
  formatOutcomeLabel,
  getAllowedStudentTransitions,
  isTerminalStatus,
} from "../lib/applicationsModel";

const messageOf = (e: unknown) => (e instanceof Error ? e.message : String(e));

type FilterTab = "all" | "saved" | "active" | "resolved";

export default function Applications() {
  const [apps, setApps] = useState<Application[]>([]);
  const [detail, setDetail] = useState<ApplicationDetail | null>(null);
  const [requirementId, setRequirementId] = useState("");
  const [applyNote, setApplyNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [tab, setTab] = useState<FilterTab>("all");
  const [withdrawReason, setWithdrawReason] = useState("");
  const [showWithdrawBox, setShowWithdrawBox] = useState(false);
  const [placements, setPlacements] = useState<Placement[]>([]);
  const [joiningDateInput, setJoiningDateInput] = useState("");
  const [savingPlacement, setSavingPlacement] = useState(false);

  const refresh = () => {
    listPlacements()
      .then(setPlacements)
      .catch(() => {});
    return listApplications()
      .then((rows) => {
        setApps(rows);
        if (detail) {
          const still = rows.find((r) => r.id === detail.id);
          if (still) {
            void open(still.id);
          }
        }
      })
      .catch((e) => setError(messageOf(e)));
  };

  useEffect(() => {
    void refresh();
  }, []);

  const handleCreate = async (initialStatus: "saved" | "applied") => {
    if (!requirementId.trim()) {
      setError("Please enter a hiring requirement ID");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const created = await createApplication(requirementId.trim(), {
        initial_status: initialStatus,
        note: applyNote.trim() || undefined,
      });
      setRequirementId("");
      setApplyNote("");
      await refresh();
      await open(created.id);
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setSaving(false);
    }
  };

  const open = async (id: string) => {
    setError(null);
    setShowWithdrawBox(false);
    setWithdrawReason("");
    try {
      setDetail(await getApplication(id));
    } catch (e) {
      setError(messageOf(e));
    }
  };

  const handleTransition = async (toStatus: ApplicationStatus, note?: string) => {
    if (!detail) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await transitionApplication(detail.id, toStatus, note);
      setDetail(await getApplication(updated.id));
      setShowWithdrawBox(false);
      setWithdrawReason("");
      await refresh();
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setSaving(false);
    }
  };

  const handleRecordJoining = async (existingPlacementId?: string) => {
    if (!detail) return;
    if (!joiningDateInput) {
      setError("Please select a valid joining date.");
      return;
    }
    setSavingPlacement(true);
    setError(null);
    try {
      if (existingPlacementId) {
        await updatePlacement(existingPlacementId, {
          status: "joined",
          joining_date: joiningDateInput,
        });
      } else {
        await createPlacement({
          application_id: detail.id,
          role_title: detail.requirement_title || "Selected Candidate",
          status: "joined",
          joining_date: joiningDateInput,
        });
      }
      setJoiningDateInput("");
      await refresh();
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setSavingPlacement(false);
    }
  };

  const handleDeclineOffer = async (existingPlacementId?: string) => {
    if (!detail) return;
    setSavingPlacement(true);
    setError(null);
    try {
      if (existingPlacementId) {
        await updatePlacement(existingPlacementId, { status: "declined" });
      } else {
        await createPlacement({
          application_id: detail.id,
          role_title: detail.requirement_title || "Selected Candidate",
          status: "declined",
        });
      }
      await refresh();
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setSavingPlacement(false);
    }
  };

  const filteredApps = apps.filter((a) => {
    if (tab === "saved") return a.status === "saved";
    if (tab === "active") return ["applied", "screening", "interview", "offer_received"].includes(a.status);
    if (tab === "resolved") return isTerminalStatus(a.status);
    return true;
  });

  const studentAllowed = detail ? getAllowedStudentTransitions(detail.status) : [];

  return (
    <main className="p2">
      <header className="p2__head">
        <h1>Applications &amp; Career Track</h1>
        <p>Track your saved and active applications. Every milestone and decision is recorded in an immutable audit timeline.</p>
      </header>

      {error && <p className="p2__error">{error}</p>}

      <div className="p2__cols">
        <section>
          <h2>Your Applications ({apps.length})</h2>

          {/* Filter Tabs */}
          <div className="p2__tabs">
            <button
              type="button"
              className={`p2__tab${tab === "all" ? " is-active" : ""}`}
              onClick={() => setTab("all")}
            >
              All ({apps.length})
            </button>
            <button
              type="button"
              className={`p2__tab${tab === "saved" ? " is-active" : ""}`}
              onClick={() => setTab("saved")}
            >
              Saved ({apps.filter((a) => a.status === "saved").length})
            </button>
            <button
              type="button"
              className={`p2__tab${tab === "active" ? " is-active" : ""}`}
              onClick={() => setTab("active")}
            >
              Active ({apps.filter((a) => ["applied", "screening", "interview", "offer_received"].includes(a.status)).length})
            </button>
            <button
              type="button"
              className={`p2__tab${tab === "resolved" ? " is-active" : ""}`}
              onClick={() => setTab("resolved")}
            >
              Resolved ({apps.filter((a) => isTerminalStatus(a.status)).length})
            </button>
          </div>

          <ul className="p2__list">
            {filteredApps.map((a) => (
              <li key={a.id}>
                <button
                  type="button"
                  className={`p2__pick${detail?.id === a.id ? " is-active" : ""}`}
                  onClick={() => open(a.id)}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "0.5rem" }}>
                    <div>
                      <strong>{a.requirement_title || `Role (${a.hiring_requirement_id.slice(0, 8)}…)`}</strong>
                      {a.employer_name && <div className="p2__hint">{a.employer_name}</div>}
                    </div>
                    <span className={`p2__badge p2__badge--${a.status}`}>
                      {formatStatusLabel(a.status)}
                    </span>
                  </div>
                  <div className="p2__meta" style={{ marginTop: "0.35rem" }}>
                    {a.outcome && <span>Outcome: <strong>{formatOutcomeLabel(a.outcome)}</strong></span>}
                    {a.created_at && (
                      <span>Created: {new Date(a.created_at).toLocaleDateString()}</span>
                    )}
                  </div>
                </button>
              </li>
            ))}
            {filteredApps.length === 0 && (
              <li className="p2__hint">No applications found in this category.</li>
            )}
          </ul>

          {/* New Application Form */}
          <div className="p2__form" style={{ marginTop: "1.5rem" }}>
            <h3>Save or Apply to a Role</h3>
            <input
              aria-label="Hiring requirement ID"
              placeholder="Hiring requirement ID (from open roles) *"
              value={requirementId}
              onChange={(e) => setRequirementId(e.target.value)}
            />
            <input
              aria-label="Optional note"
              placeholder="Application note or candidate message (optional)"
              value={applyNote}
              onChange={(e) => setApplyNote(e.target.value)}
            />
            <div className="p2__row" style={{ marginTop: "0.25rem" }}>
              <button
                type="button"
                className="p2__btn"
                onClick={() => handleCreate("applied")}
                disabled={saving || !requirementId.trim()}
              >
                {saving ? "Processing…" : "Apply Directly"}
              </button>
              <button
                type="button"
                className="p2__btn p2__btn--ghost"
                onClick={() => handleCreate("saved")}
                disabled={saving || !requirementId.trim()}
              >
                Save for Later
              </button>
            </div>
          </div>
        </section>

        {/* Selected Application Timeline & Actions */}
        <section>
          <h2>Application Timeline</h2>
          {!detail ? (
            <p className="p2__hint">Select an application from the list to view its audit timeline and available actions.</p>
          ) : (
            <div className="p2__detail">
              <div className="p2__detail-header">
                <div>
                  <h3 style={{ margin: 0 }}>
                    {detail.requirement_title || `Requirement ${detail.hiring_requirement_id.slice(0, 8)}…`}
                  </h3>
                  {detail.employer_name && (
                    <div className="p2__hint" style={{ fontSize: "0.95rem", marginTop: "0.15rem" }}>
                      {detail.employer_name}
                    </div>
                  )}
                </div>
                <span className={`p2__badge p2__badge--${detail.status}`}>
                  {formatStatusLabel(detail.status)}
                </span>
              </div>

              <div className="p2__meta">
                <span><strong>Status:</strong> {formatStatusLabel(detail.status)}</span>
                {detail.outcome && (
                  <span><strong>Outcome:</strong> {formatOutcomeLabel(detail.outcome)}</span>
                )}
                {detail.applied_at && (
                  <span><strong>Applied:</strong> {new Date(detail.applied_at).toLocaleDateString()}</span>
                )}
                <span><strong>ID:</strong> <code>{detail.id.slice(0, 8)}…</code></span>
              </div>

              {/* Action Controls for Student */}
              {studentAllowed.length > 0 && (
                <div style={{ marginTop: "0.5rem" }}>
                  <div className="p2__row">
                    {studentAllowed.includes("applied") && (
                      <button
                        type="button"
                        className="p2__btn"
                        onClick={() => handleTransition("applied")}
                        disabled={saving}
                      >
                        Submit Application Now
                      </button>
                    )}
                    {studentAllowed.includes("withdrawn") && !showWithdrawBox && (
                      <button
                        type="button"
                        className="p2__btn p2__btn--danger-ghost"
                        onClick={() => setShowWithdrawBox(true)}
                        disabled={saving}
                      >
                        Withdraw Application
                      </button>
                    )}
                  </div>

                  {showWithdrawBox && (
                    <div className="p2__form" style={{ marginTop: "0.5rem" }}>
                      <input
                        placeholder="Withdrawal reason (optional)"
                        value={withdrawReason}
                        onChange={(e) => setWithdrawReason(e.target.value)}
                      />
                      <div className="p2__row">
                        <button
                          type="button"
                          className="p2__btn p2__btn--danger"
                          onClick={() => handleTransition("withdrawn", withdrawReason.trim() || undefined)}
                          disabled={saving}
                        >
                          Confirm Withdrawal
                        </button>
                        <button
                          type="button"
                          className="p2__btn p2__btn--ghost"
                          onClick={() => {
                            setShowWithdrawBox(false);
                            setWithdrawReason("");
                          }}
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {isTerminalStatus(detail.status) && (
                <p className="p2__hint" style={{ marginTop: "0.5rem" }}>
                  This application has concluded with status <strong>{formatStatusLabel(detail.status)}</strong>.
                </p>
              )}

              {/* Placement & Joining Tracking */}
              {(detail.status === "selected" || placements.some((p) => p.application_id === detail.id)) && (() => {
                const currentPlacement = placements.find((p) => p.application_id === detail.id);
                return (
                  <div
                    className="p2__card"
                    style={{
                      marginTop: "1rem",
                      borderLeft: "4px solid #10b981",
                      background: "rgba(16, 185, 129, 0.05)",
                    }}
                  >
                    <h4 style={{ margin: "0 0 0.5rem 0", display: "flex", alignItems: "center", gap: "0.5rem" }}>
                      <span>Placement Outcome &amp; Joining</span>
                      {currentPlacement && (
                        <span className={`p2__badge p2__badge--${currentPlacement.status}`}>
                          {formatStatusLabel(currentPlacement.status)}
                        </span>
                      )}
                    </h4>
                    <div className="p2__meta" style={{ marginBottom: "0.5rem" }}>
                      <span><strong>Employer:</strong> {detail.employer_name || currentPlacement?.employer_name || "Employer"}</span>
                      <span><strong>Role:</strong> {detail.requirement_title || currentPlacement?.role_title || "Selected Candidate"}</span>
                      {currentPlacement?.joining_date && (
                        <span><strong>Joining Date:</strong> {new Date(currentPlacement.joining_date).toLocaleDateString()}</span>
                      )}
                      {currentPlacement && (
                        <span><strong>Verification:</strong> {currentPlacement.verification_status} ({currentPlacement.outcome_source})</span>
                      )}
                    </div>

                    {(!currentPlacement || currentPlacement.status === "selected" || currentPlacement.status === "offer_accepted") && (
                      <div style={{ marginTop: "0.5rem" }}>
                        <p className="p2__hint" style={{ marginBottom: "0.5rem" }}>
                          Confirm your joining date or update your outcome decision:
                        </p>
                        <div className="p2__row" style={{ alignItems: "center", gap: "0.5rem" }}>
                          <input
                            type="date"
                            value={joiningDateInput}
                            onChange={(e) => setJoiningDateInput(e.target.value)}
                            style={{ width: "auto" }}
                          />
                          <button
                            type="button"
                            className="p2__btn"
                            disabled={savingPlacement || !joiningDateInput}
                            onClick={() => handleRecordJoining(currentPlacement?.id)}
                          >
                            Confirm &amp; Record Joining
                          </button>
                          <button
                            type="button"
                            className="p2__btn p2__btn--ghost"
                            disabled={savingPlacement}
                            onClick={() => handleDeclineOffer(currentPlacement?.id)}
                          >
                            Decline Offer
                          </button>
                        </div>
                      </div>
                    )}

                    {currentPlacement?.status === "joined" && (
                      <p className="p2__hint" style={{ color: "#10b981", fontWeight: 500, marginTop: "0.5rem" }}>
                        ✓ You have joined this role on {new Date(currentPlacement.joining_date || "").toLocaleDateString()}. Status is {currentPlacement.verification_status}.
                      </p>
                    )}

                    {currentPlacement?.status === "declined" && (
                      <p className="p2__hint" style={{ color: "#ef4444", fontWeight: 500, marginTop: "0.5rem" }}>
                        You have declined this placement offer.
                      </p>
                    )}
                  </div>
                );
              })()}

              {/* Chronological Event History */}
              <h4 style={{ marginTop: "1rem", marginBottom: "0.25rem" }}>Event History ({detail.events.length})</h4>
              <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
                {detail.events.map((ev) => (
                  <div key={ev.id} className="p2__timeline-item">
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <div>
                        {ev.from_status ? (
                          <span>
                            {formatStatusLabel(ev.from_status)} → <strong>{formatStatusLabel(ev.to_status)}</strong>
                          </span>
                        ) : (
                          <span>Created as <strong>{formatStatusLabel(ev.to_status)}</strong></span>
                        )}
                      </div>
                      <span className="p2__badge" style={{ fontSize: "0.7rem" }}>
                        {ev.actor}
                      </span>
                    </div>
                    {ev.note && <div style={{ fontSize: "0.85rem", opacity: 0.9 }}>{ev.note}</div>}
                    <div className="p2__timeline-meta">
                      <span>{new Date(ev.created_at).toLocaleString()}</span>
                    </div>
                  </div>
                ))}
                {detail.events.length === 0 && <p className="p2__hint">No events logged.</p>}
              </div>

              {/* Feedback Loop Panel */}
              <FeedbackLoopPanel applicationId={detail.id} />
            </div>
          )}
        </section>
      </div>
    </main>
  );
}

