/* eslint-disable @typescript-eslint/no-explicit-any, react-hooks/set-state-in-effect */
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getLatestAnalysis, getGaps, setSkillOverride, type AnalysisResult, type SkillGap, type EvidenceSource } from "../services/analysis";
import { listEvidence, listProjects, listGithubRepos, type Evidence, type Project, type GithubRepo, setEvidenceExcluded, setProjectExcluded, setEvidenceAiAssisted, setProjectAiAssisted, setGithubRepoExcluded, setGithubRepoAiAssisted } from "../services/evidence";
import {
  getAvailableAssessments,
  type AvailableAssessment,
} from "../services/assessment";
import AssessmentModal from "../components/assessment/AssessmentModal";
import Button from "../components/ui/Button";
import "./AnalysisResults.css";

export default function AnalysisResults() {
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null);
  const [gaps, setGaps] = useState<SkillGap[]>([]);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [githubRepos, setGithubRepos] = useState<GithubRepo[]>([]);
  const [assessable, setAssessable] = useState<AvailableAssessment[]>([]);
  const [activeAssessment, setActiveAssessment] = useState<AvailableAssessment | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [provenanceGap, setProvenanceGap] = useState<SkillGap | null>(null);
  const [overrideConfirm, setOverrideConfirm] = useState<SkillGap | null>(null);
  const [overriding, setOverriding] = useState(false);
  const [evidenceActionLoading, setEvidenceActionLoading] = useState<string | null>(null);

  const loadAssessments = useCallback(async () => {
    try {
      const data = await getAvailableAssessments();
      setAssessable(data.available || []);
    } catch {
      setAssessable([]);
    }
  }, []);

  const reload = useCallback(async () => {
    try {
      const [a, g, ev, pr, gh] = await Promise.all([
        getLatestAnalysis(),
        getGaps().catch(() => [] as SkillGap[]),
        listEvidence().catch(() => [] as Evidence[]),
        listProjects().catch(() => [] as Project[]),
        listGithubRepos().catch(() => [] as GithubRepo[]),
      ]);
      setAnalysis(a);
      setGaps(g);
      setEvidence(ev);
      setProjects(pr);
      setGithubRepos(gh);
      await loadAssessments();
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
  }, [loadAssessments]);

  useEffect(() => {
    reload();
  }, [reload]);

  const refreshAfterAssessment = useCallback(async () => {
    try {
      const [a, g] = await Promise.all([
        getLatestAnalysis(),
        getGaps().catch(() => [] as SkillGap[]),
      ]);
      setAnalysis(a);
      setGaps(g);
    } catch {
      // keep current view if refresh fails
      void 0;
    }
    await loadAssessments();
  }, [loadAssessments]);

  const handleOverride = async (gap: SkillGap) => {
    setOverriding(true);
    try {
      const skillName = gap.skills?.display_name || gap.skills?.canonical_name || gap.canonical_name || gap.skill || "";
      if (!skillName) throw new Error("Skill name missing");
      await setSkillOverride(skillName);
      setOverrideConfirm(null);
      // Reload after backend recalculates
      await reload();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Failed to override skill");
    } finally {
      setOverriding(false);
    }
  };

  const handleEvidenceExclude = async (id: string, isExcluded: boolean, type: "evidence" | "project") => {
    setEvidenceActionLoading(id);
    try {
      if (type === "evidence") await setEvidenceExcluded(id, isExcluded);
      else await setProjectExcluded(id, isExcluded);
      await reload();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Failed to update evidence");
    } finally {
      setEvidenceActionLoading(null);
    }
  };

  const handleAiToggle = async (id: string, isAi: boolean, type: "evidence" | "project") => {
    setEvidenceActionLoading(id);
    try {
      if (type === "evidence") await setEvidenceAiAssisted(id, isAi);
      else await setProjectAiAssisted(id, isAi);
      await reload();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Failed to update AI flag");
    } finally {
      setEvidenceActionLoading(null);
    }
  };

  const handleGithubRepoExclude = async (fullName: string, isExcluded: boolean) => {
    setEvidenceActionLoading(fullName);
    try {
      await setGithubRepoExcluded(fullName, isExcluded);
      await reload();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Failed to update repo");
    } finally {
      setEvidenceActionLoading(null);
    }
  };

  const handleGithubRepoAi = async (fullName: string, isAi: boolean) => {
    setEvidenceActionLoading(fullName);
    try {
      await setGithubRepoAiAssisted(fullName, isAi);
      await reload();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Failed to update repo AI flag");
    } finally {
      setEvidenceActionLoading(null);
    }
  };

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

  const sortedGaps = [...gaps].sort((a, b) => b.priority_score - a.priority_score);
  // Target-role vs portfolio separation
  const targetGaps = sortedGaps.filter((g) => !g.is_portfolio);
  const portfolioGaps = sortedGaps.filter((g) => g.is_portfolio);

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

  const assessmentFor = (g: SkillGap): AvailableAssessment | undefined => {
    const names = [g.skills?.display_name, g.skills?.canonical_name, g.canonical_name].filter(Boolean) as string[];
    return assessable.find((a) =>
      names.some((n) => n.toLowerCase() === a.skill.toLowerCase() || n.toLowerCase() === a.skill_key.toLowerCase())
    );
  };

  const renderEvidenceCell = (g: SkillGap) => {
    const sources = g.evidence_sources || [];
    const label = g.evidence_state_label || (g.current_proficiency === 0 && g.confidence === 0 ? "No evidence" : "Evidence-based estimate");
    // Determine summary label per spec: use backend label directly, don't invent
    if (g.is_overridden) {
      return (
        <button className="results__evidence-link results__evidence-link--overridden" onClick={() => setProvenanceGap(g)} title="Click to see why this score">
          Overridden · 0% <span style={{ fontSize: "0.72em" }}>(was {Math.round((g as any).original_proficiency ? (g as any).original_proficiency*100 : 0)}%)</span>
        </button>
      );
    }
    if (!sources.length && g.evidence_state === "no_evidence") {
      return (
        <button className="results__evidence-link results__evidence-link--none" onClick={() => setProvenanceGap(g)}>
          No evidence
        </button>
      );
    }
    // Show first source label or count
    const firstLabel = sources[0]?.source_label || label;
    const extra = sources.length > 1 ? ` +${sources.length - 1}` : "";
    return (
      <button className="results__evidence-link" onClick={() => setProvenanceGap(g)} title="Click to see why this score">
        {firstLabel}{extra}
      </button>
    );
  };

  const renderAssessmentAction = (g: SkillGap) => {
    const item = assessmentFor(g);
    // Hard rule: no-evidence role-critical skill should still be assessable if question bank supports it.
    // If backend didn't return an assessable entry but skill is required and has no evidence, still show Assess if bank covers it.
    // Fallback check: if no item but skill is portfolio? Don't show.
    if (!item) {
      // No bank coverage => show dash, but still allow if has_assessment already?
      if (g.has_assessment) {
        return <span className="results__assessed-badge">Assessment {g.assessment_score !== null ? Math.round((g.assessment_score||0)*100)+'%' : ''}</span>;
      }
      return <span style={{ color: "#94a3b8" }}>—</span>;
    }
    const last = item.last_assessment;
    return (
      <span style={{ display: "inline-flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
        {last && (
          <span className="results__assessed-badge" title={`INAURA assessment ${item.skill}`}>
            Assessment {last.correct_count}/{last.question_count}
          </span>
        )}
        <button className="results__verify-btn" onClick={() => setActiveAssessment(item)}>
          {last ? "Re-verify" : "Assess this skill"}
        </button>
      </span>
    );
  };

  const getGapTypeBadge = (type?: string) => {
    if (type === "evidence_gap") return { label: "Evidence Gap", cls: "gap-type--evidence" };
    if (type === "coverage_gap") return { label: "Coverage Gap", cls: "gap-type--coverage" };
    if (type === "industry_data_gap") return { label: "Industry Data Gap", cls: "gap-type--industry" };
    return { label: "Skill Gap", cls: "gap-type--skill" };
  };

  const strengths = targetGaps.filter(
    (g) =>
      (g.gap <= 1e-9 || g.current_proficiency >= g.required_level) &&
      g.confidence >= 0.35 &&
      g.current_proficiency >= 0.50 &&
      g.gap_type !== "evidence_gap"
  );

  const priorityGaps = targetGaps.filter((g) => g.gap > 0);

  const evidenceGaps = targetGaps.filter(
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

  const renderProvenanceDrawer = () => {
    if (!provenanceGap) return null;
    const g = provenanceGap;
    const displayName = g.skills?.display_name || g.skills?.canonical_name || g.canonical_name;
    const sources: EvidenceSource[] = (g.evidence_sources as EvidenceSource[]) || [];
    return (
      <div className="prov__overlay" onClick={() => setProvenanceGap(null)} role="dialog" aria-modal="true">
        <div className="prov__drawer" onClick={(e) => e.stopPropagation()}>
          <div className="prov__header">
            <div>
              <div className="prov__eyebrow">Why this score?</div>
              <h3 className="prov__title">{displayName}</h3>
            </div>
            <button className="prov__close" onClick={() => setProvenanceGap(null)}>×</button>
          </div>
          <div className="prov__body">
            <div className="prov__row">
              <span>Current proficiency</span><strong>{Math.round(g.current_proficiency*100)}%</strong>
            </div>
            <div className="prov__row">
              <span>Confidence</span><strong>{Math.round(g.confidence*100)}%</strong>
            </div>
            <div className="prov__row">
              <span>Required</span><strong>{Math.round(g.required_level*100)}%</strong>
            </div>
            <div className="prov__row">
              <span>Gap</span><strong style={{ color: g.gap>0 ? "#dc2626" : "#059669" }}>{Math.round(g.gap*100)}%</strong>
            </div>
            <div className="prov__row">
              <span>Evidence state</span><strong>{g.evidence_state_label || g.evidence_state}</strong>
            </div>
            {g.is_overridden && <div className="prov__note">This skill was overridden by you to 0%. Original estimate was {Math.round(((g as any).original_proficiency||0)*100)}%.</div>}
            <div className="prov__sources">
              <h4>Contributing sources ({sources.length})</h4>
              {sources.length === 0 ? (
                <div className="prov__empty">No evidence found. INAURA has no evidence demonstrating this skill. This indicates absence of submitted evidence, not confirmed inability. Submit a GitHub project, coding profile, coursework, certification, or complete an INAURA assessment to demonstrate it.</div>
              ) : (
                sources.map((s, idx) => (
                  <div key={idx} className="prov__source">
                    <div className="prov__source-head">
                      <strong>{s.source_label}</strong>
                      <span className="prov__source-type">{s.source_type}</span>
                      {s.is_ai_assisted && <span className="prov__badge prov__badge--ai">AI-assisted</span>}
                    </div>
                    <div className="prov__source-meta">
                      <span>Strength: {(s.strength*100).toFixed(0)}%</span>
                      <span>·</span>
                      <span>Reliability: {(s.reliability*100).toFixed(0)}%</span>
                    </div>
                    {s.explanation && <div className="prov__explanation">{s.explanation}</div>}
                    {s.details && Object.keys(s.details).length>0 && (
                      <div className="prov__details">
                        {Object.entries(s.details).filter(([k]) => k !== "repositories").map(([k,v]) => (
                          <div key={k} className="prov__detail"><span className="prov__detail-k">{k}:</span> <span>{String(v).slice(0,200)}</span></div>
                        ))}
                        {(s.details as any).repositories && Array.isArray((s.details as any).repositories) && (
                          <div style={{ marginTop: 6 }}>
                            <div style={{ fontWeight: 600, fontSize: "0.82rem" }}>Contributing repositories ({(s.details as any).repositories.length}):</div>
                            {(s.details as any).repositories.map((r: any, ri: number) => (
                              <div key={ri} style={{ fontSize: "0.78rem", paddingLeft: 8, marginTop: 2 }}>
                                • <strong>{r.full_name || r.name}</strong> {r.url ? <a href={r.url} target="_blank" rel="noreferrer" style={{ color: "#0f766e" }}>{r.url}</a> : null} {r.depth !== undefined ? `(depth ${r.depth}, strength ${Math.round((r.signal_strength||0)*100)}%, reliability 40%)` : null} {r.classification ? `· ${r.classification}` : null}
                              </div>
                            ))}
                          </div>
                        )}
                        {(s as any).source_url && !(s.details as any).source_url && (
                          <div className="prov__detail"><span className="prov__detail-k">source_url:</span> <a href={(s as any).source_url} target="_blank" rel="noreferrer" style={{ color: "#0f766e" }}>{(s as any).source_url}</a></div>
                        )}
                        {(s as any).evidence_depth !== undefined && !(s.details as any).evidence_depth && (
                          <div className="prov__detail"><span className="prov__detail-k">evidence_depth:</span> <span>{String((s as any).evidence_depth)}</span></div>
                        )}
                      </div>
                    )}
                  </div>
                ))
              )}
              {g.has_assessment && (
                <div className="prov__source prov__source--assessment">
                  <div className="prov__source-head"><strong>INAURA Assessment</strong><span className="prov__badge">Validated</span></div>
                  <div>Score: {g.assessment_score!==null && g.assessment_score!==undefined ? Math.round((g.assessment_score as number)*100)+'%' : '—'}</div>
                  <div style={{ fontSize: "0.82rem", color: "#64748b" }}>Assessment is a separate stronger evidence source. GitHub reliability remains unchanged (supporting evidence).</div>
                </div>
              )}
              <div style={{ marginTop: 12, padding: 10, background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 8 }}>
                <h4 style={{ margin: "0 0 6px", fontSize: "0.90rem" }}>Why is this skill required for {analysis.target_role}?</h4>
                <div style={{ fontSize: "0.82rem", color: "#334155", display: "flex", flexDirection: "column", gap: 4 }}>
                  <div><strong>Source:</strong> {g.requirement_source || g.source || "Industry requirements"} {g.requirement_source_url ? <a href={g.requirement_source_url} target="_blank" rel="noreferrer" style={{ color: "#0f766e", wordBreak: "break-all" }}>{g.requirement_source_url}</a> : null}</div>
                  {g.requirement_source_version && <div><strong>Source version:</strong> {g.requirement_source_version}</div>}
                  {g.requirement_source_reference && <div><strong>Reference:</strong> {g.requirement_source_reference}</div>}
                  {g.requirement_role_relevance && <div><strong>Role relevance:</strong> {g.requirement_role_relevance}</div>}
                  {g.requirement_description && <div><strong>Description:</strong> {g.requirement_description}</div>}
                  {g.evidence_context && <div><strong>Evidence context:</strong> {g.evidence_context}</div>}
                </div>
                <div style={{ fontSize: "0.72rem", color: "#64748b", fontStyle: "italic", marginTop: 8 }}>Industry-grounded role requirements based on O*NET/ESCO with INAURA mapping heuristics — not universally required. <br/>Candidate evidence provenance (above) answers why INAURA thinks you have this skill; requirement provenance answers why the role requires it.</div>
              </div>
            </div>
            <div className="prov__footer-note">
              Industry requirements tell us WHAT IS REQUIRED. Evidence tells us WHAT IS DEMONSTRATED. Assessment tells us WHAT YOU CAN DIRECTLY DEMONSTRATE.
            </div>
          </div>
          <div className="prov__actions">
            <Button variant="secondary" size="md" onClick={() => setProvenanceGap(null)}>Close</Button>
            {!g.is_overridden && !g.is_portfolio && g.evidence_state !== "no_evidence" && g.evidence_state !== "user_override" && (
              <Button variant="secondary" size="md" onClick={() => { setProvenanceGap(null); setOverrideConfirm(g); }}>
                I don't actually know this yet
              </Button>
            )}
          </div>
        </div>
      </div>
    );
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
            <span>·</span>
            <span>Benchmark: <strong>Industry Intelligence 2026.1</strong> (ACM/IEEE, Stack Overflow, BLS)</span>
          </div>
        </div>
      </header>

      <main className="container results__main">
        <div className="results__disclaimer-box">
          <div className="results__disclaimer-icon">ℹ️</div>
          <div>
            <strong>Career Readiness Benchmark:</strong> {analysis.disclaimer || "Career readiness measures alignment between your verified evidence and authentic industry benchmarks (ACM/IEEE, Stack Overflow 2024, BLS). It is an objective developmental indicator, not a statistical hiring probability or guarantee of placement."}
          </div>
        </div>

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

        {strengths.length > 0 && (
          <section className="results__section">
            <h2>Top Strengths</h2>
            <p>
              Skills where your submitted evidence meets or exceeds industry expectations for{" "}
              {analysis.target_role}. Repository and project evidence is a supporting
              <em> estimate</em> — only a completed INAURA assessment marks a skill as validated.
            </p>
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
                      <span>Estimated: <strong>{Math.round(g.current_proficiency * 100)}%</strong></span>
                      <span>Required: <strong>{Math.round(g.required_level * 100)}%</strong></span>
                      <span>Confidence: <strong>{Math.round(g.confidence * 100)}%</strong></span>
                      {g.quadrant_title && <span className="results__quadrant-tag">{g.quadrant_title}</span>}
                      <button className="results__evidence-link results__evidence-link--small" onClick={() => setProvenanceGap(g)}>{g.evidence_state_label}</button>
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        )}

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
                      <div className="results__gap-tags" style={{ margin: 0, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                        <span className={`gap-type-badge ${typeBadge.cls}`}>{typeBadge.label}</span>
                        <span className={`priority ${prio.cls}`}>
                          {prio.label} · {g.priority_score.toFixed(1)}
                        </span>
                        {renderAssessmentAction(g)}
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

                    <div style={{ marginTop: 8, fontSize: "0.80rem", color: "#64748b", display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
                      <span>Estimated: <strong>{currentPct}%</strong></span>
                      <span>Target Level: <strong>{requiredPct}%</strong></span>
                      <span>Gap: <strong style={{ color: "#e11d48" }}>{gapPct}%</strong></span>
                      <span>Confidence: <strong>{confPct}%</strong></span>
                      <span>Role Importance: <strong>{g.importance.toFixed(2)}</strong></span>
                      <span>Interview Weight: <strong>{g.interview_relevance.toFixed(2)}</strong></span>
                      {g.quadrant_title && <span className="results__quadrant-tag">{g.quadrant_title}</span>}
                      <button className="results__evidence-link results__evidence-link--small" onClick={() => setProvenanceGap(g)} title="Why this score?">{g.evidence_state_label}</button>
                    </div>
                    {!g.is_overridden && g.evidence_state !== "no_evidence" && g.evidence_state !== "user_override" && (
                      <div style={{ marginTop: 8 }}>
                        <button className="results__override-btn" onClick={() => setOverrideConfirm(g)}>I don't actually know this yet</button>
                      </div>
                    )}
                    {g.is_overridden && <div style={{ marginTop: 6, fontSize: "0.80rem", color: "#dc2626" }}>User marked as not known — new evidence or assessment required to restore.</div>}
                  </div>
                </div>
              );
            })}
            {priorityGaps.length === 0 && (
              <div style={{ color: "#64748b", fontSize: "0.9rem" }}>No priority gaps — all required skills are covered.</div>
            )}
          </div>
        </section>

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
                    <div style={{ marginTop: 8, display: "flex", gap: 8 }}>
                      {renderAssessmentAction(g)}
                      <button className="results__evidence-link results__evidence-link--small" onClick={() => setProvenanceGap(g)}>Why this score?</button>
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        )}

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

        <section className="results__section">
          <h2>Skill Overview — Target-Role Requirements</h2>
          <p>Current vs required, gap, confidence, evidence provenance, market demand, and priority — sorted by priority. Click Evidence to see why INAURA gave this score.</p>
          <p style={{ fontSize: "0.82rem", color: "#64748b", marginTop: -6 }}>
            Evidence reliability: INAURA assessment (direct validation, 0.95) &gt; LeetCode/Codeforces/Kaggle
            performance and verified coursework (0.85/0.80) &gt; certifications (0.55) &gt; GitHub/project artifacts (0.40,
            supporting evidence). A repository shows that you worked with a technology; a passed
            assessment shows demonstrated understanding. Until a skill is validated its estimate is
            held back toward "not yet validated" — verifying it can move the number up <em>or</em> down
            and is what raises confidence.
            <em> Prototype heuristic model — not a validated measurement of proficiency.</em>
          </p>

          <div className="results__table-wrap">
            <table className="results__table">
              <thead>
                <tr>
                  <th>Skill</th>
                  <th>Type</th>
                  <th>Current</th>
                  <th>Required</th>
                  <th>Gap</th>
                  <th>Confidence</th>
                  <th>Evidence</th>
                  <th>Priority</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {targetGaps.map((g) => {
                  const currentPct = Math.round(g.current_proficiency * 100);
                  const requiredPct = Math.round(g.required_level * 100);
                  const gapPct = Math.round(g.gap * 100);
                  const confPct = Math.round(g.confidence * 100);
                  const prio = getPriorityLabel(g.priority_score, g.priority_category);
                  const typeBadge = getGapTypeBadge(g.gap_type);
                  const displayName = g.skills?.display_name || g.skills?.canonical_name || g.canonical_name || "Unknown";
                  return (
                    <tr key={g.id} style={g.is_overridden ? { opacity: 0.7, background: "#fef2f2" } : undefined}>
                      <td>
                        <strong>{displayName}</strong>
                        <span className="results__cat">{g.skills?.category || ""}</span>
                        {g.is_overridden && <span style={{ fontSize: "0.70rem", color: "#dc2626", display: "block" }}>Overridden to 0%</span>}
                      </td>
                      <td>
                        <span className={`gap-type-badge ${typeBadge.cls}`}>{typeBadge.label}</span>
                      </td>
                      <td>{currentPct}%</td>
                      <td>{requiredPct}%</td>
                      <td>{gapPct}%</td>
                      <td>{confPct}%</td>
                      <td>{renderEvidenceCell(g)}</td>
                      <td>
                        <span className={`priority ${prio.cls}`}>{prio.label}</span>
                      </td>
                      <td>
                        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                          {renderAssessmentAction(g)}
                          {!g.is_overridden && g.evidence_state !== "no_evidence" && g.evidence_state !== "user_override" && (
                            <button className="results__override-btn" onClick={() => setOverrideConfirm(g)} style={{ fontSize: "0.75rem", padding: "4px 8px" }}>
                              I don't know this yet
                            </button>
                          )}
                          {g.is_overridden && <span style={{ fontSize: "0.70rem", color: "#dc2626" }}>User override</span>}
                        </div>
                      </td>
                    </tr>
                  );
                })}
                {targetGaps.length === 0 && (
                  <tr>
                    <td colSpan={9} style={{ textAlign: "center", color: "#64748b", padding: 16 }}>
                      No gaps found — all required skills covered or no requirements for this role.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>

        {portfolioGaps.length > 0 && (
          <section className="results__section" style={{ background: "#f8fafc" }}>
            <h2>Other Detected Portfolio Skills</h2>
            <p>Skills discovered in your evidence but not required for {analysis.target_role}. They do not affect your target-role readiness score, but are shown for completeness.</p>
            <div className="results__table-wrap">
              <table className="results__table">
                <thead>
                  <tr>
                    <th>Skill</th>
                    <th>Current</th>
                    <th>Confidence</th>
                    <th>Evidence</th>
                    <th>Note</th>
                  </tr>
                </thead>
                <tbody>
                  {portfolioGaps.map((g) => {
                    const displayName = g.skills?.display_name || g.skills?.canonical_name || g.canonical_name || "Unknown";
                    return (
                      <tr key={g.id}>
                        <td><strong>{displayName}</strong><span className="results__cat">{g.skills?.category || "Additional"}</span></td>
                        <td>{Math.round(g.current_proficiency*100)}%</td>
                        <td>{Math.round(g.confidence*100)}%</td>
                        <td>{renderEvidenceCell(g)}</td>
                        <td style={{ fontSize: "0.82rem", color: "#64748b" }}>Not required for this role — does not inflate readiness.</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {(evidence.length > 0 || projects.length > 0 || githubRepos.length > 0) && (
          <section className="results__section">
            <h2>Evidence Sources — Personalization Controls</h2>
            <p>Exclude specific evidence from scoring or flag as AI-assisted. Raw evidence is preserved; only the scoring contribution changes and analysis is recalculated. Each repository has independent controls.</p>
            {githubRepos.length > 0 && (
              <div style={{ marginTop: 12 }}>
                <h3 style={{ fontSize: "0.95rem", margin: "12px 0 8px" }}>GitHub Repositories — {githubRepos.length} discovered</h3>
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {githubRepos.map((repo) => (
                    <div key={repo.full_name} className="results__evidence-card" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8, borderLeft: repo.fork ? "3px solid #f59e0b" : "3px solid #e2e8f0" }}>
                      <div style={{ flex: 1, minWidth: 200 }}>
                        <strong style={{ fontSize: "0.92rem" }}>{repo.full_name}</strong> {repo.fork && <span style={{ fontSize: "0.72rem", background: "#fef3c7", border: "1px solid #fde68a", padding: "1px 6px", borderRadius: 4, marginLeft: 6 }}>Forked repository</span>} {!repo.fork && <span style={{ fontSize: "0.72rem", background: "#ecfdf5", border: "1px solid #a7f3d0", padding: "1px 6px", borderRadius: 4, marginLeft: 6 }}>Original repository</span>} {repo.archived && <span style={{ fontSize: "0.72rem", background: "#f1f5f9", padding: "1px 6px", borderRadius: 4, marginLeft: 4 }}>Archived</span>}
                        <div style={{ fontSize: "0.78rem", color: "#64748b" }}>{repo.classification || "—"} {repo.pushed_at ? `· pushed ${new Date(repo.pushed_at).toLocaleDateString()}` : ""}</div>
                        {repo.html_url && <div style={{ fontSize: "0.78rem", color: "#0f766e", wordBreak: "break-all" }}><a href={repo.html_url} target="_blank" rel="noreferrer">{repo.html_url}</a></div>}
                      </div>
                      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                        <button
                          className={`results__evidence-toggle ${repo.is_excluded ? "results__evidence-toggle--excluded" : ""}`}
                          onClick={() => handleGithubRepoExclude(repo.full_name, !repo.is_excluded)}
                          disabled={evidenceActionLoading === repo.full_name}
                        >
                          {repo.is_excluded ? "Excluded from current analysis" : "Included"}
                        </button>
                        <label style={{ fontSize: "0.82rem", display: "flex", alignItems: "center", gap: 4 }}>
                          <input type="checkbox" checked={!!repo.is_ai_assisted} onChange={(e) => handleGithubRepoAi(repo.full_name, e.target.checked)} disabled={evidenceActionLoading === repo.full_name} />
                          AI-assisted
                        </label>
                      </div>
                    </div>
                  ))}
                </div>
                <div style={{ fontSize: "0.78rem", color: "#64748b", marginTop: 6, fontStyle: "italic" }}>New repositories default to Included, not AI-assisted. Forked repositories are marked as forks with lower authorship confidence.</div>
              </div>
            )}
            <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 12 }}>
              {evidence.filter(ev => ev.evidence_type !== "github").map((ev) => (
                <div key={ev.id} className="results__evidence-card" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
                  <div>
                    <strong style={{ fontSize: "0.92rem" }}>{ev.title || ev.evidence_type}</strong> <span style={{ fontSize: "0.78rem", color: "#64748b" }}>· {ev.evidence_type} · {ev.verification_status}</span>
                    {ev.source_url && <div style={{ fontSize: "0.78rem", color: "#0f172a", wordBreak: "break-all" }}>{ev.source_url}</div>}
                  </div>
                  <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                    <button
                      className={`results__evidence-toggle ${ev.is_excluded ? "results__evidence-toggle--excluded" : ""}`}
                      onClick={() => handleEvidenceExclude(ev.id, !ev.is_excluded, "evidence")}
                      disabled={evidenceActionLoading === ev.id}
                    >
                      {ev.is_excluded ? "Excluded from current analysis" : "Use this evidence"}
                    </button>
                    <label style={{ fontSize: "0.82rem", display: "flex", alignItems: "center", gap: 4 }}>
                      <input type="checkbox" checked={!!ev.is_ai_assisted} onChange={(e) => handleAiToggle(ev.id, e.target.checked, "evidence")} disabled={evidenceActionLoading === ev.id} />
                      AI-assisted
                    </label>
                  </div>
                </div>
              ))}
              {projects.map((pr) => (
                <div key={pr.id} className="results__evidence-card" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
                  <div>
                    <strong style={{ fontSize: "0.92rem" }}>{pr.name}</strong> <span style={{ fontSize: "0.78rem", color: "#64748b" }}>· Project · {pr.technologies?.join(", ")}</span>
                    {pr.github_url && <div style={{ fontSize: "0.78rem", color: "#0f172a" }}>{pr.github_url}</div>}
                  </div>
                  <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                    <button
                      className={`results__evidence-toggle ${(pr as any).is_excluded ? "results__evidence-toggle--excluded" : ""}`}
                      onClick={() => handleEvidenceExclude(pr.id, !(pr as any).is_excluded, "project")}
                      disabled={evidenceActionLoading === pr.id}
                    >
                      {(pr as any).is_excluded ? "Excluded from current analysis" : "Use this evidence"}
                    </button>
                    <label style={{ fontSize: "0.82rem", display: "flex", alignItems: "center", gap: 4 }}>
                      <input type="checkbox" checked={!!(pr as any).is_ai_assisted} onChange={(e) => handleAiToggle(pr.id, e.target.checked, "project")} disabled={evidenceActionLoading === pr.id} />
                      AI-assisted
                    </label>
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

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

      {provenanceGap && renderProvenanceDrawer()}

      {overrideConfirm && (
        <div className="prov__overlay" onClick={() => setOverrideConfirm(null)}>
          <div className="prov__drawer" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 480 }}>
            <h3 style={{ margin: 0 }}>Set this skill to 0%?</h3>
            <p style={{ marginTop: 8, fontSize: "0.92rem", color: "#475569", lineHeight: 1.5 }}>
              This will override the current estimate in future analyses.<br />
              Your existing evidence and assessment history will be preserved.<br />
              You cannot manually restore the previous estimate.<br />
              New evidence or a new assessment can change the result.
            </p>
            <p style={{ fontSize: "0.85rem", color: "#64748b" }}>Skill: <strong>{overrideConfirm.skills?.display_name || overrideConfirm.skills?.canonical_name || overrideConfirm.canonical_name}</strong> · Current: {Math.round(overrideConfirm.current_proficiency*100)}% · Required: {Math.round(overrideConfirm.required_level*100)}%</p>
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 16 }}>
              <Button variant="secondary" size="md" onClick={() => setOverrideConfirm(null)} disabled={overriding}>Cancel</Button>
              <Button variant="primary" size="md" onClick={() => handleOverride(overrideConfirm)} disabled={overriding}>{overriding ? "Updating…" : "Confirm — Set to 0%"}</Button>
            </div>
          </div>
        </div>
      )}

      {activeAssessment && (
        <AssessmentModal
          key={activeAssessment.skill}
          skill={activeAssessment.skill}
          evidenceProficiency={activeAssessment.proficiency}
          evidenceConfidence={activeAssessment.confidence}
          onClose={() => setActiveAssessment(null)}
          onCompleted={() => {
            void refreshAfterAssessment();
          }}
        />
      )}
    </div>
  );
}
