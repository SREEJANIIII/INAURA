import { useState, useEffect, useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { useEmployer } from "../../context/EmployerContext";
import {
  listApplicationsForEmployer,
  type Application,
} from "../../services/outcomes";
import { formatStatusLabel } from "../../lib/applicationsModel";
import CandidateDetailModal from "../../components/employer/CandidateDetailModal";
import "../../components/employer/EmployerComponents.css";

type TabFilter = "all" | "applied" | "screening" | "interview" | "selected" | "rejected" | "withdrawn";

export default function EmployerApplications() {
  const { currentEmployer, requirements } = useEmployer();
  const [searchParams, setSearchParams] = useSearchParams();

  const reqParam = searchParams.get("requirementId");
  const [selectedReqId, setSelectedReqId] = useState<string>(reqParam || "all");
  const [tab, setTab] = useState<TabFilter>("all");
  const [applications, setApplications] = useState<Application[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Selected candidate detail modal
  const [selectedAppId, setSelectedAppId] = useState<string | null>(null);

  // Sync state if url changes
  useEffect(() => {
    if (reqParam) {
      setSelectedReqId(reqParam);
    }
  }, [reqParam]);

  const loadApplications = useCallback(async () => {
    if (!currentEmployer) return;
    setLoading(true);
    setError(null);
    try {
      const rows = await listApplicationsForEmployer(currentEmployer.id);
      setApplications(rows);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [currentEmployer]);

  useEffect(() => {
    void loadApplications();
  }, [loadApplications]);

  const handleReqChange = (reqId: string) => {
    setSelectedReqId(reqId);
    if (reqId === "all") {
      searchParams.delete("requirementId");
      setSearchParams(searchParams);
    } else {
      setSearchParams({ requirementId: reqId });
    }
  };

  const filtered = useMemo(() => {
    return applications.filter((app) => {
      if (selectedReqId !== "all" && app.hiring_requirement_id !== selectedReqId) {
        return false;
      }
      if (tab !== "all" && app.status !== tab) {
        return false;
      }
      return true;
    });
  }, [applications, selectedReqId, tab]);

  if (!currentEmployer) {
    return (
      <div style={{ padding: "3rem", textAlign: "center", color: "var(--muted)" }}>
        Please select or register a company first to manage applications.
      </div>
    );
  }

  return (
    <div>
      <div className="emp-page-header">
        <div>
          <h1>Application Management</h1>
          <p>
            Track candidate lifecycle, advance screening stages, and record recruitment decisions for <strong>{currentEmployer.name}</strong>.
          </p>
        </div>
        <div className="emp-header-actions">
          <select
            className="emp-select"
            value={selectedReqId}
            onChange={(e) => handleReqChange(e.target.value)}
          >
            <option value="all">All Requirements</option>
            {requirements.map((r) => (
              <option key={r.id} value={r.id}>
                {r.title}
              </option>
            ))}
          </select>
        </div>
      </div>

      {error && (
        <div style={{ background: "#fef2f2", color: "#dc2626", padding: "0.6rem 0.85rem", borderRadius: "8px", marginBottom: "1rem", fontSize: "0.85rem" }}>
          {error}
        </div>
      )}

      {/* Status Filter Tabs */}
      <div className="emp-tabs">
        <button
          type="button"
          className={`emp-tab-btn${tab === "all" ? " is-active" : ""}`}
          onClick={() => setTab("all")}
        >
          All Applications ({applications.length})
        </button>
        <button
          type="button"
          className={`emp-tab-btn${tab === "applied" ? " is-active" : ""}`}
          onClick={() => setTab("applied")}
        >
          Applied ({applications.filter((a) => a.status === "applied").length})
        </button>
        <button
          type="button"
          className={`emp-tab-btn${tab === "screening" ? " is-active" : ""}`}
          onClick={() => setTab("screening")}
        >
          Screening ({applications.filter((a) => a.status === "screening").length})
        </button>
        <button
          type="button"
          className={`emp-tab-btn${tab === "interview" ? " is-active" : ""}`}
          onClick={() => setTab("interview")}
        >
          Interview ({applications.filter((a) => a.status === "interview").length})
        </button>
        <button
          type="button"
          className={`emp-tab-btn${tab === "selected" ? " is-active" : ""}`}
          onClick={() => setTab("selected")}
        >
          Selected / Hired ({applications.filter((a) => a.status === "selected").length})
        </button>
        <button
          type="button"
          className={`emp-tab-btn${tab === "rejected" ? " is-active" : ""}`}
          onClick={() => setTab("rejected")}
        >
          Rejected ({applications.filter((a) => a.status === "rejected").length})
        </button>
        <button
          type="button"
          className={`emp-tab-btn${tab === "withdrawn" ? " is-active" : ""}`}
          onClick={() => setTab("withdrawn")}
        >
          Withdrawn ({applications.filter((a) => a.status === "withdrawn").length})
        </button>
      </div>

      {loading ? (
        <div style={{ padding: "3rem", textAlign: "center", color: "var(--muted)" }}>
          Loading applications…
        </div>
      ) : filtered.length === 0 ? (
        <div className="emp-card emp-empty-state">
          <h3>No applications in this category</h3>
          <p>
            {applications.length === 0
              ? "Candidates haven't applied to your job postings yet."
              : `No applications match the current filter (${formatStatusLabel(tab)}).`}
          </p>
        </div>
      ) : (
        <div className="emp-table-wrap">
          <table className="emp-table">
            <thead>
              <tr>
                <th>Candidate Name</th>
                <th>Target Requirement</th>
                <th>Applied Date</th>
                <th>Current Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((app) => (
                <tr key={app.id}>
                  <td>
                    <div>
                      <strong>
                        {app.candidate_name || `Candidate (${app.student_id.slice(0, 8)})`}
                      </strong>
                    </div>
                    <div style={{ fontSize: "0.75rem", color: "var(--muted)", marginTop: "0.15rem" }}>
                      ID: <code>{app.student_id.slice(0, 10)}…</code>
                    </div>
                  </td>
                  <td>
                    <div style={{ fontWeight: 600 }}>{app.requirement_title || "Requirement"}</div>
                  </td>
                  <td style={{ fontSize: "0.85rem", color: "var(--muted)" }}>
                    {app.applied_at ? new Date(app.applied_at).toLocaleDateString() : "Pending"}
                  </td>
                  <td>
                    <span className={`emp-badge emp-badge--${app.status}`}>
                      {formatStatusLabel(app.status)}
                    </span>
                  </td>
                  <td>
                    <button
                      type="button"
                      className="emp-btn emp-btn--secondary emp-btn--sm"
                      onClick={() => setSelectedAppId(app.id)}
                    >
                      Manage &amp; Evaluate →
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Candidate Detail Modal */}
      {selectedAppId && (
        <CandidateDetailModal
          applicationId={selectedAppId}
          employerId={currentEmployer.id}
          onClose={() => setSelectedAppId(null)}
          onApplicationUpdated={() => {
            void loadApplications();
          }}
        />
      )}
    </div>
  );
}
