import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { Link, useLocation } from "react-router-dom";
import { setSkillOverride, type AnalysisResult, type SkillGap } from "../services/analysis";
import {
  type Evidence,
  type Project,
  type GithubRepo,
  setEvidenceExcluded,
  setProjectExcluded,
  setEvidenceAiAssisted,
  setProjectAiAssisted,
  setGithubRepoExcluded,
  setGithubRepoAiAssisted,
} from "../services/evidence";
import { type AvailableAssessment } from "../services/assessment";
import { generateRoadmap } from "../services/roadmap";
import AssessmentModal from "../components/assessment/AssessmentModal";
import SkillAssessmentLayers from "../components/assessment/SkillAssessmentLayers";
import DsaChecklist from "../components/assessment/DsaChecklist";
import SkillEvidenceCard from "../components/analysis/SkillEvidenceCard";
import Button from "../components/ui/app-button";
import { profileData, resultsPageData, roadmapPageData, subscribePageData } from "../lib/pageData";
import { setActiveSection } from "../lib/sectionSpy";
import {
  headlineInsight,
  pct,
  roadmapLinkFor,
  skillName,
  sourceUsage,
  splitGaps,
} from "../components/analysis/analysisModel";
import type { GapActions } from "../components/analysis/gapActions";
import PriorityGaps from "../components/analysis/PriorityGaps";
import EvidenceGaps from "../components/analysis/EvidenceGaps";
import SkillQuadrant from "../components/analysis/SkillQuadrant";
import SkillOverview from "../components/analysis/SkillOverview";
import EvidenceSources from "../components/analysis/EvidenceSources";
import { CodeforcesPanel, DsaCoverage } from "../components/analysis/CodingPractice";
import { codingPracticeData } from "../components/analysis/codingPracticeData";
import "./AnalysisResults.css";
import "../components/analysis/AnalysisPage.css";

/** The two Skill Assessment sidebar links still open a focused view of just that part */
const FOCUS_VIEWS = ["dsa", "skill-assessments"];

const NAV = [
  { id: "overview", label: "Overview" },
  { id: "priority-gaps", label: "Priority gaps" },
  { id: "evidence-gaps", label: "Evidence gaps" },
  { id: "skill-quadrants", label: "Skill quadrants" },
  { id: "skill-overview", label: "Skill overview" },
  { id: "evidence-sources", label: "Evidence sources" },
  { id: "next-steps", label: "Next steps" },
];

const scrollToSection = (id: string, smooth = true) =>
  document.getElementById(id)?.scrollIntoView({ behavior: smooth ? "smooth" : "auto", block: "start" });

export default function AnalysisResults() {
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(() => resultsPageData.peek()?.analysis ?? null);
  const [gaps, setGaps] = useState<SkillGap[]>(() => resultsPageData.peek()?.gaps ?? []);
  const [evidence, setEvidence] = useState<Evidence[]>(() => resultsPageData.peek()?.evidence ?? []);
  const [projects, setProjects] = useState<Project[]>(() => resultsPageData.peek()?.projects ?? []);
  const [githubRepos, setGithubRepos] = useState<GithubRepo[]>(() => resultsPageData.peek()?.githubRepos ?? []);
  const [assessable, setAssessable] = useState<AvailableAssessment[]>(() => resultsPageData.peek()?.assessable ?? []);
  const [activeAssessment, setActiveAssessment] = useState<AvailableAssessment | null>(null);
  const [loading, setLoading] = useState(() => !resultsPageData.peek());
  const [error, setError] = useState<string | null>(null);
  const [provenanceGap, setProvenanceGap] = useState<SkillGap | null>(null);
  const [overrideConfirm, setOverrideConfirm] = useState<SkillGap | null>(null);
  const [overriding, setOverriding] = useState(false);
  const [evidenceActionLoading, setEvidenceActionLoading] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [generatingRoadmap, setGeneratingRoadmap] = useState(false);
  const [showFormula, setShowFormula] = useState(false);
  const [navActive, setNavActive] = useState("overview");
  const location = useLocation();
  const hash = location.hash.slice(1);
  const focusView = FOCUS_VIEWS.includes(hash) ? hash : null;

  const roadmapData = useSyncExternalStore(subscribePageData, roadmapPageData.peek);

  const reload = useCallback(async (force = true) => {
    try {
      const data = await resultsPageData.fetch(force);
      setAnalysis(data.analysis);
      setGaps(data.gaps);
      setEvidence(data.evidence);
      setProjects(data.projects);
      setGithubRepos(data.githubRepos);
      setAssessable(data.assessable);
      setError(null);
    } catch (e) {
      // A failed background refresh keeps the last-seen results on screen
      if (!force && resultsPageData.peek()) return;
      const msg = e instanceof Error ? e.message : "Failed to load analysis";
      if (msg.includes("404") || msg.toLowerCase().includes("no analysis")) {
        setError("none");
      } else if (msg.includes("401")) {
        setError("Your session has expired. Log in again to see your analysis.");
      } else if (msg.includes("503")) {
        setError("Analysis tables aren’t set up. Run backend/supabase/005_skill_engine.sql in Supabase.");
      } else {
        setError("Your analysis couldn’t be loaded. Check your connection and try again.");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  // State starts from the last-seen data (see useState above); refresh it in the background
  useEffect(() => {
    // Fetching on open: state is only set after the request resolves
    // eslint-disable-next-line react-hooks/set-state-in-effect
    reload(false);
    roadmapPageData.fetch().catch(() => undefined);
  }, [reload]);

  const ready = !loading && !!analysis;

  // Sidebar links like #priority-gaps scroll within this page; focused views start at the top
  useEffect(() => {
    if (!ready) return;
    if (focusView) {
      window.scrollTo(0, 0);
    } else if (hash && document.getElementById(hash)) {
      scrollToSection(hash);
    }
    // location.key: clicking the same sidebar link again scrolls back to that section
  }, [ready, hash, focusView, location.key]);

  // Track which section is on screen, for the sidebar and the section bar
  useEffect(() => {
    if (!ready || focusView) {
      setActiveSection(null);
      return;
    }
    const sections = NAV.map((n) => document.getElementById(n.id)).filter((el): el is HTMLElement => !!el);
    let frame = 0;
    // The section whose heading has most recently passed a line a third of the way down the screen
    const update = () => {
      frame = 0;
      const line = window.innerHeight * 0.33;
      const atBottom = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4;
      let current = sections[0];
      for (const el of sections) if (el.getBoundingClientRect().top <= line) current = el;
      if (atBottom) current = sections[sections.length - 1];
      if (current) {
        setActiveSection(current.id);
        setNavActive(current.id);
      }
    };
    const onScroll = () => {
      if (!frame) frame = requestAnimationFrame(update);
    };
    // IntersectionObserver catches sections resizing (expanding rows) as well as scrolling
    const observer = new IntersectionObserver(onScroll, { threshold: [0, 1] });
    sections.forEach((el) => observer.observe(el));
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    update();
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      setActiveSection(null);
    };
  }, [ready, focusView]);

  // Keep the active chip in view in the phone section bar. Scroll only the bar sideways:
  // scrollIntoView would also nudge the page and interrupt a smooth scroll that's in progress.
  useEffect(() => {
    const bar = document.querySelector<HTMLElement>(".an-sectionbar");
    const chip = bar?.querySelector<HTMLElement>(`a[data-id="${navActive}"]`);
    if (!bar || !chip || bar.offsetParent === null) return;
    bar.scrollTo({ left: chip.offsetLeft - bar.clientWidth / 2 + chip.clientWidth / 2, behavior: "smooth" });
  }, [navActive]);

  const refreshAfterAssessment = useCallback(async () => {
    await reload();
  }, [reload]);

  const handleOverride = async (gap: SkillGap) => {
    setOverriding(true);
    try {
      await setSkillOverride(skillName(gap));
      setOverrideConfirm(null);
      await reload();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "That change couldn’t be saved. Try again.");
      setOverrideConfirm(null);
    } finally {
      setOverriding(false);
    }
  };

  // Source switches: the backend recalculates, then we reload the analysis
  const runSourceAction = async (id: string, action: () => Promise<unknown>) => {
    setEvidenceActionLoading(id);
    setActionError(null);
    try {
      await action();
      await reload();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "That change couldn’t be saved. Try again.");
    } finally {
      setEvidenceActionLoading(null);
    }
  };

  const handleGenerateRoadmap = async () => {
    if (!analysis) return;
    setGeneratingRoadmap(true);
    setActionError(null);
    try {
      const profile = profileData.peek() ?? (await profileData.fetch().catch(() => undefined));
      await generateRoadmap(analysis.target_role, profile?.hours_per_week);
      await roadmapPageData.fetch(true);
    } catch (e) {
      setActionError(e instanceof Error ? `Your roadmap couldn’t be built: ${e.message}` : "Your roadmap couldn’t be built.");
    } finally {
      setGeneratingRoadmap(false);
    }
  };

  const groups = useMemo(() => splitGaps(gaps), [gaps]);
  const coding = useMemo(() => codingPracticeData(evidence), [evidence]);

  const assessmentFor = useCallback(
    (g: SkillGap): AvailableAssessment | undefined => {
      const names = [g.skills?.display_name, g.skills?.canonical_name, g.canonical_name].filter(Boolean).map((n) => (n as string).toLowerCase());
      return assessable.find((a) => names.includes(a.skill.toLowerCase()) || names.includes(a.skill_key.toLowerCase()));
    },
    [assessable]
  );

  const hasRoadmap = !!roadmapData?.roadmap;
  const actions: GapActions = {
    targetRole: analysis?.target_role ?? "your target",
    assessmentFor,
    startAssessment: setActiveAssessment,
    openDetails: setProvenanceGap,
    requestOverride: setOverrideConfirm,
    roadmapFor: (g) => roadmapLinkFor(g, hasRoadmap, roadmapData?.weeks ?? []),
    generateRoadmap: roadmapData && !hasRoadmap ? handleGenerateRoadmap : undefined,
    generatingRoadmap,
  };

  /* ---------------- Loading / empty / error ---------------- */

  if (loading) {
    return (
      <div className="an">
        <div className="an__inner" aria-busy="true">
          <div className="an-skel an-skel--head" />
          <div className="an-skel an-skel--stats" />
          <div className="an-skel an-skel--block" />
          <p className="an-visually-hidden">Loading your analysis</p>
        </div>
      </div>
    );
  }

  if (error || !analysis) {
    const none = !error || error === "none";
    return (
      <div className="an">
        <div className="an__inner">
          <section className="an-state">
            <h1 className="an-state__title">{none ? "You haven’t run an analysis yet" : "Something went wrong"}</h1>
            <p>{none ? "Choose your target role, add some evidence and run your analysis. The results appear here." : error}</p>
            <div className="an-actions">
              {none ? (
                <Button asChild variant="primary"><Link to="/analysis">Start your analysis</Link></Button>
              ) : (
                <Button variant="primary" onClick={() => { setLoading(true); void reload(); }}>Try again</Button>
              )}
            </div>
          </section>
        </div>
      </div>
    );
  }

  const usage = sourceUsage(evidence, projects, githubRepos);
  const readiness = pct(analysis.readiness_score);
  const analysedOn = new Date(analysis.created_at).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });

  /* ---------------- Shared overlays ---------------- */

  const overlays = (
    <>
      {provenanceGap && (
        <div className="prov__overlay" onClick={() => setProvenanceGap(null)} role="dialog" aria-modal="true" aria-label={`Evidence details for ${skillName(provenanceGap)}`}>
          <div className="prov__drawer" onClick={(e) => e.stopPropagation()}>
            <div className="prov__header">
              <div>
                <div className="prov__eyebrow">Why this score?</div>
                <h3 className="prov__title">{skillName(provenanceGap)}</h3>
              </div>
              <button className="prov__close" onClick={() => setProvenanceGap(null)} aria-label="Close">×</button>
            </div>
            <div className="prov__body">
              <SkillEvidenceCard gap={provenanceGap} />
              <div className="prov__sources">
                <div style={{ marginTop: 12, padding: 10, background: "var(--paper-2)", border: "1px solid var(--line-strong)", borderRadius: 8 }}>
                  <h4 style={{ margin: "0 0 6px", fontSize: "0.90rem" }}>Why is this skill required for {analysis.target_role}?</h4>
                  <div style={{ fontSize: "0.82rem", color: "var(--muted)", display: "flex", flexDirection: "column", gap: 4 }}>
                    <div><strong>Source:</strong> {provenanceGap.requirement_source || provenanceGap.source || "Industry requirements"} {provenanceGap.requirement_source_url ? <a href={provenanceGap.requirement_source_url} target="_blank" rel="noreferrer" style={{ color: "var(--ok-ink)", wordBreak: "break-all" }}>{provenanceGap.requirement_source_url}</a> : null}</div>
                    {provenanceGap.requirement_source_version && <div><strong>Source version:</strong> {provenanceGap.requirement_source_version}</div>}
                    {provenanceGap.requirement_source_reference && <div><strong>Reference:</strong> {provenanceGap.requirement_source_reference}</div>}
                    {provenanceGap.requirement_role_relevance && <div><strong>Role relevance:</strong> {provenanceGap.requirement_role_relevance}</div>}
                    {provenanceGap.requirement_description && <div><strong>Description:</strong> {provenanceGap.requirement_description}</div>}
                    {provenanceGap.evidence_context && <div><strong>Evidence context:</strong> {provenanceGap.evidence_context}</div>}
                  </div>
                  <div style={{ fontSize: "0.72rem", color: "var(--muted-2)", fontStyle: "italic", marginTop: 8 }}>Industry-grounded role requirements based on O*NET/ESCO with INAURA mapping heuristics — not universally required.</div>
                </div>
              </div>
              <div className="prov__footer-note">
                Industry requirements tell us what is required. Evidence tells us what is demonstrated. An assessment tells us what you can directly demonstrate.
              </div>
            </div>
            <div className="prov__actions">
              <Button variant="secondary" size="md" onClick={() => setProvenanceGap(null)}>Close</Button>
              {!provenanceGap.is_overridden && !provenanceGap.is_portfolio && provenanceGap.evidence_state !== "no_evidence" && provenanceGap.evidence_state !== "user_override" && (
                <Button variant="secondary" size="md" onClick={() => { const g = provenanceGap; setProvenanceGap(null); setOverrideConfirm(g); }}>
                  I don't actually know this yet
                </Button>
              )}
            </div>
          </div>
        </div>
      )}

      {overrideConfirm && (
        <div className="prov__overlay" onClick={() => setOverrideConfirm(null)} role="dialog" aria-modal="true">
          <div className="prov__drawer" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 480 }}>
            <h3 style={{ margin: 0 }}>Set {skillName(overrideConfirm)} to 0%?</h3>
            <p style={{ marginTop: 8, fontSize: "0.92rem", color: "var(--muted)", lineHeight: 1.5 }}>
              This overrides the current estimate in future analyses. Your evidence and assessment history are kept. You can’t restore the previous estimate yourself, but new evidence or a new assessment can change the result.
            </p>
            <p style={{ fontSize: "0.85rem", color: "var(--muted-2)" }}>
              Current: {pct(overrideConfirm.current_proficiency)}%, required: {pct(overrideConfirm.required_level)}%
            </p>
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 16 }}>
              <Button variant="secondary" size="md" onClick={() => setOverrideConfirm(null)} disabled={overriding}>Cancel</Button>
              <Button variant="primary" size="md" onClick={() => handleOverride(overrideConfirm)} disabled={overriding}>{overriding ? "Updating…" : "Set to 0%"}</Button>
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
    </>
  );

  /* ---------------- Focused views from the Skill Assessment sidebar group ---------------- */

  if (focusView === "skill-assessments") {
    return (
      <div className="an">
        <div className="an__inner">
          <Link to="/analysis/results" className="an-link sa-back">← Full analysis</Link>

          <section className="an-sec an-overview" id="skill-assessments" aria-labelledby="h-assess">
            <div className="an-overview__head">
              <div>
                <h1 id="h-assess" className="an-overview__title">Skills you know</h1>
                <p className="an-overview__sub">Show INAURA what you can actually do. Every check you finish sharpens your skill gaps and your roadmap.</p>
              </div>
              <Button asChild variant="secondary"><Link to="/analysis">Update evidence</Link></Button>
            </div>

            {assessable.length > 0 ? (
              <SkillAssessmentLayers items={assessable} onStartKnowledge={(item) => setActiveAssessment(item)} onCompleted={refreshAfterAssessment} />
            ) : (
              <>
                <p className="an-empty">There’s nothing to validate yet. Add your evidence and run your analysis first — INAURA then suggests the skills worth proving.</p>
                <div className="an-actions">
                  <Button asChild variant="primary"><Link to="/analysis">Add evidence</Link></Button>
                </div>
              </>
            )}
          </section>

          {coding.cfInspection && (
            <section className="an-sec" aria-labelledby="h-cf">
              <header className="an-sec__head">
                <h2 id="h-cf">Codeforces performance</h2>
                <p>Verified from your Codeforces profile — it counts as evidence on its own, so there’s nothing to take here.</p>
              </header>
              <CodeforcesPanel data={coding} />
            </section>
          )}
        </div>
        {overlays}
      </div>
    );
  }

  if (focusView === "dsa") {
    return (
      <div className="an">
        <div className="an__inner">
          <Link to="/analysis/results" className="an-link sa-back">← Full analysis</Link>

          {/* Interactive Compulsory Questions & Pattern Checklist */}
          <DsaChecklist onProgressUpdate={() => void reload(true)} />

          {/* Connected LeetCode profile insights if available */}
          {coding.hasDsa && (
            <section className="an-sec" style={{ marginTop: "24px" }} aria-labelledby="h-lc-coverage">
              <header className="an-sec__head">
                <h2 id="h-lc-coverage">Connected LeetCode Profile Insights</h2>
                <p>Real-time submission analytics parsed from your verified LeetCode profile.</p>
              </header>
              <DsaCoverage data={coding} />
            </section>
          )}
        </div>
        {overlays}
      </div>
    );
  }

  /* ---------------- The single analysis page ---------------- */

  const topGap = groups.priority[0];
  const claimToProve = groups.evidence.find((g) => assessmentFor(g));
  const topLink = topGap ? actions.roadmapFor(topGap) : null;

  return (
    <div className="an">
      {/* Phones and tablets: the sidebar is hidden, so sections get a compact bar */}
      <nav className="an-sectionbar" aria-label="Analysis sections">
        {NAV.map((n) => (
          <a
            key={n.id}
            href={`#${n.id}`}
            data-id={n.id}
            className={navActive === n.id ? "is-active" : ""}
            aria-current={navActive === n.id ? "true" : undefined}
            onClick={(e) => {
              e.preventDefault();
              scrollToSection(n.id);
            }}
          >
            {n.label}
          </a>
        ))}
      </nav>

      <div className="an__inner">
        {actionError && (
          <div className="an-alert" role="alert">
            <span>{actionError}</span>
            <button type="button" className="an-link an-link--btn" onClick={() => setActionError(null)}>Dismiss</button>
          </div>
        )}

        {/* ---------- Overview ---------- */}
        <section id="overview" className="an-sec an-overview" aria-labelledby="an-title">
          <div className="an-overview__head">
            <div>
              <h1 id="an-title" className="an-overview__title">Your analysis</h1>
              <p className="an-overview__sub">Here’s what INAURA found about your career profile. Analysed {analysedOn}.</p>
            </div>
            <Button asChild variant="secondary"><Link to="/analysis">Update evidence or re-run</Link></Button>
          </div>

          <dl className="an-stats">
            <div className="an-stat">
              <dt>Target role</dt>
              <dd className="an-stat__role">{analysis.target_role}</dd>
            </div>
            <div className="an-stat an-stat--main">
              <dt>Career readiness</dt>
              <dd>
                <span className="an-stat__big an-num">{readiness}<span className="an-stat__unit">%</span></span>
                <button type="button" className="an-link an-link--btn" aria-expanded={showFormula} onClick={() => setShowFormula((s) => !s)}>
                  {showFormula ? "Hide" : "How is this calculated?"}
                </button>
              </dd>
            </div>
            <div className="an-stat">
              <dt>Evidence sources</dt>
              <dd><span className="an-stat__num an-num">{usage.kinds}</span> analysed</dd>
            </div>
            <div className="an-stat">
              <dt>Skills assessed</dt>
              <dd><span className="an-stat__num an-num">{analysis.assessment_count}</span>, {groups.priority.length} with gaps</dd>
            </div>
          </dl>

          {showFormula && (
            <div className="an-formula">
              <div className="an-formula__parts">
                {[
                  { label: "Skills", value: analysis.skill_component, weight: 45 },
                  { label: "Industry fit", value: analysis.industry_component, weight: 25 },
                  { label: "Evidence", value: analysis.evidence_component, weight: 30 },
                ].map((c) => (
                  <div key={c.label} className="an-formula__part">
                    <span>{c.label} <span className="an-faint">× {c.weight}%</span></span>
                    <span className="an-meter"><span style={{ width: `${pct(c.value)}%` }} /></span>
                    <span className="an-num">{pct(c.value)}%</span>
                  </div>
                ))}
              </div>
              <p className="an-note">
                {analysis.disclaimer ||
                  "Career readiness measures how well your verified evidence matches industry benchmarks for this role. It’s a development indicator, not a hiring probability."}
              </p>
            </div>
          )}

          <p className="an-insight">{headlineInsight(analysis, groups)}</p>
        </section>

        {/* ---------- Priority gaps ---------- */}
        <section id="priority-gaps" className="an-sec" aria-labelledby="h-priority">
          <header className="an-sec__head">
            <h2 id="h-priority">Priority gaps</h2>
            <p>Ranked by how far you are from the requirement, how much the role and interviews weigh it, and how sure INAURA is.</p>
          </header>
          <PriorityGaps gaps={groups.priority} actions={actions} />
        </section>

        {/* ---------- Evidence gaps ---------- */}
        <section id="evidence-gaps" className="an-sec" aria-labelledby="h-evidence">
          <header className="an-sec__head">
            <h2 id="h-evidence">Evidence gaps</h2>
            <p>Skills you claim or the role needs, where INAURA lacks independent proof. Missing proof isn’t the same as not knowing it.</p>
          </header>
          <EvidenceGaps gaps={groups.evidence} actions={actions} />
        </section>

        {/* ---------- Quadrants ---------- */}
        <section id="skill-quadrants" className="an-sec" aria-labelledby="h-quad">
          <header className="an-sec__head">
            <h2 id="h-quad">Skill quadrants</h2>
            <p>Each skill placed by how strong it looks and how confident INAURA is in that. Select a skill to see why.</p>
          </header>
          <SkillQuadrant skills={groups.target} actions={actions} />
        </section>

        {/* ---------- Skill overview ---------- */}
        <section id="skill-overview" className="an-sec" aria-labelledby="h-overview">
          <header className="an-sec__head">
            <h2 id="h-overview">Skill overview</h2>
            <p>What {analysis.target_role} roles require, and where you stand on each skill.</p>
          </header>
          <SkillOverview roleSkills={groups.target} secondary={groups.secondary} actions={actions} />
        </section>

        {/* ---------- Evidence sources ---------- */}
        <section id="evidence-sources" className="an-sec" aria-labelledby="h-sources">
          <header className="an-sec__head">
            <h2 id="h-sources">Evidence sources</h2>
            <p>What INAURA used to understand you, and control over what counts.</p>
          </header>
          <EvidenceSources
            evidence={evidence}
            projects={projects}
            repos={githubRepos}
            busyId={evidenceActionLoading}
            onToggleEvidence={(id, exclude, type) =>
              runSourceAction(id, () => (type === "evidence" ? setEvidenceExcluded(id, exclude) : setProjectExcluded(id, exclude)))
            }
            onToggleEvidenceAi={(id, ai, type) =>
              runSourceAction(id, () => (type === "evidence" ? setEvidenceAiAssisted(id, ai) : setProjectAiAssisted(id, ai)))
            }
            onToggleRepo={(name, exclude) => runSourceAction(name, () => setGithubRepoExcluded(name, exclude))}
            onToggleRepoAi={(name, ai) => runSourceAction(name, () => setGithubRepoAiAssisted(name, ai))}
          />
        </section>

        {/* ---------- Next steps ---------- */}
        <section id="next-steps" className="an-sec an-next" aria-labelledby="h-next">
          <header className="an-sec__head">
            <h2 id="h-next">Next steps</h2>
          </header>
          <ol className="an-next__list">
            <li>
              <span className="an-next__k">Close your biggest gap</span>
              {topGap ? (
                <>
                  <span className="an-next__v">{skillName(topGap)}</span>
                  <span className="an-note">
                    {topLink?.state === "planned"
                      ? `Planned for week ${topLink.week.week_number} of your roadmap.`
                      : topLink?.state === "missing"
                        ? "Not in your current roadmap yet."
                        : "Build a roadmap to plan it."}
                  </span>
                </>
              ) : (
                <span className="an-next__v">No open gaps</span>
              )}
            </li>
            <li>
              <span className="an-next__k">Prove a claimed skill</span>
              {claimToProve ? (
                <>
                  <span className="an-next__v">{skillName(claimToProve)}</span>
                  <button type="button" className="an-link an-link--btn" onClick={() => { const a = assessmentFor(claimToProve); if (a) setActiveAssessment(a); }}>
                    Take the assessment
                  </button>
                </>
              ) : (
                <span className="an-next__v">Nothing waiting</span>
              )}
            </li>
            <li>
              <span className="an-next__k">Follow your plan</span>
              <span className="an-next__v">{hasRoadmap ? "Weekly roadmap" : "No roadmap yet"}</span>
              {hasRoadmap ? (
                <Link to="/roadmap" className="an-link">Open roadmap</Link>
              ) : roadmapData ? (
                <button type="button" className="an-link an-link--btn" onClick={handleGenerateRoadmap} disabled={generatingRoadmap}>
                  {generatingRoadmap ? "Building…" : "Build my roadmap"}
                </button>
              ) : (
                <Link to="/roadmap" className="an-link">Go to roadmap</Link>
              )}
            </li>
          </ol>
          <p className="an-note">
            Want a deeper view of each skill? <Link to="/analysis/capabilities" className="an-link">Open the capability map</Link>.
          </p>
        </section>
      </div>

      {overlays}
    </div>
  );
}
