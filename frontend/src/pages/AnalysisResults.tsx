import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getLatestAnalysis, getGaps, type AnalysisResult, type SkillGap } from "../services/analysis";
import Button from "../components/ui/Button";
import "./AnalysisResults.css";

export default function AnalysisResults() {
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null);
  const [gaps, setGaps] = useState<SkillGap[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const load = async () => {
      try {
        const [a, g] = await Promise.all([getLatestAnalysis(), getGaps().catch(() => [] as SkillGap[])]);
        setAnalysis(a);
        setGaps(g);
      } catch (e) {
        const msg = e instanceof Error ? e.message : "Failed to load analysis";
        if (msg.includes("404") || msg.toLowerCase().includes("no analysis")) {
          setError("No analysis found. Run INAURA analysis first.");
        } else if (msg.includes("401")) {
          setError("Session expired. Please log in again.");
        } else if (msg.includes("503")) {
          setError("Analysis tables not configured — run backend/supabase/005_skill_engine.sql");
        } else {
          setError(msg);
        }
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  if (loading) {
    return (
      <div className="results">
        <div className="container" style={{ padding: "4rem 0", textAlign: "center", color: "#64748b" }}>
          Loading your INAURA analysis…
        </div>
      </div>
    );
  }

  if (error || !analysis) {
    return (
      <div className="results">
        <div className="container" style={{ padding: "2rem 0" }}>
          <div className="results__error">
            <h2>{error || "No analysis found"}</h2>
            <p>Complete your profile and evidence, then run analysis.</p>
            <div style={{ marginTop: 12, display: "flex", gap: 8, justifyContent: "center" }}>
              <Link to="/analysis">
                <Button variant="primary" size="md">
                  Go to Analysis
                </Button>
              </Link>
              <Link to="/dashboard">
                <Button variant="secondary" size="md">
                  Dashboard
                </Button>
              </Link>
            </div>
          </div>
        </div>
      </div>
    );
  }

  const readinessPct = Math.round(analysis.readiness_score * 100);
  const skillPct = Math.round(analysis.skill_component * 100);
  const industryPct = Math.round(analysis.industry_component * 100);
  const evidencePct = Math.round(analysis.evidence_component * 100);

  // For skills table, we need to fetch skills — but gaps already contain required/current
  // We'll use gaps for table, sorted by priority
  const sortedGaps = [...gaps].sort((a, b) => b.priority_score - a.priority_score);

  const getPriorityLabel = (score: number) => {
    if (score >= 50) return { label: "Critical", cls: "priority--critical" };
    if (score >= 25) return { label: "High", cls: "priority--high" };
    if (score >= 10) return { label: "Medium", cls: "priority--medium" };
    if (score > 0) return { label: "Low", cls: "priority--low" };
    return { label: "Covered", cls: "priority--covered" };
  };

  return (
    <div className="results">
      <header className="results__header">
        <div className="container">
          <Link to="/analysis" className="results__back">
            ← Back to Analysis
          </Link>
          <div className="eyebrow" style={{ marginTop: 12 }}>
            INAURA Skill Analysis — {analysis.engine_version}
          </div>
          <h1 className="results__title">Your INAURA Skill Analysis</h1>
          <div className="results__meta">
            <span>
              Target Role: <strong>{analysis.target_role}</strong>
            </span>
            <span>·</span>
            <span>{new Date(analysis.created_at).toLocaleDateString()}</span>
          </div>
        </div>
      </header>

      <main className="container results__main">
        {/* Top cards */}
        <section className="results__top">
          <div className="results__card results__card--primary">
            <div className="results__card-label">Career Readiness</div>
            <div className="results__big">{readinessPct}%</div>
            <div className="results__hint">Estimated — based on available evidence</div>
            <div className="results__components">
              <span>Skill {skillPct}%</span>
              <span>Industry {industryPct}%</span>
              <span>Evidence {evidencePct}%</span>
            </div>
            <div style={{ marginTop: 8, fontSize: "0.78rem", color: "#64748b" }}>
              0.45×skill + 0.25×industry + 0.30×evidence — heuristic prototype, not validated
            </div>
          </div>

          <div className="results__card">
            <div className="results__card-label">Evidence Confidence</div>
            <div className="results__big" style={{ color: "#0f766e" }}>
              {evidencePct}%
            </div>
            <div className="results__hint">Avg confidence across assessed skills</div>
            <div style={{ marginTop: 8, fontSize: "0.84rem", color: "#475569" }}>
              Skills assessed: <strong>{analysis.assessment_count}</strong> · Priority gaps: <strong>{analysis.gap_count}</strong>
            </div>
          </div>
        </section>

        <div className="results__note">
          <strong>Heuristic prototype:</strong> All scores are normalized [0,1] internally and shown as percentages. Weights are configurable and not scientifically validated. Based on available evidence.
        </div>

        {/* Skill overview */}
        <section className="results__section">
          <h2>Skill overview</h2>
          <p>Current vs required, gap, confidence and priority — sorted by priority.</p>

          <div className="results__table-wrap">
            <table className="results__table">
              <thead>
                <tr>
                  <th>Skill</th>
                  <th>Current</th>
                  <th>Required</th>
                  <th>Gap</th>
                  <th>Confidence</th>
                  <th>Priority</th>
                </tr>
              </thead>
              <tbody>
                {sortedGaps.map((g) => {
                  const currentPct = Math.round(g.current_proficiency * 100);
                  const requiredPct = Math.round(g.required_level * 100);
                  const gapPct = Math.round(g.gap * 100);
                  const confPct = Math.round(g.confidence * 100);
                  const prio = getPriorityLabel(g.priority_score);
                  const displayName = g.skills?.display_name || g.skills?.canonical_name || "Unknown";
                  return (
                    <tr key={g.id}>
                      <td>
                        <strong>{displayName}</strong>
                        <span className="results__cat">{g.skills?.category || ""}</span>
                      </td>
                      <td>{currentPct}%</td>
                      <td>{requiredPct}%</td>
                      <td>{gapPct}%</td>
                      <td>{confPct}%</td>
                      <td>
                        <span className={`priority ${prio.cls}`}>{prio.label}</span>
                      </td>
                    </tr>
                  );
                })}
                {sortedGaps.length === 0 && (
                  <tr>
                    <td colSpan={6} style={{ textAlign: "center", color: "#64748b", padding: 16 }}>
                      No gaps found — all required skills covered or no requirements for this role.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>

        {/* Gap visualization */}
        <section className="results__section">
          <h2>Gap visualization</h2>
          <div className="results__viz">
            {sortedGaps.slice(0, 5).map((g) => {
              const displayName = g.skills?.display_name || g.skills?.canonical_name || "Unknown";
              const currentPct = Math.round(g.current_proficiency * 100);
              const requiredPct = Math.round(g.required_level * 100);
              const gapPct = Math.round(g.gap * 100);
              return (
                <div key={g.id} className="results__viz-row">
                  <div className="results__viz-head">
                    <strong>{displayName}</strong>
                    <span>
                      {currentPct}% → {requiredPct}% (gap {gapPct}%)
                    </span>
                  </div>
                  <div className="results__bar">
                    <div className="results__bar-current" style={{ width: `${currentPct}%` }} />
                    <div className="results__bar-required" style={{ width: `${requiredPct}%` }} />
                  </div>
                  <div className="results__viz-labels">
                    <span>Current {currentPct}%</span>
                    <span>Required {requiredPct}%</span>
                  </div>
                </div>
              );
            })}
          </div>
        </section>

        {/* Evidence panel */}
        <section className="results__section">
          <h2>Evidence panel</h2>
          <p>For each skill, see supporting evidence. INAURA shows traceability — not just a number.</p>
          <div className="results__evidence">
            {sortedGaps.slice(0, 6).map((g) => {
              const displayName = g.skills?.display_name || g.skills?.canonical_name || "Unknown";
              return (
                <div key={g.id} className="results__evidence-card">
                  <h3>{displayName}</h3>
                  <div style={{ fontSize: "0.84rem", color: "#475569", marginTop: 4 }}>{g.explanation}</div>
                  <div style={{ marginTop: 8, fontSize: "0.82rem", color: "#64748b" }}>
                    Confidence: {Math.round(g.confidence * 100)}% · Gap: {Math.round(g.gap * 100)}% · Priority: {getPriorityLabel(g.priority_score).label}
                  </div>
                </div>
              );
            })}
          </div>
        </section>

        {/* Priority gaps */}
        <section className="results__section">
          <h2>Priority gaps</h2>
          <p>Highest priority first — gap × importance × demand × confidence × interview relevance.</p>
          <div className="results__gaps">
            {sortedGaps
              .filter((g) => g.gap > 0)
              .slice(0, 5)
              .map((g, idx) => {
                const displayName = g.skills?.display_name || g.skills?.canonical_name || "Unknown";
                const prio = getPriorityLabel(g.priority_score);
                return (
                  <div key={g.id} className="results__gap-card">
                    <div className="results__gap-num">{idx + 1}</div>
                    <div>
                      <strong>{displayName}</strong>
                      <div style={{ fontSize: "0.84rem", color: "#475569", marginTop: 4 }}>{g.explanation}</div>
                      <div style={{ marginTop: 6, fontSize: "0.82rem", color: "#64748b" }}>
                        Gap {Math.round(g.gap * 100)}% · Importance {g.importance.toFixed(2)} · Demand {g.demand.toFixed(2)} · Interview {g.interview_relevance.toFixed(2)} · Confidence {Math.round(g.confidence * 100)}%
                      </div>
                      <span className={`priority ${prio.cls}`} style={{ marginTop: 6, display: "inline-block" }}>
                        {prio.label} · {g.priority_score.toFixed(1)}
                      </span>
                    </div>
                  </div>
                );
              })}
            {sortedGaps.filter((g) => g.gap > 0).length === 0 && (
              <div style={{ color: "#64748b", fontSize: "0.9rem" }}>No priority gaps — all required skills are covered.</div>
            )}
          </div>
        </section>

        <section className="results__next">
          <h3>Next: Build Your Personalized Roadmap</h3>
          <p>Your analysis is saved and versioned ({analysis.engine_version}). Your roadmap is built from your highest-priority gaps — not a generic template.</p>
          <div style={{ marginTop: 12, display: "flex", gap: 8, justifyContent: "center" }}>
            <Button variant="secondary" size="md" onClick={() => (window.location.href = "/analysis")}>
              Back to Evidence
            </Button>
            <Button variant="primary" size="md" onClick={() => (window.location.href = "/roadmap")}>
              View Personalized Roadmap →
            </Button>
          </div>
        </section>
      </main>
    </div>
  );
}
