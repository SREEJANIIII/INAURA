import { useState, useEffect, useCallback } from "react";
import { useEmployer } from "../../context/EmployerContext";
import {
  listPlacementsForEmployer,
  listApplicationsForEmployer,
  createPlacement,
  updatePlacement,
  confirmPlacement,
  type Placement,
  type Application,
} from "../../services/outcomes";
import { formatStatusLabel } from "../../lib/applicationsModel";
import "../../components/employer/EmployerComponents.css";

export default function EmployerPlacements() {
  const { currentEmployer } = useEmployer();

  const [placements, setPlacements] = useState<Placement[]>([]);
  const [selectedApps, setSelectedApps] = useState<Application[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // New placement record modal/form state
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newAppId, setNewAppId] = useState("");
  const [newRoleTitle, setNewRoleTitle] = useState("");
  const [newJoiningDate, setNewJoiningDate] = useState("");
  const [creating, setCreating] = useState(false);

  // Updating joining date inline
  const [editingPlId, setEditingPlId] = useState<string | null>(null);
  const [editDate, setEditDate] = useState("");
  const [updatingPl, setUpdatingPl] = useState(false);

  const loadData = useCallback(async () => {
    if (!currentEmployer) return;
    setLoading(true);
    setError(null);
    try {
      const [pls, apps] = await Promise.all([
        listPlacementsForEmployer(currentEmployer.id),
        listApplicationsForEmployer(currentEmployer.id),
      ]);
      setPlacements(pls);
      // Candidates with status === 'selected' or 'offer_received'
      setSelectedApps(apps.filter((a) => a.status === "selected" || a.status === "offer_received"));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [currentEmployer]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const handleCreatePlacement = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!currentEmployer) return;
    if (!newRoleTitle.trim()) {
      setError("Role title is required.");
      return;
    }

    setCreating(true);
    setError(null);
    try {
      await createPlacement({
        employer_id: currentEmployer.id,
        application_id: newAppId || null,
        role_title: newRoleTitle.trim(),
        joining_date: newJoiningDate || null,
        status: "pending",
      });
      setShowCreateModal(false);
      setNewAppId("");
      setNewRoleTitle("");
      setNewJoiningDate("");
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setCreating(false);
    }
  };

  const handleConfirm = async (placementId: string, verified: boolean) => {
    setError(null);
    try {
      await confirmPlacement(placementId, verified);
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const handleUpdateStatus = async (placementId: string, status: string, date?: string) => {
    setUpdatingPl(true);
    setError(null);
    try {
      await updatePlacement(placementId, {
        status,
        joining_date: date || undefined,
      });
      setEditingPlId(null);
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setUpdatingPl(false);
    }
  };

  if (!currentEmployer) {
    return (
      <div style={{ padding: "3rem", textAlign: "center", color: "var(--muted)" }}>
        Please select or register a company first to manage placements.
      </div>
    );
  }

  const verifiedCount = placements.filter((p) => p.verification_status === "verified").length;
  const joinedCount = placements.filter((p) => p.status === "joined").length;
  const pendingCount = placements.filter((p) => p.verification_status !== "verified").length;

  return (
    <div>
      <div className="emp-page-header">
        <div>
          <h1>Placement Records &amp; Hiring Verification</h1>
          <p>
            Verify candidate joining, confirm official offers, and manage employment outcomes for <strong>{currentEmployer.name}</strong>.
          </p>
        </div>
        <div className="emp-header-actions">
          <button
            type="button"
            className="emp-btn emp-btn--primary"
            onClick={() => setShowCreateModal(true)}
          >
            + Create Placement Record
          </button>
        </div>
      </div>

      {error && (
        <div style={{ background: "#fef2f2", color: "#dc2626", padding: "0.6rem 0.85rem", borderRadius: "8px", marginBottom: "1rem", fontSize: "0.85rem" }}>
          {error}
        </div>
      )}

      {/* Summary Cards */}
      <div className="emp-stats-grid">
        <div className="emp-stat-box">
          <span className="emp-stat-box__label">Total Placements</span>
          <span className="emp-stat-box__val">{placements.length}</span>
          <span className="emp-stat-box__sub">Established records</span>
        </div>
        <div className="emp-stat-box">
          <span className="emp-stat-box__label">Verified Hires</span>
          <span className="emp-stat-box__val">{verifiedCount}</span>
          <span className="emp-stat-box__sub">Outcome confirmed</span>
        </div>
        <div className="emp-stat-box">
          <span className="emp-stat-box__label">Joined Candidates</span>
          <span className="emp-stat-box__val">{joinedCount}</span>
          <span className="emp-stat-box__sub">Onboarded team members</span>
        </div>
        <div className="emp-stat-box">
          <span className="emp-stat-box__label">Pending Verification</span>
          <span className="emp-stat-box__val">{pendingCount}</span>
          <span className="emp-stat-box__sub">Awaiting confirmation</span>
        </div>
      </div>

      {loading ? (
        <div style={{ padding: "3rem", textAlign: "center", color: "var(--muted)" }}>
          Loading placement outcomes…
        </div>
      ) : placements.length === 0 ? (
        <div className="emp-card emp-empty-state">
          <h3>No placement records established yet</h3>
          <p>
            When candidates complete your interview loop and accept an offer, you can establish their placement outcome here.
          </p>
          <button
            type="button"
            className="emp-btn emp-btn--primary"
            onClick={() => setShowCreateModal(true)}
          >
            + Establish Placement
          </button>
        </div>
      ) : (
        <div className="emp-table-wrap">
          <table className="emp-table">
            <thead>
              <tr>
                <th>Candidate / Student</th>
                <th>Role Title</th>
                <th>Joining Date</th>
                <th>Placement Status</th>
                <th>Verification</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {placements.map((pl) => (
                <tr key={pl.id}>
                  <td>
                    <div>
                      <strong>Candidate</strong>
                    </div>
                    <div style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
                      Student ID: <code>{pl.student_id.slice(0, 10)}…</code>
                    </div>
                  </td>
                  <td>
                    <strong>{pl.role_title}</strong>
                  </td>
                  <td>
                    {editingPlId === pl.id ? (
                      <div style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
                        <input
                          type="date"
                          className="emp-input"
                          style={{ padding: "0.25rem 0.5rem", fontSize: "0.8rem" }}
                          value={editDate}
                          onChange={(e) => setEditDate(e.target.value)}
                        />
                        <button
                          type="button"
                          className="emp-btn emp-btn--primary emp-btn--sm"
                          disabled={updatingPl}
                          onClick={() => handleUpdateStatus(pl.id, pl.status, editDate)}
                        >
                          Save
                        </button>
                        <button
                          type="button"
                          className="emp-btn emp-btn--secondary emp-btn--sm"
                          onClick={() => setEditingPlId(null)}
                        >
                          ✕
                        </button>
                      </div>
                    ) : (
                      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                        <span>
                          {pl.joining_date
                            ? new Date(pl.joining_date).toLocaleDateString()
                            : "Pending Date"}
                        </span>
                        <button
                          type="button"
                          className="emp-btn emp-btn--secondary emp-btn--sm"
                          style={{ padding: "0.15rem 0.4rem", fontSize: "0.75rem" }}
                          onClick={() => {
                            setEditingPlId(pl.id);
                            setEditDate(pl.joining_date ? pl.joining_date.split("T")[0] : "");
                          }}
                        >
                          ✎
                        </button>
                      </div>
                    )}
                  </td>
                  <td>
                    <span className={`emp-badge emp-badge--${pl.status}`}>
                      {formatStatusLabel(pl.status)}
                    </span>
                  </td>
                  <td>
                    <span
                      className={`emp-badge emp-badge--${
                        pl.verification_status === "verified" ? "open" : "suspended"
                      }`}
                    >
                      {pl.verification_status}
                    </span>
                  </td>
                  <td>
                    <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap" }}>
                      {pl.verification_status !== "verified" && (
                        <button
                          type="button"
                          className="emp-btn emp-btn--primary emp-btn--sm"
                          onClick={() => handleConfirm(pl.id, true)}
                        >
                          ✓ Confirm
                        </button>
                      )}
                      {pl.verification_status !== "disputed" && pl.verification_status !== "verified" && (
                        <button
                          type="button"
                          className="emp-btn emp-btn--secondary emp-btn--sm"
                          onClick={() => handleConfirm(pl.id, false)}
                        >
                          Dispute
                        </button>
                      )}
                      {pl.status !== "joined" && (
                        <button
                          type="button"
                          className="emp-btn emp-btn--secondary emp-btn--sm"
                          onClick={() => handleUpdateStatus(pl.id, "joined")}
                        >
                          Mark Joined
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Create Placement Modal */}
      {showCreateModal && (
        <div className="emp-modal-overlay" onClick={() => setShowCreateModal(false)} role="dialog" aria-modal="true">
          <div className="emp-modal" onClick={(e) => e.stopPropagation()}>
            <div className="emp-modal__header">
              <h2 style={{ fontSize: "1.2rem", fontWeight: 700, margin: 0 }}>
                Establish Placement Record
              </h2>
              <button
                type="button"
                className="emp-modal__close"
                onClick={() => setShowCreateModal(false)}
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleCreatePlacement}>
              <div className="emp-field" style={{ marginBottom: "1rem" }}>
                <label className="emp-label">Linked Candidate Application</label>
                <select
                  className="emp-select"
                  value={newAppId}
                  onChange={(e) => {
                    setNewAppId(e.target.value);
                    const matched = selectedApps.find((a) => a.id === e.target.value);
                    if (matched?.requirement_title) {
                      setNewRoleTitle(matched.requirement_title);
                    }
                  }}
                >
                  <option value="">Select a candidate application (optional)</option>
                  {selectedApps.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.candidate_name || `Candidate ${a.student_id.slice(0, 8)}`} — {a.requirement_title || "Requirement"} ({formatStatusLabel(a.status)})
                    </option>
                  ))}
                </select>
              </div>

              <div className="emp-field" style={{ marginBottom: "1rem" }}>
                <label className="emp-label">Job Role Title *</label>
                <input
                  type="text"
                  className="emp-input"
                  placeholder="e.g. Associate Software Engineer"
                  value={newRoleTitle}
                  onChange={(e) => setNewRoleTitle(e.target.value)}
                  required
                />
              </div>

              <div className="emp-field" style={{ marginBottom: "1.25rem" }}>
                <label className="emp-label">Expected Joining Date</label>
                <input
                  type="date"
                  className="emp-input"
                  value={newJoiningDate}
                  onChange={(e) => setNewJoiningDate(e.target.value)}
                />
              </div>

              <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.75rem" }}>
                <button
                  type="button"
                  className="emp-btn emp-btn--secondary"
                  onClick={() => setShowCreateModal(false)}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="emp-btn emp-btn--primary"
                  disabled={creating}
                >
                  {creating ? "Creating…" : "Establish Placement"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
