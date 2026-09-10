import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getLatestAnalysis, getGaps, type AnalysisResult, type SkillGap } from "../services/analysis";
import { listEvidence, type Evidence } from "../services/evidence";
import Button from "../components/ui/Button";
import "./AnalysisResults.css";

export default function AnalysisResults() {
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null);
  const [gaps, setGaps] = useState<SkillGap[]>([]);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const load = async () => {
      try {
        const [a, g, ev] = await Promise.all([
          getLatestAnalysis(),
          getGaps().catch(() => [] as SkillGap[]),
          listEvidence().catch(() => [] as Evidence[]),
        ]);
        setAnalysis(a);
        setGaps(g);
        setEvidence(ev);
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

  const getPriorityLabel = (score: number, category?: string) => {
    if (category) {
      if (category === "critical") return { label: "Critical", cls: "priority--critical" };
      if (category === "high") return { label: "High", cls: "priority--high" };
      if (category === "medium") return { label: "Medium", cls: "priority--medium" };
      if (category === "low") return { label: "Low", cls: "priority--low" };
      if (category === "covered") return { label: "Covered", cls: "priority--covered" };
    }
    if (score >= 40) return { label: "Critical", cls: "priority--critical" };
    if (score >= 25) return { label: "High", cls: "priority--high" };
    if (score >= 10) return { label: "Medium", cls: "priority--medium" };
    if (score > 0) return { label: "Low", cls: "priority--low" };
    return { label: "Covered", cls: "priority--covered" };
  };

  const getGapTypeBadge = (type?: string) => {
    if (type === "evidence_gap") return { label: "Evidence Gap", cls: "gap-type--evidence" };
    if (type === "coverage_gap") return { label: "Coverage Gap", cls: "gap-type--coverage" };
    if (type === "industry_data_gap") return { label: "Industry Data Gap", cls: "gap-type--industry" };
    return { label: "Skill Gap", cls: "gap-type--skill" };
  };

  // Grouped items
  const strengths = sortedGaps.filter(
    (g) =>
      (g.gap <= 1e-9 || g.current_proficiency >= g.required_level) &&
      g.confidence >= 0.35 &&
      g.current_proficiency >= 0.50 &&
      g.gap_type !== "evidence_gap"
  );

  const priorityGaps = sortedGaps.filter((g) => g.gap > 0);

  const evidenceGaps = sortedGaps.filter(
    (g) => g.gap_type === "evidence_gap" || (g.gap > 0 && g.confidence < 0.20)
  );

  const strongValidated = sortedGaps.filter(
    (g) => g.quadrant === "strong_validated" || (g.current_proficiency >= 0.60 && g.confidence >= 0.50)
  );
  const unverifiedClaims = sortedGaps.filter(
    (g) => g.quadrant === "unverified_claim" || (g.current_proficiency >= 0.60 && g.confidence < 0.50)
  );
  const confirmedNeeds = sortedGaps.filter(
    (g) => g.quadrant === "confirmed_gap" || (g.current_proficiency < 0.60 && g.confidence >= 0.50 && g.gap > 0)
  );
  const exploratory = sortedGaps.filter(
    (g) => g.quadrant === "exploratory" || (g.current_proficiency < 0.60 && g.confidence < 0.50)
  );

  // Extract verified LeetCode topic coverage evidence if present
  const leetcodeEv = evidence.find(
    (e) =>
      e.evidence_type === "leetcode" &&
      (e.verification_status === "verified" ||
        (e.metadata as Record<string, unknown> | null)?.verification_status === "verified")
  );

  const lcMeta = leetcodeEv?.metadata as Record<string, any> | null;
  const lcInspection = lcMeta?.inspection;
  const lcTopicMeta =
    lcInspection?.topic_coverage ||
    (lcMeta?.verified_signals as any[])?.find((s: any) => s.skill?.includes("Data Structures"))?.metadata ||
    lcMeta?.topic_coverage;

  const lcUsername = lcInspection?.username || "LeetCode Candidate";
  const lcTotal = lcInspection?.total_solved ?? (lcTopicMeta?.total_solved ?? 0);
  const lcEasy = lcInspection?.easy_solved ?? (lcTopicMeta?.easy ?? 0);
  const lcMed = lcInspection?.medium_solved ?? (lcTopicMeta?.medium ?? 0);
  const lcHard = lcInspection?.hard_solved ?? (lcTopicMeta?.hard ?? 0);

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
            <span>·</span>
            <span>Benchmark: <strong>Industry Intelligence 2026.1</strong> (ACM/IEEE, Stack Overflow, BLS)</span>
          </div>
        </div>
      </header>

      <main className="container results__main">
        {/* Readiness != Guarantee Disclaimer */}
        <div className="results__disclaimer-box">
          <div className="results__disclaimer-icon">ℹ️</div>
          <div>
            <strong>Career Readiness Benchmark:</strong> {analysis.disclaimer || "Career readiness measures alignment between your verified evidence and authentic industry benchmarks (ACM/IEEE, Stack Overflow 2024, BLS). It is an objective developmental indicator, not a statistical hiring probability or guarantee of placement."}
          </div>
        </div>

        {/* Top cards */}
        <section className="results__top">
          <div className="results__card results__card--primary">
            <div className="results__card-label">Career Readiness</div>
            <div className="results__big">{readinessPct}%</div>
            <div className="results__hint">Alignment with {analysis.target_role} Benchmark</div>
            <div className="results__components">
              <span>Skill {skillPct}%</span>
              <span>Industry {industryPct}%</span>
              <span>Evidence {evidencePct}%</span>
            </div>
            <div style={{ marginTop: 8, fontSize: "0.78rem", color: "#64748b" }}>
              0.45×skill + 0.25×industry + 0.30×evidence — calibrated against verified industry benchmarks
            </div>
          </div>

          <div className="results__card">
            <div className="results__card-label">Evidence Confidence</div>
            <div className="results__big" style={{ color: "#0f766e" }}>
              {evidencePct}%
            </div>
            <div className="results__hint">Average verification confidence across assessed skills</div>
            <div style={{ marginTop: 8, fontSize: "0.84rem", color: "#475569" }}>
              Skills assessed: <strong>{analysis.assessment_count}</strong> · Priority gaps: <strong>{analysis.gap_count}</strong>
            </div>
          </div>
        </section>

        {/* Top Verified Strengths */}
        {strengths.length > 0 && (
          <section className="results__section">
            <h2>Top Verified Strengths</h2>
            <p>Skills where your verified evidence meets or exceeds industry expectations for {analysis.target_role}.</p>
            <div className="results__evidence">
              {strengths.slice(0, 4).map((g) => {
                const displayName = g.skills?.display_name || g.skills?.canonical_name || "Unknown";
                return (
                  <div key={g.id} className="results__evidence-card" style={{ borderColor: "#10b981" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <h3 style={{ display: "flex", alignItems: "center", gap: 6 }}>
                        <span style={{ color: "#10b981" }}>✓</span> {displayName}
                      </h3>
                      <span className="priority priority--covered">Covered</span>
                    </div>
                    <div style={{ fontSize: "0.84rem", color: "#475569", marginTop: 4 }}>{g.explanation}</div>
                    <div style={{ marginTop: 8, fontSize: "0.82rem", color: "#059669", display: "flex", gap: 10, flexWrap: "wrap" }}>
                      <span>Proficiency: <strong>{Math.round(g.current_proficiency * 100)}%</strong></span>
                      <span>Required: <strong>{Math.round(g.required_level * 100)}%</strong></span>
                      <span>Confidence: <strong>{Math.round(g.confidence * 100)}%</strong></span>
                      {g.quadrant_title && <span className="results__quadrant-tag">{g.quadrant_title}</span>}
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        )}

        {/* Priority gaps */}
        <section className="results__section">
          <h2>Priority Gaps</h2>
          <p>Multi-factor prioritization — gap size × role importance × interview relevance × demand × evidence confidence.</p>
          <div className="results__gaps">
            {priorityGaps.slice(0, 6).map((g, idx) => {
              const displayName = g.skills?.display_name || g.skills?.canonical_name || "Unknown";
              const prio = getPriorityLabel(g.priority_score, g.priority_category);
              const typeBadge = getGapTypeBadge(g.gap_type);
              const currentPct = Math.round(g.current_proficiency * 100);
              const requiredPct = Math.round(g.required_level * 100);
              const gapPct = Math.round(g.gap * 100);
              const confPct = Math.round(g.confidence * 100);

              return (
                <div key={g.id} className="results__gap-card">
                  <div className="results__gap-num">{idx + 1}</div>
                  <div style={{ flex: 1 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 8 }}>
                      <div>
                        <strong style={{ fontSize: "1.05rem" }}>{displayName}</strong>
                        <span className="results__cat" style={{ marginLeft: 8 }}>{g.skills?.category || ""}</span>
                      </div>
                      <div className="results__gap-tags" style={{ margin: 0 }}>
                        <span className={`gap-type-badge ${typeBadge.cls}`}>{typeBadge.label}</span>
                        <span className={`priority ${prio.cls}`}>
                          {prio.label} · {g.priority_score.toFixed(1)}
                        </span>
                      </div>
                    </div>

                    <div style={{ fontSize: "0.85rem", color: "#475569", marginTop: 6, lineHeight: 1.5 }}>
                      {g.explanation}
                    </div>

                    {g.actionable_advice && (
                      <div className="results__advice-box">
                        <strong>Recommended Action:</strong> {g.actionable_advice}
                      </div>
                    )}

                    <div style={{ marginTop: 8, fontSize: "0.80rem", color: "#64748b", display: "flex", gap: 12, flexWrap: "wrap" }}>
                      <span>Demonstrated: <strong>{currentPct}%</strong></span>
                      <span>Target Level: <strong>{requiredPct}%</strong></span>
                      <span>Gap: <strong style={{ color: "#e11d48" }}>{gapPct}%</strong></span>
                      <span>Confidence: <strong>{confPct}%</strong></span>
                      <span>Role Importance: <strong>{g.importance.toFixed(2)}</strong></span>
                      <span>Interview Weight: <strong>{g.interview_relevance.toFixed(2)}</strong></span>
                      {g.quadrant_title && <span className="results__quadrant-tag">{g.quadrant_title}</span>}
                    </div>
                  </div>
                </div>
              );
            })}
            {priorityGaps.length === 0 && (
              <div style={{ color: "#64748b", fontSize: "0.9rem" }}>No priority gaps — all required skills are covered.</div>
            )}
          </div>
        </section>

        {/* Evidence Gaps Section */}
        {evidenceGaps.length > 0 && (
          <section className="results__section">
            <h2>Evidence Gaps · Missing Independent Proof</h2>
            <p>
              The following skills are required or claimed, but INAURA lacks sufficient independent proof.
              <strong> Note: This indicates absence of submitted evidence, NOT confirmed inability.</strong>
            </p>
            <div className="results__evidence">
              {evidenceGaps.slice(0, 4).map((g) => {
                const displayName = g.skills?.display_name || g.skills?.canonical_name || "Unknown";
                return (
                  <div key={g.id} className="results__evidence-card" style={{ borderColor: "#f59e0b" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <h3>{displayName}</h3>
                      <span className="gap-type-badge gap-type--evidence">Missing Evidence</span>
                    </div>
                    <div style={{ fontSize: "0.84rem", color: "#475569", marginTop: 4 }}>{g.explanation}</div>
                    <div className="results__advice-box" style={{ borderLeftColor: "#f59e0b" }}>
                      <strong>Action to Verify:</strong> {g.actionable_advice || `Submit a GitHub repo, project, or certificate demonstrating ${displayName}.`}
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        )}

        {/* LeetCode Topic Coverage Breakdown */}
        {lcTopicMeta && lcTopicMeta.status === "available" && lcTopicMeta.pillar_breakdown && (
          <section className="results__section">
            <h2>DSA Topic Coverage Analysis</h2>
            <div className="results__leetcode-card">
              <div className="results__leetcode-header">
                <div>
                  <h3 style={{ margin: 0, fontSize: "1.05rem" }}>LeetCode DSA Topic Coverage · {lcUsername}</h3>
                  <div style={{ fontSize: "0.82rem", color: "var(--muted)", marginTop: 2 }}>
                    Topic breadth & depth across 9 canonical DSA pillars
                  </div>
                </div>
                <div className="results__leetcode-diffs">
                  <span className="results__badge-diff results__badge-diff--easy">Easy: {lcEasy}</span>
                  <span className="results__badge-diff results__badge-diff--medium">Medium: {lcMed}</span>
                  <span className="results__badge-diff results__badge-diff--hard">Hard: {lcHard}</span>
                  <span style={{ fontWeight: 700, fontSize: "0.82rem", marginLeft: 4 }}>Total: {lcTotal}</span>
                </div>
              </div>

              <div className="results__leetcode-meta-row">
                <span>
                  Topic Breadth: <strong>{Math.round((lcTopicMeta.breadth_score ?? lcTopicMeta.topic_breadth_score ?? 0) * 100)}%</strong> ({lcTopicMeta.covered_pillars?.length || lcTopicMeta.covered_topics?.length || 0} covered, {lcTopicMeta.moderate_pillars?.length || lcTopicMeta.moderate_topics?.length || 0} moderate, {lcTopicMeta.missing_pillars?.length || lcTopicMeta.missing_topics?.length || 0} unpracticed)
                </span>
                <span>·</span>
                <span>
                  Topic Depth: <strong>{Math.round((lcTopicMeta.depth_score ?? lcTopicMeta.topic_depth_score ?? 0) * 100)}%</strong>
                </span>
              </div>

              <div className="results__leetcode-pillars-grid">
                {Object.entries(lcTopicMeta.pillar_breakdown).map(([pillar, data]: [string, any]) => {
                  const badgeClass =
                    data.status === "covered"
                      ? "results__pillar-badge--covered"
                      : data.status === "moderate"
                      ? "results__pillar-badge--moderate"
                      : data.status === "weak"
                      ? "results__pillar-badge--weak"
                      : "results__pillar-badge--missing";
                  const pctBar = Math.min(100, Math.round((data.solved / 15) * 100));
                  return (
                    <div key={pillar} className="results__pillar-box">
                      <div className="results__pillar-top">
                        <strong>{pillar}</strong>
                        <span className={`results__pillar-badge ${badgeClass}`}>{data.status}</span>
                      </div>
                      <div className="results__pillar-count">
                        {data.solved} problems solved {lcTotal > 0 ? `(${data.percentage}%)` : ""}
                      </div>
                      <div className="results__pillar-bar-wrap">
                        <div className="results__pillar-bar" style={{ width: `${pctBar}%` }} />
                      </div>
                    </div>
                  );
                })}
              </div>

              <div style={{ marginTop: 12, fontSize: "0.78rem", color: "#64748b", fontStyle: "italic" }}>
                * INAURA assesses algorithmic competency based on balanced pillar breadth and depth. High problem volume concentrated in single topics does not substitute for practice across Trees, Graphs, Dynamic Programming, and Backtracking.
              </div>
            </div>
          </section>
        )}

        {/* Confidence-Aware Skill Quadrants */}
        <section className="results__section">
          <h2>Confidence-Aware Skill Quadrants</h2>
          <p>Cross-referencing demonstrated proficiency against evidence confidence level.</p>
          <div className="results__quadrants-grid">
            <div className="results__quadrant-card results__quadrant-card--strong">
              <div className="results__quadrant-header">
                <span>Strong & Validated</span>
                <span className="results__quadrant-count">{strongValidated.length}</span>
              </div>
              <div className="results__quadrant-desc">High proficiency backed by robust independent evidence.</div>
              <div className="results__quadrant-skills">
                {strongValidated.map((s) => (
                  <span key={s.id} className="results__quadrant-skill-chip">{s.skills?.display_name || s.skills?.canonical_name}</span>
                ))}
                {strongValidated.length === 0 && <span style={{ fontSize: "0.76rem", color: "#94a3b8" }}>None yet</span>}
              </div>
            </div>

            <div className="results__quadrant-card results__quadrant-card--unverified">
              <div className="results__quadrant-header">
                <span>Unverified Claims / Emergent</span>
                <span className="results__quadrant-count">{unverifiedClaims.length}</span>
              </div>
              <div className="results__quadrant-desc">Promising proficiency but needs independent proof.</div>
              <div className="results__quadrant-skills">
                {unverifiedClaims.map((s) => (
                  <span key={s.id} className="results__quadrant-skill-chip">{s.skills?.display_name || s.skills?.canonical_name}</span>
                ))}
                {unverifiedClaims.length === 0 && <span style={{ fontSize: "0.76rem", color: "#94a3b8" }}>None</span>}
              </div>
            </div>

            <div className="results__quadrant-card results__quadrant-card--confirmed">
              <div className="results__quadrant-header">
                <span>Confirmed Growth Needs</span>
                <span className="results__quadrant-count">{confirmedNeeds.length}</span>
              </div>
              <div className="results__quadrant-desc">Demonstrated deficit below benchmark with verified evidence.</div>
              <div className="results__quadrant-skills">
                {confirmedNeeds.map((s) => (
                  <span key={s.id} className="results__quadrant-skill-chip">{s.skills?.display_name || s.skills?.canonical_name}</span>
                ))}
                {confirmedNeeds.length === 0 && <span style={{ fontSize: "0.76rem", color: "#94a3b8" }}>None</span>}
              </div>
            </div>

            <div className="results__quadrant-card results__quadrant-card--exploratory">
              <div className="results__quadrant-header">
                <span>Exploratory / Unclear</span>
                <span className="results__quadrant-count">{exploratory.length}</span>
              </div>
              <div className="results__quadrant-desc">Limited evidence to benchmark definitively.</div>
              <div className="results__quadrant-skills">
                {exploratory.map((s) => (
                  <span key={s.id} className="results__quadrant-skill-chip">{s.skills?.display_name || s.skills?.canonical_name}</span>
                ))}
                {exploratory.length === 0 && <span style={{ fontSize: "0.76rem", color: "#94a3b8" }}>None</span>}
              </div>
            </div>
          </div>
        </section>

        {/* Skill overview table */}
        <section className="results__section">
          <h2>Skill Overview</h2>
          <p>Current vs required, gap, confidence, market demand, and priority — sorted by priority.</p>

          <div className="results__table-wrap">
            <table className="results__table">
              <thead>
                <tr>
                  <th>Skill</th>
                  <th>Type</th>
                  <th>Current</th>
                  <th>Required</th>
                  <th>Gap</th>
                  <th>Demand</th>
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
                  const demandPct = Math.round(g.demand * 100);
                  const prio = getPriorityLabel(g.priority_score, g.priority_category);
                  const typeBadge = getGapTypeBadge(g.gap_type);
                  const displayName = g.skills?.display_name || g.skills?.canonical_name || "Unknown";
                  return (
                    <tr key={g.id}>
                      <td>
                        <strong>{displayName}</strong>
                        <span className="results__cat">{g.skills?.category || ""}</span>
                      </td>
                      <td>
                        <span className={`gap-type-badge ${typeBadge.cls}`}>{typeBadge.label}</span>
                      </td>
                      <td>{currentPct}%</td>
                      <td>{requiredPct}%</td>
                      <td>{gapPct}%</td>
                      <td>{demandPct}%</td>
                      <td>{confPct}%</td>
                      <td>
                        <span className={`priority ${prio.cls}`}>{prio.label}</span>
                      </td>
                    </tr>
                  );
                })}
                {sortedGaps.length === 0 && (
                  <tr>
                    <td colSpan={8} style={{ textAlign: "center", color: "#64748b", padding: 16 }}>
                      No gaps found — all required skills covered or no requirements for this role.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>

        {/* Next step to roadmap */}
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

