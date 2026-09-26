import { useState, useEffect, useCallback } from "react";
import { useEmployer } from "../../context/EmployerContext";
import { getDashboard, type Dashboard } from "../../services/outcomes";
import "../../components/employer/EmployerComponents.css";

const pct = (val: number | null | undefined) =>
  val == null ? "—" : `${Math.round(val * 100)}%`;

export default function EmployerAnalytics() {
  const { currentEmployer } = useEmployer();
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadDashboard = useCallback(async () => {
    if (!currentEmployer) return;
    setLoading(true);
    setError(null);
    try {
      const data = await getDashboard(currentEmployer.id);
      setDashboard(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [currentEmployer]);

  useEffect(() => {
    void loadDashboard();
  }, [loadDashboard]);

  if (!currentEmployer) {
    return (
      <div style={{ padding: "3rem", textAlign: "center", color: "var(--muted)" }}>
        Please select or register a company to view hiring analytics.
      </div>
    );
  }

  return (
    <div>
      <div className="emp-page-header">
        <div>
          <h1>Hiring Analytics &amp; Outcome Signals</h1>
          <p>
            Conversion rates, funnel health, and skill gaps for <strong>{currentEmployer.name}</strong>.
          </p>
        </div>
      </div>

      {error && (
        <div style={{ background: "#fef2f2", color: "#dc2626", padding: "0.6rem 0.85rem", borderRadius: "8px", marginBottom: "1rem", fontSize: "0.85rem" }}>
          {error}
        </div>
      )}

      {loading ? (
        <div style={{ padding: "3rem", textAlign: "center", color: "var(--muted)" }}>
          Loading funnel metrics…
        </div>
      ) : !dashboard ? (
        <div className="emp-card emp-empty-state">
          <h3>No analytics data available yet</h3>
          <p>Funnel conversion rates will calculate as applications advance through hiring stages.</p>
        </div>
      ) : (
        <>
          {/* Conversion Rates Grid */}
          <div className="emp-stats-grid">
            <div className="emp-stat-box">
              <span className="emp-stat-box__label">Interview Rate</span>
              <span className="emp-stat-box__val">{pct(dashboard.rates.interview_rate)}</span>
              <span className="emp-stat-box__sub">Applied to interview</span>
            </div>
            <div className="emp-stat-box">
              <span className="emp-stat-box__label">Offer Rate</span>
              <span className="emp-stat-box__val">{pct(dashboard.rates.offer_rate)}</span>
              <span className="emp-stat-box__sub">Interview to offer</span>
            </div>
            <div className="emp-stat-box">
              <span className="emp-stat-box__label">Selection Rate</span>
              <span className="emp-stat-box__val">{pct(dashboard.rates.selection_rate)}</span>
              <span className="emp-stat-box__sub">Selected / total applied</span>
            </div>
            <div className="emp-stat-box">
              <span className="emp-stat-box__label">Joining Rate</span>
              <span className="emp-stat-box__val">{pct(dashboard.rates.joining_rate_selection_base)}</span>
              <span className="emp-stat-box__sub">Selected to joined</span>
            </div>
          </div>

          {/* Funnel Stage Breakdown */}
          <div className="emp-card">
            <h2 className="emp-card__title" style={{ marginBottom: "1rem" }}>
              Funnel Stage Distribution
            </h2>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: "0.75rem" }}>
              {Object.entries(dashboard.funnel || {}).map(([stage, count]) => (
                <div
                  key={stage}
                  style={{
                    background: "var(--paper-2, #f8fafc)",
                    padding: "0.75rem 1rem",
                    borderRadius: "8px",
                    border: "1px solid var(--line)",
                    textAlign: "center",
                  }}
                >
                  <div style={{ fontSize: "0.75rem", textTransform: "uppercase", fontWeight: 600, color: "var(--muted)" }}>
                    {stage.replace("_", " ")}
                  </div>
                  <div style={{ fontSize: "1.5rem", fontWeight: 700, color: "var(--ink)", marginTop: "0.2rem" }}>
                    {count}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(360px, 1fr))", gap: "1.5rem" }}>
            {/* Top Required Skills */}
            <div className="emp-card">
              <h2 className="emp-card__title" style={{ marginBottom: "0.75rem" }}>
                Most Demanded Skills
              </h2>
              {dashboard.top_required_skills.length === 0 ? (
                <p style={{ color: "var(--muted)", fontSize: "0.85rem" }}>No skills recorded in active requirements.</p>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
                  {dashboard.top_required_skills.map((s) => (
                    <div
                      key={s.skill_id}
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        padding: "0.5rem 0.75rem",
                        background: "var(--paper-2, #f8fafc)",
                        borderRadius: "6px",
                        fontSize: "0.85rem",
                      }}
                    >
                      <span><strong>{s.skill_id}</strong></span>
                      <span style={{ color: "var(--muted)" }}>{s.count} requirement postings</span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Observed Skill Gaps */}
            <div className="emp-card">
              <h2 className="emp-card__title" style={{ marginBottom: "0.75rem" }}>
                Top Observed Skill Gaps (Candidate Feedback)
              </h2>
              {dashboard.top_observed_gaps.length === 0 ? (
                <p style={{ color: "var(--muted)", fontSize: "0.85rem" }}>
                  No skill gaps recorded from evaluations yet.
                </p>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
                  {dashboard.top_observed_gaps.map((g) => (
                    <div
                      key={g.skill_id}
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        padding: "0.5rem 0.75rem",
                        background: "var(--paper-2, #f8fafc)",
                        borderRadius: "6px",
                        fontSize: "0.85rem",
                      }}
                    >
                      <span><strong>{g.skill_id}</strong></span>
                      <span style={{ color: "#dc2626", fontWeight: 600 }}>
                        Avg Gap: {Math.round(g.avg_gap * 100)}pp ({g.feedback_count} reviews)
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
