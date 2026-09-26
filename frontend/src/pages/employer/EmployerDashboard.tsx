import { useState, useEffect, useCallback } from "react";
import { Link } from "react-router-dom";
import { useEmployer } from "../../context/EmployerContext";
import {
  listApplicationsForEmployer,
  listPlacementsForEmployer,
  getDashboard,
  type Application,
  type Placement,
  type Dashboard,
} from "../../services/outcomes";
import { formatStatusLabel } from "../../lib/applicationsModel";
import CandidateDetailModal from "../../components/employer/CandidateDetailModal";
import RequirementModal from "../../components/employer/RequirementModal";
import CompanyModal from "../../components/employer/CompanyModal";
import "../../components/employer/EmployerComponents.css";

export default function EmployerDashboard() {
  const { currentEmployer, requirements, loading: empLoading, refreshRequirements } = useEmployer();

  const [applications, setApplications] = useState<Application[]>([]);
  const [placements, setPlacements] = useState<Placement[]>([]);
  const [dashboardData, setDashboardData] = useState<Dashboard | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Modals
  const [selectedAppId, setSelectedAppId] = useState<string | null>(null);
  const [showReqModal, setShowReqModal] = useState(false);
  const [showCompanyModal, setShowCompanyModal] = useState(false);

  const loadData = useCallback(async () => {
    if (!currentEmployer) return;
    setLoading(true);
    setError(null);
    try {
      const [apps, pls, dash] = await Promise.all([
        listApplicationsForEmployer(currentEmployer.id),
        listPlacementsForEmployer(currentEmployer.id),
        getDashboard(currentEmployer.id).catch(() => null),
      ]);
      setApplications(apps);
      setPlacements(pls);
      setDashboardData(dash);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [currentEmployer]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  if (empLoading) {
    return (
      <div style={{ padding: "3rem", textAlign: "center", color: "var(--muted)" }}>
        Loading employer workspace…
      </div>
    );
  }

  // If user has no company yet
  if (!currentEmployer) {
    return (
      <div>
        <div className="emp-page-header">
          <div>
            <h1>Welcome to INAURA Employer Portal</h1>
            <p>
              Connect with verified talent, assess demonstrated skills, and streamline your recruitment pipeline.
            </p>
          </div>
        </div>

        <div className="emp-card" style={{ maxWidth: 600, margin: "2rem auto", textAlign: "center", padding: "2.5rem 2rem" }}>
          <div style={{ fontSize: "2.5rem", marginBottom: "0.5rem" }}>🏢</div>
          <h2 style={{ fontSize: "1.35rem", fontWeight: 700, margin: "0 0 0.5rem" }}>
            Register Your Organization
          </h2>
          <p style={{ color: "var(--muted)", fontSize: "0.9rem", marginBottom: "1.5rem" }}>
            Set up your company profile to start posting hiring requirements, reviewing verified candidate evidence, and evaluating applicants.
          </p>
          <button
            type="button"
            className="emp-btn emp-btn--primary"
            onClick={() => setShowCompanyModal(true)}
          >
            + Register Company Profile
          </button>
        </div>

        {showCompanyModal && (
          <CompanyModal
            onClose={() => setShowCompanyModal(false)}
            onSaved={() => {
              setShowCompanyModal(false);
            }}
          />
        )}
      </div>
    );
  }

  const activeReqs = requirements.filter((r) => r.status === "open");
  const inReviewApps = applications.filter((a) => a.status === "screening" || a.status === "interview");
  const interviewApps = applications.filter((a) => a.status === "interview");
  const selectedApps = applications.filter((a) => a.status === "selected");
  const joinedPlacements = placements.filter((p) => p.status === "joined");

  // Funnel counts
  const appliedCount = applications.filter((a) => a.status === "applied").length;
  const screeningCount = applications.filter((a) => a.status === "screening").length;
  const interviewCount = interviewApps.length;
  const selectedCount = selectedApps.length;
  const joinedCount = joinedPlacements.length;

  return (
    <div>
      {/* Top Banner / Actions */}
      <div className="emp-page-header">
        <div>
          <h1>Employer Dashboard</h1>
          <p>
            Overview for <strong>{currentEmployer.name}</strong> • Hiring pipeline, candidate evaluations, and active requirements.
          </p>
        </div>
        <div className="emp-header-actions">
          <button
            type="button"
            className="emp-btn emp-btn--primary"
            onClick={() => setShowReqModal(true)}
          >
            + Post Requirement
          </button>
          <Link to="/employer/applications" className="emp-btn emp-btn--secondary">
            Manage Applications
          </Link>
        </div>
      </div>

      {error && (
        <div style={{ background: "#fef2f2", color: "#dc2626", padding: "0.75rem 1rem", borderRadius: "8px", marginBottom: "1.5rem" }}>
          {error}
        </div>
      )}

      {/* 1. Overview Cards (Section 8) */}
      <div className="emp-stats-grid">
        <div className="emp-stat-box">
          <span className="emp-stat-box__label">Active Requirements</span>
          <span className="emp-stat-box__val">{activeReqs.length}</span>
          <span className="emp-stat-box__sub">{requirements.length} total requirements</span>
        </div>

        <div className="emp-stat-box">
          <span className="emp-stat-box__label">Total Applications</span>
          <span className="emp-stat-box__val">{applications.length}</span>
          <span className="emp-stat-box__sub">Across all roles</span>
        </div>

        <div className="emp-stat-box">
          <span className="emp-stat-box__label">Candidates In Review</span>
          <span className="emp-stat-box__val">{inReviewApps.length}</span>
          <span className="emp-stat-box__sub">Screening &amp; interviews</span>
        </div>

        <div className="emp-stat-box">
          <span className="emp-stat-box__label">Active Interviews</span>
          <span className="emp-stat-box__val">{interviewApps.length}</span>
          <span className="emp-stat-box__sub">In interview stage</span>
        </div>

        <div className="emp-stat-box">
          <span className="emp-stat-box__label">Placements</span>
          <span className="emp-stat-box__val">{placements.length}</span>
          <span className="emp-stat-box__sub">{joinedPlacements.length} confirmed joined</span>
        </div>
      </div>

      {/* 2. Hiring Pipeline Funnel (Section 8) */}
      <div className="emp-card">
        <div className="emp-card__header">
          <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
            <h2 className="emp-card__title">Candidate Pipeline</h2>
            {loading && <span style={{ fontSize: "0.75rem", color: "var(--muted)" }}>Refreshing…</span>}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
            {dashboardData?.rates && (
              <span style={{ fontSize: "0.8rem", color: "var(--muted)" }}>
                Interview Rate: {Math.round(dashboardData.rates.interview_rate * 100)}%
              </span>
            )}
            <Link to="/employer/analytics" style={{ fontSize: "0.85rem", color: "#0d9488", textDecoration: "none" }}>
              View Full Funnel Analytics →
            </Link>
          </div>
        </div>
        <div className="emp-pipeline">
          <div className="emp-pipeline__step">
            <span className="emp-pipeline__step-title">1. Applied</span>
            <span className="emp-pipeline__step-count">{appliedCount}</span>
          </div>
          <div style={{ color: "var(--muted-3)" }}>→</div>
          <div className="emp-pipeline__step">
            <span className="emp-pipeline__step-title">2. Screening</span>
            <span className="emp-pipeline__step-count">{screeningCount}</span>
          </div>
          <div style={{ color: "var(--muted-3)" }}>→</div>
          <div className="emp-pipeline__step is-active">
            <span className="emp-pipeline__step-title">3. Interview</span>
            <span className="emp-pipeline__step-count">{interviewCount}</span>
          </div>
          <div style={{ color: "var(--muted-3)" }}>→</div>
          <div className="emp-pipeline__step">
            <span className="emp-pipeline__step-title">4. Selected</span>
            <span className="emp-pipeline__step-count">{selectedCount}</span>
          </div>
          <div style={{ color: "var(--muted-3)" }}>→</div>
          <div className="emp-pipeline__step">
            <span className="emp-pipeline__step-title">5. Joined</span>
            <span className="emp-pipeline__step-count">{joinedCount}</span>
          </div>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(440px, 1fr))", gap: "1.5rem" }}>
        {/* 3. Recent Applications Table */}
        <div className="emp-card" style={{ marginBottom: 0 }}>
          <div className="emp-card__header">
            <h2 className="emp-card__title">Recent Applications</h2>
            <Link to="/employer/applications" style={{ fontSize: "0.85rem", color: "#0d9488", textDecoration: "none" }}>
              See all ({applications.length}) →
            </Link>
          </div>
          {applications.length === 0 ? (
            <p style={{ color: "var(--muted)", fontSize: "0.875rem", margin: "1rem 0" }}>
              No applications submitted yet. Once candidates apply to your hiring requirements, they will appear here.
            </p>
          ) : (
            <div className="emp-table-wrap">
              <table className="emp-table">
                <thead>
                  <tr>
                    <th>Candidate</th>
                    <th>Role</th>
                    <th>Status</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {applications.slice(0, 5).map((app) => (
                    <tr key={app.id}>
                      <td>
                        <strong>{app.candidate_name || `Candidate (${app.student_id.slice(0, 8)})`}</strong>
                        <div style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
                          {app.applied_at ? new Date(app.applied_at).toLocaleDateString() : "Pending"}
                        </div>
                      </td>
                      <td style={{ fontSize: "0.85rem" }}>
                        {app.requirement_title || "Requirement"}
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
                          Review
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* 4. Active Requirements List */}
        <div className="emp-card" style={{ marginBottom: 0 }}>
          <div className="emp-card__header">
            <h2 className="emp-card__title">Active Hiring Requirements</h2>
            <Link to="/employer/requirements" style={{ fontSize: "0.85rem", color: "#0d9488", textDecoration: "none" }}>
              Manage all ({requirements.length}) →
            </Link>
          </div>
          {activeReqs.length === 0 ? (
            <div style={{ textAlign: "center", padding: "1.5rem", color: "var(--muted)" }}>
              <p style={{ fontSize: "0.875rem", marginBottom: "0.75rem" }}>No open requirements right now.</p>
              <button
                type="button"
                className="emp-btn emp-btn--secondary emp-btn--sm"
                onClick={() => setShowReqModal(true)}
              >
                + Post New Requirement
              </button>
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
              {activeReqs.slice(0, 4).map((req) => {
                const reqAppCount = applications.filter((a) => a.hiring_requirement_id === req.id).length;
                return (
                  <div
                    key={req.id}
                    style={{
                      background: "var(--paper-2, #f8fafc)",
                      padding: "0.75rem 1rem",
                      borderRadius: "8px",
                      border: "1px solid var(--line)",
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                    }}
                  >
                    <div>
                      <div style={{ fontWeight: 700, fontSize: "0.925rem" }}>{req.title}</div>
                      <div style={{ fontSize: "0.8rem", color: "var(--muted)", marginTop: "0.2rem" }}>
                        {req.location || "Remote / Any"} • {req.employment_type?.replace("_", " ") || "Full-time"} • {reqAppCount} applicants
                      </div>
                    </div>
                    <span className="emp-badge emp-badge--open">Active</span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* 5. Recent Placements List */}
      <div className="emp-card" style={{ marginTop: "1.5rem" }}>
        <div className="emp-card__header">
          <h2 className="emp-card__title">Recent Placements &amp; Verified Hires</h2>
          <Link to="/employer/placements" style={{ fontSize: "0.85rem", color: "#0d9488", textDecoration: "none" }}>
            View Placements Table →
          </Link>
        </div>
        {placements.length === 0 ? (
          <p style={{ color: "var(--muted)", fontSize: "0.875rem", margin: "0.5rem 0" }}>
            No placement records yet. When candidates are marked selected and confirmed, their outcome records appear here.
          </p>
        ) : (
          <div className="emp-table-wrap">
            <table className="emp-table">
              <thead>
                <tr>
                  <th>Role Title</th>
                  <th>Joining Date</th>
                  <th>Placement Status</th>
                  <th>Verification</th>
                </tr>
              </thead>
              <tbody>
                {placements.slice(0, 4).map((pl) => (
                  <tr key={pl.id}>
                    <td>
                      <strong>{pl.role_title}</strong>
                      <div style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
                        Student ID: <code>{pl.student_id.slice(0, 8)}…</code>
                      </div>
                    </td>
                    <td>{pl.joining_date ? new Date(pl.joining_date).toLocaleDateString() : "Pending"}</td>
                    <td>
                      <span className={`emp-badge emp-badge--${pl.status}`}>
                        {formatStatusLabel(pl.status)}
                      </span>
                    </td>
                    <td>
                      <span className={`emp-badge emp-badge--${pl.verification_status === "verified" ? "open" : "suspended"}`}>
                        {pl.verification_status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Candidate Detail Modal */}
      {selectedAppId && (
        <CandidateDetailModal
          applicationId={selectedAppId}
          employerId={currentEmployer.id}
          onClose={() => setSelectedAppId(null)}
          onApplicationUpdated={() => {
            void loadData();
          }}
        />
      )}

      {/* Requirement Creation Modal */}
      {showReqModal && (
        <RequirementModal
          employerId={currentEmployer.id}
          onClose={() => setShowReqModal(false)}
          onSaved={() => {
            void refreshRequirements();
            void loadData();
          }}
        />
      )}
    </div>
  );
}
