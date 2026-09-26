import { useState, useEffect, useCallback, useMemo } from "react";
import { useEmployer } from "../../context/EmployerContext";
import {
  listApplicationsForEmployer,
  type Application,
} from "../../services/outcomes";
import { formatStatusLabel } from "../../lib/applicationsModel";
import CandidateDetailModal from "../../components/employer/CandidateDetailModal";
import "../../components/employer/EmployerComponents.css";

export default function EmployerCandidates() {
  const { currentEmployer, requirements } = useEmployer();

  const [applications, setApplications] = useState<Application[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Filters & search
  const [selectedReqId, setSelectedReqId] = useState<string>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");

  // Selected candidate detail modal
  const [selectedAppId, setSelectedAppId] = useState<string | null>(null);

  const loadCandidates = useCallback(async () => {
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
    void loadCandidates();
  }, [loadCandidates]);

  const filteredCandidates = useMemo(() => {
    return applications.filter((app) => {
      if (selectedReqId !== "all" && app.hiring_requirement_id !== selectedReqId) {
        return false;
      }
      if (statusFilter !== "all" && app.status !== statusFilter) {
        return false;
      }
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const name = (app.candidate_name || "").toLowerCase();
        const role = (app.requirement_title || "").toLowerCase();
        const sid = app.student_id.toLowerCase();
        return name.includes(q) || role.includes(q) || sid.includes(q);
      }
      return true;
    });
  }, [applications, selectedReqId, statusFilter, searchQuery]);

  if (!currentEmployer) {
    return (
      <div style={{ padding: "3rem", textAlign: "center", color: "var(--muted)" }}>
        Please select or create an employer company to view candidates.
      </div>
    );
  }

  return (
    <div>
      <div className="emp-page-header">
        <div>
          <h1>Candidate Talent Discovery</h1>
          <p>
            Evaluate applicants, review verified evidence, and track interview progress across <strong>{currentEmployer.name}</strong>.
          </p>
        </div>
        <div className="emp-header-actions">
          <span style={{ fontSize: "0.85rem", color: "var(--muted)", fontWeight: 600 }}>
            {filteredCandidates.length} Candidates Found
          </span>
        </div>
      </div>

      {error && (
        <div style={{ background: "#fef2f2", color: "#dc2626", padding: "0.6rem 0.85rem", borderRadius: "8px", marginBottom: "1rem", fontSize: "0.85rem" }}>
          {error}
        </div>
      )}

      {/* Filter and Search Bar */}
      <div className="emp-card" style={{ padding: "1rem", marginBottom: "1.25rem" }}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem", alignItems: "center" }}>
          <div style={{ flex: 1, minWidth: 240 }}>
            <input
              type="search"
              className="emp-input"
              style={{ width: "100%" }}
              placeholder="Search candidate by name, role or student ID…"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>

          <div style={{ width: 200 }}>
            <select
              className="emp-select"
              style={{ width: "100%" }}
              value={selectedReqId}
              onChange={(e) => setSelectedReqId(e.target.value)}
            >
              <option value="all">All Requirements</option>
              {requirements.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.title}
                </option>
              ))}
            </select>
          </div>

          <div style={{ width: 160 }}>
            <select
              className="emp-select"
              style={{ width: "100%" }}
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
            >
              <option value="all">All Statuses</option>
              <option value="applied">Applied</option>
              <option value="screening">Screening</option>
              <option value="interview">Interview</option>
              <option value="offer_received">Offer Extended</option>
              <option value="selected">Selected</option>
              <option value="rejected">Rejected</option>
              <option value="withdrawn">Withdrawn</option>
            </select>
          </div>
        </div>
      </div>

      {loading ? (
        <div style={{ padding: "3rem", textAlign: "center", color: "var(--muted)" }}>
          Loading candidate pool…
        </div>
      ) : filteredCandidates.length === 0 ? (
        <div className="emp-card emp-empty-state">
          <h3>No candidates match your criteria</h3>
          <p>
            {applications.length === 0
              ? "No candidates have applied to your active requirements yet."
              : "Try adjusting your search query or requirement filter."}
          </p>
        </div>
      ) : (
        <div className="emp-table-wrap">
          <table className="emp-table">
            <thead>
              <tr>
                <th>Candidate Name</th>
                <th>Applied Role</th>
                <th>Application Date</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredCandidates.map((cand) => (
                <tr key={cand.id}>
                  <td>
                    <div>
                      <strong>
                        {cand.candidate_name || `Candidate (${cand.student_id.slice(0, 8)})`}
                      </strong>
                    </div>
                    <div style={{ fontSize: "0.75rem", color: "var(--muted)", marginTop: "0.15rem" }}>
                      ID: <code>{cand.student_id.slice(0, 12)}…</code>
                    </div>
                  </td>
                  <td>
                    <div style={{ fontWeight: 600 }}>{cand.requirement_title || "Requirement"}</div>
                  </td>
                  <td style={{ fontSize: "0.85rem", color: "var(--muted)" }}>
                    {cand.applied_at ? new Date(cand.applied_at).toLocaleDateString() : "Pending"}
                  </td>
                  <td>
                    <span className={`emp-badge emp-badge--${cand.status}`}>
                      {formatStatusLabel(cand.status)}
                    </span>
                  </td>
                  <td>
                    <button
                      type="button"
                      className="emp-btn emp-btn--primary emp-btn--sm"
                      onClick={() => setSelectedAppId(cand.id)}
                    >
                      Review Evidence &amp; Evaluate →
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Candidate Detail / Evaluation Modal */}
      {selectedAppId && (
        <CandidateDetailModal
          applicationId={selectedAppId}
          employerId={currentEmployer.id}
          onClose={() => setSelectedAppId(null)}
          onApplicationUpdated={() => {
            void loadCandidates();
          }}
        />
      )}
    </div>
  );
}
