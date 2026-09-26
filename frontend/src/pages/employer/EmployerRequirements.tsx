import { useState } from "react";
import { Link } from "react-router-dom";
import { useEmployer } from "../../context/EmployerContext";
import {
  updateRequirement,
  deleteRequirement,
  type Requirement,
} from "../../services/employers";
import { formatStatusLabel } from "../../lib/applicationsModel";
import RequirementModal from "../../components/employer/RequirementModal";
import RequirementSkillsModal from "../../components/employer/RequirementSkillsModal";
import "../../components/employer/EmployerComponents.css";

type StatusFilter = "all" | "open" | "paused" | "closed" | "draft";

export default function EmployerRequirements() {
  const { currentEmployer, requirements, refreshRequirements } = useEmployer();

  const [filter, setFilter] = useState<StatusFilter>("all");
  const [editingReq, setEditingReq] = useState<Requirement | null>(null);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [managingSkillsReq, setManagingSkillsReq] = useState<Requirement | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const filtered = requirements.filter((r) => {
    if (filter === "all") return true;
    return r.status === filter;
  });

  const handleUpdateStatus = async (
    reqId: string,
    status: "draft" | "open" | "paused" | "closed"
  ) => {
    setActionError(null);
    try {
      await updateRequirement(reqId, { status });
      await refreshRequirements();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleDelete = async (reqId: string, title: string) => {
    if (!window.confirm(`Are you sure you want to delete the requirement "${title}"?`)) {
      return;
    }
    setActionError(null);
    try {
      await deleteRequirement(reqId);
      await refreshRequirements();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e));
    }
  };

  if (!currentEmployer) {
    return (
      <div style={{ padding: "3rem", textAlign: "center", color: "var(--muted)" }}>
        Please select or register a company first to manage hiring requirements.
      </div>
    );
  }

  return (
    <div>
      <div className="emp-page-header">
        <div>
          <h1>Hiring Requirements</h1>
          <p>
            Define open roles, target qualifications, and required skill benchmarks for <strong>{currentEmployer.name}</strong>.
          </p>
        </div>
        <div className="emp-header-actions">
          <button
            type="button"
            className="emp-btn emp-btn--primary"
            onClick={() => setShowCreateModal(true)}
          >
            + Post New Requirement
          </button>
        </div>
      </div>

      {actionError && (
        <div style={{ background: "#fef2f2", color: "#dc2626", padding: "0.6rem 0.85rem", borderRadius: "8px", marginBottom: "1rem", fontSize: "0.85rem" }}>
          {actionError}
        </div>
      )}

      {/* Status Filter Tabs */}
      <div className="emp-tabs">
        <button
          type="button"
          className={`emp-tab-btn${filter === "all" ? " is-active" : ""}`}
          onClick={() => setFilter("all")}
        >
          All Requirements ({requirements.length})
        </button>
        <button
          type="button"
          className={`emp-tab-btn${filter === "open" ? " is-active" : ""}`}
          onClick={() => setFilter("open")}
        >
          Open ({requirements.filter((r) => r.status === "open").length})
        </button>
        <button
          type="button"
          className={`emp-tab-btn${filter === "paused" ? " is-active" : ""}`}
          onClick={() => setFilter("paused")}
        >
          Paused ({requirements.filter((r) => r.status === "paused").length})
        </button>
        <button
          type="button"
          className={`emp-tab-btn${filter === "closed" ? " is-active" : ""}`}
          onClick={() => setFilter("closed")}
        >
          Closed ({requirements.filter((r) => r.status === "closed").length})
        </button>
        <button
          type="button"
          className={`emp-tab-btn${filter === "draft" ? " is-active" : ""}`}
          onClick={() => setFilter("draft")}
        >
          Drafts ({requirements.filter((r) => r.status === "draft").length})
        </button>
      </div>

      {filtered.length === 0 ? (
        <div className="emp-card emp-empty-state">
          <h3>No requirements found</h3>
          <p>
            {filter === "all"
              ? "You haven't posted any hiring requirements yet. Create your first role to start accepting candidates."
              : `No requirements in ${filter} status.`}
          </p>
          <button
            type="button"
            className="emp-btn emp-btn--primary"
            onClick={() => setShowCreateModal(true)}
          >
            + Post Requirement
          </button>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
          {filtered.map((req) => (
            <div key={req.id} className="emp-card" style={{ marginBottom: 0 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "0.75rem", marginBottom: "0.75rem" }}>
                <div>
                  <div style={{ display: "flex", alignItems: "center", gap: "0.6rem" }}>
                    <h2 style={{ fontSize: "1.2rem", fontWeight: 700, margin: 0 }}>{req.title}</h2>
                    <span className={`emp-badge emp-badge--${req.status}`}>
                      {formatStatusLabel(req.status)}
                    </span>
                  </div>
                  <div style={{ fontSize: "0.85rem", color: "var(--muted)", marginTop: "0.35rem" }}>
                    {req.location || "Remote / Anywhere"} • {req.employment_type?.replace("_", " ") || "Full-time"} • Min Experience: {req.experience_min_years != null ? `${req.experience_min_years} yrs` : "Not specified"}
                  </div>
                </div>

                <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", flexWrap: "wrap" }}>
                  <button
                    type="button"
                    className="emp-btn emp-btn--secondary emp-btn--sm"
                    onClick={() => setManagingSkillsReq(req)}
                  >
                    Skills Benchmark
                  </button>
                  <button
                    type="button"
                    className="emp-btn emp-btn--secondary emp-btn--sm"
                    onClick={() => setEditingReq(req)}
                  >
                    Edit
                  </button>
                  <Link
                    to={`/employer/applications?requirementId=${req.id}`}
                    className="emp-btn emp-btn--primary emp-btn--sm"
                  >
                    View Candidates →
                  </Link>
                </div>
              </div>

              {req.qualification_text && (
                <div style={{ fontSize: "0.85rem", color: "var(--ink-700)", marginBottom: "0.5rem" }}>
                  <strong>Qualification:</strong> {req.qualification_text}
                </div>
              )}

              {req.description && (
                <p style={{ fontSize: "0.875rem", color: "var(--muted)", margin: "0.5rem 0", lineHeight: 1.5 }}>
                  {req.description}
                </p>
              )}

              {/* Requirement footer actions (Status transitions & delete) */}
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderTop: "1px solid var(--line)", paddingTop: "0.75rem", marginTop: "0.75rem", flexWrap: "wrap", gap: "0.5rem" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                  <span style={{ fontSize: "0.75rem", color: "var(--muted)", fontWeight: 600 }}>Quick Status:</span>
                  {req.status !== "open" && (
                    <button
                      type="button"
                      className="emp-btn emp-btn--secondary emp-btn--sm"
                      onClick={() => handleUpdateStatus(req.id, "open")}
                    >
                      Open
                    </button>
                  )}
                  {req.status === "open" && (
                    <button
                      type="button"
                      className="emp-btn emp-btn--secondary emp-btn--sm"
                      onClick={() => handleUpdateStatus(req.id, "paused")}
                    >
                      Pause
                    </button>
                  )}
                  {req.status !== "closed" && (
                    <button
                      type="button"
                      className="emp-btn emp-btn--secondary emp-btn--sm"
                      onClick={() => handleUpdateStatus(req.id, "closed")}
                    >
                      Close
                    </button>
                  )}
                </div>

                <button
                  type="button"
                  className="emp-btn emp-btn--danger-ghost emp-btn--sm"
                  onClick={() => handleDelete(req.id, req.title)}
                >
                  Delete Requirement
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Create / Edit Modal */}
      {(showCreateModal || editingReq) && (
        <RequirementModal
          employerId={currentEmployer.id}
          requirement={editingReq}
          onClose={() => {
            setShowCreateModal(false);
            setEditingReq(null);
          }}
          onSaved={() => {
            void refreshRequirements();
          }}
        />
      )}

      {/* Skills Management Modal */}
      {managingSkillsReq && (
        <RequirementSkillsModal
          requirement={managingSkillsReq}
          onClose={() => setManagingSkillsReq(null)}
          onSaved={() => {
            void refreshRequirements();
          }}
        />
      )}
    </div>
  );
}
