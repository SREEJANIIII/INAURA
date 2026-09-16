import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { getGaps, getLatestAnalysis, type AnalysisResult, type SkillGap } from "../services/analysis";
import { getProfile, type Profile } from "../services/profile";
import {
  generateRoadmap,
  getEvidenceSummary,
  getLatestRoadmap,
  getRoadmapWeeks,
  reassessRoadmap,
  updateRoadmapTask,
  type EvidenceSummary,
  type Roadmap,
  type RoadmapTask,
  type RoadmapWeek,
  type SkillPersonalizationExplanation,
} from "../services/roadmap";
import Button from "../components/ui/Button";
import "./Roadmap.css";

const STAGES: RoadmapTask["task_type"][] = ["learn", "practice", "build", "validate"];
const SOURCE_LABELS: Record<string, string> = {
  github: "GitHub",
  leetcode: "LeetCode",
  codeforces: "Codeforces",
  resume: "Resume",
  linkedin: "LinkedIn",
  kaggle: "Kaggle",
  projects: "Projects",
  certifications: "Certifications",
  assessment: "Assessment",
};

function formatDate(value?: string | null) {
  if (!value) return "Unavailable";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Unavailable"
    : date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function asPercent(value: number | null | undefined) {
  const numeric = Number(value ?? 0);
  const normalized = numeric <= 1 ? numeric * 100 : numeric;
  return Math.round(Math.max(0, Math.min(100, normalized)));
}

function priorityTone(priority: number) {
  if (priority >= 50) return "critical";
  if (priority >= 25) return "high";
  if (priority >= 10) return "medium";
  return "low";
}

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

function Metric({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="roadmap__metric">
      <div className="roadmap__label">{label}</div>
      <div className="roadmap__metric-value">{value}</div>
      {hint && <div className="roadmap__hint">{hint}</div>}
    </div>
  );
}

function ProgressBar({ value, className = "" }: { value: number; className?: string }) {
  const safeValue = Math.max(0, Math.min(100, value));
  return (
    <div className={`roadmap__progress-bar ${className}`} aria-label={`${Math.round(safeValue)}% complete`}>
      <div className="roadmap__progress-fill" style={{ width: `${safeValue}%` }} />
    </div>
  );
}

function EvidenceSummarySection({ summary }: { summary: EvidenceSummary | null }) {
  const analyzedSources = new Set((summary?.sources_analyzed ?? []).map((source) => source.source.toLowerCase()));
  const unavailableSources = new Set((summary?.sources_unavailable ?? []).map((source) => source.toLowerCase()));
  const availableSources = new Set((summary?.sources_available ?? []).map((source) => source.toLowerCase()));
  const snapshotStates = Object.values(summary?.latest_snapshot?.learner_skill_states ?? {});
  const sourceKeys = Array.from(new Set([
    ...Object.keys(SOURCE_LABELS),
    ...Array.from(analyzedSources),
    ...Array.from(unavailableSources),
  ]));
  const analyzedCount = analyzedSources.size;
  const totalSourceCount = new Set([...analyzedSources, ...unavailableSources, ...availableSources]).size;
  const sourceCoverage = totalSourceCount ? (analyzedCount / totalSourceCount) * 100 : 0;
  const skillCoverage = snapshotStates.length
    ? snapshotStates.reduce((total, state) => total + asPercent(state.evidence_coverage), 0) / snapshotStates.length
    : sourceCoverage;
  const confidence = snapshotStates.length
    ? snapshotStates.reduce((total, state) => total + asPercent(state.confidence), 0) / snapshotStates.length
    : 0;

  return (
    <section className="roadmap__section" aria-labelledby="evidence-summary-title">
      <div className="roadmap__section-heading">
        <div>
          <div className="roadmap__eyebrow">Evidence audit</div>
          <h2 id="evidence-summary-title">Evidence summary</h2>
          <p>Only sources INAURA actually accessed are marked as analyzed.</p>
        </div>
        <span className="roadmap__snapshot-date">Snapshot: {formatDate(summary?.latest_snapshot?.created_at)}</span>
      </div>

      <div className="roadmap__evidence-layout">
        <div className="roadmap__source-list">
          {sourceKeys.map((sourceKey) => {
            const isAnalyzed = analyzedSources.has(sourceKey);
            const isUnavailable = unavailableSources.has(sourceKey);
            const status = isAnalyzed ? "Analyzed" : isUnavailable ? "Not connected" : "Available";
            return (
              <div className={`roadmap__source-row ${isAnalyzed ? "roadmap__source-row--analyzed" : ""}`} key={sourceKey}>
                <span className="roadmap__source-icon" aria-hidden="true">{isAnalyzed ? "✓" : "○"}</span>
                <span>{SOURCE_LABELS[sourceKey] ?? sourceKey}</span>
                <span className="roadmap__source-status">{status}</span>
              </div>
            );
          })}
        </div>

        <div className="roadmap__evidence-metrics">
          <Metric label="Sources analyzed" value={`${analyzedCount}`} hint="Distinct sources used" />
          <Metric label="Sources unavailable" value={`${unavailableSources.size}`} hint="Not treated as evidence" />
          <Metric label="Evidence coverage" value={`${Math.round(skillCoverage)}%`} hint={`${Math.round(sourceCoverage)}% source coverage`} />
          <Metric label="Overall confidence" value={`${Math.round(confidence)}%`} hint="Across captured skill states" />
        </div>
      </div>
    </section>
  );
}

function PersonalizationExplanationCard({ explanation }: { explanation: SkillPersonalizationExplanation }) {
  const [showRaw, setShowRaw] = useState(false);

  return (
    <div className="roadmap__personalization-card">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "8px" }}>
        <div>
          <h4 style={{ margin: 0, fontSize: "0.95rem", color: "#0f172a" }}>
            Personalized Diagnostic: {explanation.skill_name}
          </h4>
          <p style={{ margin: "2px 0 0", fontSize: "0.8rem", color: "#64748b" }}>
            Current: {explanation.current_proficiency_pct}% | Required: {explanation.required_level_pct}% | Gap: {explanation.gap_pct}% | Confidence: {explanation.confidence_pct}%
          </p>
        </div>
        <button
          type="button"
          className="roadmap__gap-details-btn"
          onClick={() => setShowRaw((prev) => !prev)}
        >
          {showRaw ? "Hide summary block" : "View summary block"}
        </button>
      </div>

      {showRaw && (
        <pre className="roadmap__summary-pre">{explanation.readable_summary}</pre>
      )}

      {/* Demonstrated vs Missing Capabilities */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "12px", marginTop: "10px" }}>
        <div className="roadmap__cap-section">
          <div className="roadmap__cap-label" style={{ color: "#166534" }}>✓ What you already demonstrate</div>
          <div className="roadmap__cap-pills">
            {explanation.demonstrated_capabilities.length > 0 ? (
              explanation.demonstrated_capabilities.map((cap, i) => (
                <span key={i} className="roadmap__cap-pill roadmap__cap-pill--demonstrated">
                  ✓ {cap}
                </span>
              ))
            ) : (
              <span style={{ fontSize: "0.78rem", color: "#64748b" }}>Foundational concepts only</span>
            )}
          </div>
        </div>

        <div className="roadmap__cap-section">
          <div className="roadmap__cap-label" style={{ color: "#92400e" }}>⚠ Missing evidence (What to build next)</div>
          <div className="roadmap__cap-pills">
            {explanation.missing_capabilities.length > 0 ? (
              explanation.missing_capabilities.map((cap, i) => (
                <span key={i} className="roadmap__cap-pill roadmap__cap-pill--missing">
                  + {cap}
                </span>
              ))
            ) : (
              <span style={{ fontSize: "0.78rem", color: "#166534" }}>Advanced production validation</span>
            )}
          </div>
        </div>
      </div>

      {/* Metadata & Role Diagnostics */}
      <div className="roadmap__meta-grid">
        <div className="roadmap__meta-item">
          <strong>Confidence Rationale</strong>
          <span>{explanation.confidence_rationale}</span>
        </div>
        <div className="roadmap__meta-item">
          <strong>Prerequisites Status</strong>
          <span>{explanation.prerequisites_status}</span>
        </div>
        <div className="roadmap__meta-item">
          <strong>Role Importance</strong>
          <span>{explanation.importance_pct}% priority for {explanation.target_role}</span>
        </div>
        <div className="roadmap__meta-item">
          <strong>Time & Pacing</strong>
          <span>{explanation.allocated_hours}h allocated ({explanation.weekly_pacing})</span>
        </div>
      </div>

      {/* Smallest Learning Unit & Validation Criteria */}
      <div className="roadmap__trace-box">
        <div style={{ marginBottom: "5px" }}>
          <strong>Smallest useful learning unit:</strong> {explanation.smallest_learning_unit}
        </div>
        <div>
          <strong>Validation criteria:</strong> {explanation.validation_criteria}
        </div>
      </div>

      {/* Supporting Evidence Provenance */}
      {explanation.supporting_evidence.length > 0 && (
        <div className="roadmap__trace-box">
          <strong>Supporting evidence sources:</strong>
          <ul className="roadmap__trace-list">
            {explanation.supporting_evidence.map((ev, i) => (
              <li key={i}>{ev}</li>
            ))}
          </ul>
        </div>
      )}

      {/* The 5 Whys Grid */}
      <div className="roadmap__five-whys">
        <div className="roadmap__why-item">
          <div className="roadmap__why-header">❓ 1. Why am I learning this?</div>
          <p className="roadmap__why-text">{explanation.five_whys?.why_learning}</p>
        </div>
        <div className="roadmap__why-item">
          <div className="roadmap__why-header">⏱️ 2. Why now?</div>
          <p className="roadmap__why-text">{explanation.five_whys?.why_now}</p>
        </div>
        <div className="roadmap__why-item">
          <div className="roadmap__why-header">⌛ 3. Why this much time?</div>
          <p className="roadmap__why-text">{explanation.five_whys?.why_time}</p>
        </div>
        <div className="roadmap__why-item">
          <div className="roadmap__why-header">📚 4. Why this resource?</div>
          <p className="roadmap__why-text">{explanation.five_whys?.why_resource}</p>
        </div>
        <div className="roadmap__why-item" style={{ gridColumn: "1 / -1" }}>
          <div className="roadmap__why-header">🎯 5. How will INAURA know that I learned it?</div>
          <p className="roadmap__why-text">{explanation.five_whys?.how_validated}</p>
        </div>
      </div>
    </div>
  );
}

function findExplanation(gap: SkillGap, explanations: SkillPersonalizationExplanation[]): SkillPersonalizationExplanation | undefined {
  const cands = [
    gap.canonical_name,
    gap.skill,
    gap.skills?.canonical_name,
    gap.skills?.display_name,
  ]
    .filter(Boolean)
    .map((s) => s!.toLowerCase().replace(/[\s-]+/g, "_"));

  return explanations.find((exp) => {
    const expSlugs = [
      exp.canonical_name,
      exp.skill_slug,
      exp.skill_name,
    ]
      .filter(Boolean)
      .map((s) => s!.toLowerCase().replace(/[\s-]+/g, "_"));
    return cands.some((c) => expSlugs.includes(c));
  });
}

function SkillGapOverview({
  gaps,
  explanations = [],
}: {
  gaps: SkillGap[];
  explanations?: SkillPersonalizationExplanation[];
}) {
  const [expandedSkillId, setExpandedSkillId] = useState<string | null>(null);
  const sortedGaps = [...gaps].sort((a, b) => (b.priority_score ?? 0) - (a.priority_score ?? 0));
  return (
    <section className="roadmap__section" aria-labelledby="skill-gaps-title">
      <div className="roadmap__section-heading">
        <div>
          <div className="roadmap__eyebrow">What to focus on</div>
          <h2 id="skill-gaps-title">Skill gap overview</h2>
          <p>Prioritized from current evidence, role requirements, and confidence.</p>
        </div>
        <span className="roadmap__count-label">{sortedGaps.length} skill{sortedGaps.length === 1 ? "" : "s"}</span>
      </div>

      {sortedGaps.length === 0 ? (
        <div className="roadmap__empty-inline">No priority gaps were returned by the latest analysis.</div>
      ) : (
        <div className="roadmap__table-wrap">
          <table className="roadmap__gap-table">
            <thead>
              <tr>
                <th>Skill</th>
                <th>Current</th>
                <th>Required</th>
                <th>Gap</th>
                <th>Confidence</th>
                <th>Priority</th>
                <th>Evidence</th>
                <th>Diagnosis & Why</th>
              </tr>
            </thead>
            <tbody>
              {sortedGaps.map((gap) => {
                const priority = Math.round(gap.priority_score ?? gap.priority ?? 0);
                const skillName = gap.skill || gap.canonical_name || gap.skills?.display_name || "Unknown skill";
                const explanation = findExplanation(gap, explanations);
                const isExpanded = expandedSkillId === gap.id;
                return (
                  <Fragment key={gap.id}>
                    <tr>
                      <th scope="row">
                        <div className="roadmap__skill-name">{skillName}</div>
                        {gap.evidence_state_label && <div className="roadmap__table-note">{gap.evidence_state_label}</div>}
                      </th>
                      <td>{asPercent(gap.current_proficiency)}%</td>
                      <td>{asPercent(gap.required_level)}%</td>
                      <td className="roadmap__gap-value">{asPercent(gap.gap)}%</td>
                      <td>{asPercent(gap.confidence)}%</td>
                      <td><span className={`roadmap__priority roadmap__priority--${priorityTone(priority)}`}>{priority}</span></td>
                      <td>{gap.evidence_count ?? 0}</td>
                      <td>
                        {explanation ? (
                          <button
                            type="button"
                            className="roadmap__gap-details-btn"
                            onClick={() => setExpandedSkillId(isExpanded ? null : gap.id)}
                            aria-expanded={isExpanded}
                          >
                            {isExpanded ? "Hide Diagnosis" : "Why this skill?"}
                          </button>
                        ) : (
                          <span className="roadmap__muted">—</span>
                        )}
                      </td>
                    </tr>
                    {isExpanded && explanation && (
                      <tr className="roadmap__gap-card-row">
                        <td colSpan={8}>
                          <PersonalizationExplanationCard explanation={explanation} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

type TaskUpdate = {
  status?: RoadmapTask["status"];
  completion_percentage?: number;
  submission_url?: string;
  submission_notes?: string;
};

type TaskCardProps = {
  task: RoadmapTask;
  updating: boolean;
  expanded: boolean;
  proof: { url: string; notes: string };
  onToggleExpanded: () => void;
  onProofChange: (proof: { url: string; notes: string }) => void;
  onUpdate: (patch: TaskUpdate) => void;
};

function TaskCard({ task, updating, expanded, proof, onToggleExpanded, onProofChange, onUpdate }: TaskCardProps) {
  const isComplete = task.status === "completed" || task.completion_percentage >= 100;
  return (
    <article className={`roadmap__task roadmap__task--${task.task_type}`}>
      <div className="roadmap__task-head">
        <div className="roadmap__task-info">
          <div className="roadmap__task-badges">
            <span className={`roadmap__stage roadmap__stage--${task.task_type}`}>{task.task_type}</span>
            <span className="roadmap__task-skill">{task.skill_name}</span>
            <span className="roadmap__task-time">{task.estimated_minutes} min</span>
            {task.personalization_context && typeof task.personalization_context.primary_gap === "string" && (
              <span className="roadmap__task-targeting-badge">
                Focus: {String(task.personalization_context.primary_gap)}
              </span>
            )}
          </div>
          <h4 className="roadmap__task-title">{task.title}</h4>
          <p className="roadmap__task-desc">{task.description}</p>
          {task.why_this_task && <p className="roadmap__why"><strong>Why this task:</strong> {task.why_this_task}</p>}
        </div>
        <span className={`roadmap__status roadmap__status--${task.status}`}>{task.status.replace("_", " ")}</span>
      </div>

      <div className="roadmap__task-actions">
        <label className="roadmap__complete-control">
          <input
            type="checkbox"
            checked={isComplete}
            disabled={updating}
            onChange={(event) => onUpdate({
              status: event.target.checked ? "completed" : "in_progress",
              completion_percentage: event.target.checked ? 100 : Math.min(task.completion_percentage, 99),
            })}
          />
          <span>Mark complete</span>
        </label>
        <label className="roadmap__status-control">
          <span className="sr-only">Task status</span>
          <select
            value={task.status}
            disabled={updating}
            onChange={(event) => onUpdate({
              status: event.target.value as RoadmapTask["status"],
              completion_percentage: event.target.value === "completed" ? 100 : task.completion_percentage,
            })}
          >
            <option value="not_started">Not started</option>
            <option value="in_progress">In progress</option>
            <option value="completed">Completed</option>
            <option value="skipped">Skipped</option>
          </select>
        </label>
        <span className="roadmap__task-percent">{Math.round(task.completion_percentage)}%</span>
        <button type="button" className="roadmap__details-button" onClick={onToggleExpanded} aria-expanded={expanded}>
          {expanded ? "Hide details" : "Resources & validation"}
        </button>
      </div>
      <ProgressBar value={task.completion_percentage} />

      {expanded && (
        <div className="roadmap__task-details">
          <div className="roadmap__detail-grid">
            <div>
              <h5>Validation criteria</h5>
              <p>{task.validation_method || "Self-check"}</p>
            </div>
            <div>
              <h5>Generated evidence</h5>
              {task.evidence_generated ? (
                <pre className="roadmap__evidence-json">{JSON.stringify(task.evidence_generated, null, 2)}</pre>
              ) : (
                <p className="roadmap__muted">No evidence generated yet.</p>
              )}
            </div>
          </div>

          {task.resources.length > 0 && (
            <div className="roadmap__resource-block">
              <h5>Resources</h5>
              <div className="roadmap__resources">
                {task.resources.map((resource, index) => (
                  <a className="roadmap__resource" href={resource.url} target="_blank" rel="noreferrer" key={`${resource.url}-${index}`}>
                    <span>{resource.title}</span>
                    <small>{resource.provider || resource.type || "Open resource"}</small>
                  </a>
                ))}
              </div>
            </div>
          )}

          <div className="roadmap__evidence-form">
            <div>
              <h5>Attach generated evidence</h5>
              <p>Link a repository, submission, or artifact used to validate this task.</p>
            </div>
            <div className="roadmap__evidence-fields">
              <label>
                <span className="sr-only">Evidence URL</span>
                <input
                  type="url"
                  placeholder="https://github.com/you/project"
                  value={proof.url}
                  onChange={(event) => onProofChange({ ...proof, url: event.target.value })}
                />
              </label>
              <label>
                <span className="sr-only">Evidence notes</span>
                <input
                  type="text"
                  placeholder="What does this demonstrate?"
                  value={proof.notes}
                  onChange={(event) => onProofChange({ ...proof, notes: event.target.value })}
                />
              </label>
              <Button
                variant="secondary"
                size="sm"
                disabled={updating || (!proof.url.trim() && !proof.notes.trim())}
                onClick={() => onUpdate({
                  submission_url: proof.url.trim() || undefined,
                  submission_notes: proof.notes.trim() || undefined,
                  status: "completed",
                  completion_percentage: 100,
                })}
              >
                Save evidence
              </Button>
            </div>
          </div>
        </div>
      )}
    </article>
  );
}

type WeekContentProps = {
  week: RoadmapWeek;
  updating: string | null;
  expanded: Record<string, boolean>;
  proofs: Record<string, { url: string; notes: string }>;
  onToggleExpanded: (taskId: string) => void;
  onProofChange: (taskId: string, proof: { url: string; notes: string }) => void;
  onUpdateTask: (task: RoadmapTask, patch: TaskUpdate) => void;
};

function WeekContent({ week, updating, expanded, proofs, onToggleExpanded, onProofChange, onUpdateTask }: WeekContentProps) {
  return (
    <div className="roadmap__week-content">
      <div className="roadmap__week-heading">
        <div>
          <div className="roadmap__week-kicker">Week {week.week_number}</div>
          <h3>{week.title}</h3>
          <p>{week.objective}</p>
        </div>
        <div className="roadmap__week-time"><strong>{week.estimated_hours}h</strong><span>estimated time</span></div>
      </div>
      <div className="roadmap__week-meta">
        <span>{week.status.replace("_", " ")}</span>
        {week.start_date && <span>{formatDate(week.start_date)} – {formatDate(week.target_completion_date)}</span>}
        {(week.skills ?? []).map((skill) => <span className="roadmap__skill-tag" key={skill}>{skill}</span>)}
      </div>
      <div className="roadmap__week-progress-line">
        <span>{Math.round(week.completion_percentage)}% complete</span>
        <ProgressBar value={week.completion_percentage} />
      </div>

      <div className="roadmap__stage-list">
        {STAGES.map((stage) => {
          const tasks = (week.tasks ?? []).filter((task) => task.task_type === stage);
          return (
            <section className="roadmap__stage-section" key={stage} aria-labelledby={`${week.id}-${stage}`}>
              <div className="roadmap__stage-heading">
                <h4 id={`${week.id}-${stage}`}><span className={`roadmap__stage roadmap__stage--${stage}`}>{stage}</span></h4>
                <span>{tasks.length} task{tasks.length === 1 ? "" : "s"}</span>
              </div>
              {tasks.length > 0 ? tasks.map((task) => (
                <TaskCard
                  key={task.id}
                  task={task}
                  updating={updating === task.id}
                  expanded={Boolean(expanded[task.id])}
                  proof={proofs[task.id] ?? { url: "", notes: "" }}
                  onToggleExpanded={() => onToggleExpanded(task.id)}
                  onProofChange={(proof) => onProofChange(task.id, proof)}
                  onUpdate={(patch) => onUpdateTask(task, patch)}
                />
              )) : <p className="roadmap__empty-stage">No {stage} tasks planned for this week.</p>}
            </section>
          );
        })}
      </div>
    </div>
  );
}

export default function Roadmap() {
  const [roadmap, setRoadmap] = useState<Roadmap | null>(null);
  const [weeks, setWeeks] = useState<RoadmapWeek[]>([]);
  const [selectedWeekNum, setSelectedWeekNum] = useState(1);
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [evidenceSummary, setEvidenceSummary] = useState<EvidenceSummary | null>(null);
  const [skillGaps, setSkillGaps] = useState<SkillGap[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [reassessing, setReassessing] = useState(false);
  const [updating, setUpdating] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [proofs, setProofs] = useState<Record<string, { url: string; notes: string }>>({});
  const [showAdaptiveNotice, setShowAdaptiveNotice] = useState(false);

  const loadAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [prof, ana, evidence, gaps] = await Promise.all([
        getProfile().catch(() => null),
        getLatestAnalysis().catch(() => null),
        getEvidenceSummary().catch(() => null),
        getGaps().catch(() => [] as SkillGap[]),
      ]);
      setProfile(prof);
      setAnalysis(ana);
      setEvidenceSummary(evidence);
      setSkillGaps(gaps);

      try {
        const latest = await getLatestRoadmap();
        setRoadmap(latest);
        const loadedWeeks = await getRoadmapWeeks(latest.id);
        setWeeks(loadedWeeks);
        const preferredWeek = latest.current_week_index || loadedWeeks.find((week) => week.status === "current")?.week_number || loadedWeeks[0]?.week_number || 1;
        setSelectedWeekNum(preferredWeek);
      } catch (roadmapError) {
        const message = errorMessage(roadmapError, "");
        if (message.includes("503")) throw roadmapError;
        setRoadmap(null);
        setWeeks([]);
      }
    } catch (loadError) {
      const message = errorMessage(loadError, "Failed to load roadmap");
      if (message.includes("503")) setError("Roadmap tables not configured — run backend/supabase/022_adaptive_weekly_roadmap.sql");
      else if (message.includes("401")) setError("Session expired. Please log in again.");
      else setError(message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  const handleGenerate = async () => {
    if (!analysis) {
      setError("Run your INAURA analysis first to generate a personalized roadmap.");
      return;
    }
    if (!profile?.hours_per_week) {
      setError("Update your weekly availability to create a realistic timeline.");
      return;
    }
    setGenerating(true);
    setError(null);
    try {
      await generateRoadmap(analysis.target_role, profile.hours_per_week);
      await loadAll();
    } catch (generateError) {
      setError(errorMessage(generateError, "Failed to generate roadmap"));
    } finally {
      setGenerating(false);
    }
  };

  const handleAdaptiveReassess = async () => {
    if (!roadmap) return;
    setReassessing(true);
    setError(null);
    try {
      await reassessRoadmap({
        target_role: roadmap.target_role,
        adjust_hours_per_week: profile?.hours_per_week,
        mode: "compress",
      });
      setShowAdaptiveNotice(true);
      await loadAll();
    } catch (reassessError) {
      setError(errorMessage(reassessError, "Failed to update roadmap"));
    } finally {
      setReassessing(false);
    }
  };

  const handleUpdateTask = async (task: RoadmapTask, patch: TaskUpdate) => {
    setUpdating(task.id);
    setError(null);
    try {
      const updated = await updateRoadmapTask(task.id, patch);
      setWeeks((currentWeeks) => currentWeeks.map((week) => {
        if (week.id !== task.roadmap_week_id) return week;
        const updatedTasks = (week.tasks ?? []).map((item) => item.id === task.id ? updated : item);
        const completion = updatedTasks.length
          ? updatedTasks.reduce((total, item) => total + item.completion_percentage, 0) / updatedTasks.length
          : 0;
        return {
          ...week,
          tasks: updatedTasks,
          completion_percentage: completion,
          status: completion >= 100 ? "completed" : week.status === "locked" ? "locked" : "current",
        };
      }));
      const latest = await getLatestRoadmap().catch(() => null);
      if (latest) setRoadmap(latest);
    } catch (updateError) {
      setError(errorMessage(updateError, "Failed to update task"));
    } finally {
      setUpdating(null);
    }
  };

  const activeWeek = useMemo(
    () => weeks.find((week) => week.week_number === selectedWeekNum) ?? weeks[0] ?? null,
    [selectedWeekNum, weeks],
  );
  const progress = roadmap?.progress ?? 0;
  const totalWeeks = roadmap?.total_weeks ?? roadmap?.estimated_weeks ?? weeks.length;
  const hoursPerWeek = roadmap?.weekly_hours_budget ?? roadmap?.hours_per_week ?? profile?.hours_per_week;
  const adaptiveNotice = showAdaptiveNotice || Boolean((roadmap?.adaptive_rebalance_count ?? 0) > 0);

  if (loading) return <div className="roadmap"><div className="container roadmap__loading">Loading your INAURA weekly roadmap…</div></div>;

  return (
    <div className="roadmap">
      <header className="roadmap__header">
        <div className="container">
          <Link to="/analysis/results" className="roadmap__back">← Back to Analysis Results</Link>
          <div className="roadmap__eyebrow roadmap__eyebrow--header">INAURA Evidence-Driven Adaptive Roadmap</div>
          <h1 className="roadmap__title">{roadmap?.title || "Personalized Weekly Roadmap"}</h1>
          <p className="roadmap__subtitle">A focused weekly plan built from your audited evidence and target role requirements.</p>
          <div className="roadmap__header-meta">
            <span>Target role: <strong>{roadmap?.target_role || analysis?.target_role || "Not set"}</strong></span>
            <span>Generated: {formatDate(roadmap?.created_at)}</span>
            <span>Evidence snapshot: {formatDate(evidenceSummary?.latest_snapshot?.created_at)}</span>
          </div>
        </div>
      </header>

      <main className="container roadmap__main">
        {error && <div className="roadmap__error" role="alert">{error}</div>}

        {adaptiveNotice && roadmap && (
          <div className="roadmap__adaptive-alert" role="status">
            <span aria-hidden="true">⚡</span>
            <div><strong>Your roadmap was updated based on new evidence.</strong><span> Completed work is preserved; only future work is adjusted.</span></div>
          </div>
        )}

        <section className="roadmap__card roadmap__card--primary" aria-label="Roadmap overview">
          <div className="roadmap__overview-grid">
            <Metric label="Target role" value={roadmap?.target_role || analysis?.target_role || "Not set"} />
            <Metric label="Total weeks" value={totalWeeks ? `${totalWeeks}` : "—"} />
            <Metric label="Hours / week" value={hoursPerWeek ? `${hoursPerWeek}h` : "—"} />
            <Metric label="Estimated hours" value={roadmap ? `${roadmap.total_estimated_hours}h` : "—"} />
            <Metric label="Generated" value={formatDate(roadmap?.created_at)} />
            <Metric label="Evidence snapshot" value={formatDate(evidenceSummary?.latest_snapshot?.created_at)} />
          </div>
          {roadmap && <div className="roadmap__overall-progress"><span>Overall progress</span><strong>{Math.round(progress)}%</strong><ProgressBar value={progress} /></div>}
        </section>

        <EvidenceSummarySection summary={evidenceSummary} />
        <SkillGapOverview gaps={skillGaps} explanations={roadmap?.skill_explanations} />

        {!roadmap ? (
          <section className="roadmap__empty">
            <h2>Generate your evidence-driven roadmap</h2>
            <p>{analysis ? "Turn your latest skill gaps into a realistic week-by-week plan." : "Run your INAURA analysis first, then return here to generate your plan."}</p>
            <Button variant="primary" size="lg" onClick={handleGenerate} disabled={generating || !analysis || !profile?.hours_per_week}>
              {generating ? "Assembling weekly plan…" : "Generate weekly roadmap"}
            </Button>
            {!profile?.hours_per_week && <div className="roadmap__empty-note">Set your hours per week in your profile before generating.</div>}
          </section>
        ) : (
          <section className="roadmap__section roadmap__weekly-section" aria-labelledby="weekly-roadmap-title">
            <div className="roadmap__section-heading roadmap__section-heading--weekly">
              <div>
                <div className="roadmap__eyebrow">Your plan</div>
                <h2 id="weekly-roadmap-title">Weekly roadmap</h2>
                <p>Complete tasks in order. Each week builds toward validated evidence.</p>
              </div>
              <Button variant="secondary" size="sm" onClick={handleAdaptiveReassess} disabled={reassessing || generating}>
                {reassessing ? "Updating…" : "Update with latest evidence"}
              </Button>
            </div>

            {weeks.length > 0 ? (
              <>
                <div className="roadmap__week-navigation" aria-label="Week navigation">
                  <Button variant="secondary" size="sm" disabled={selectedWeekNum <= weeks[0].week_number} onClick={() => setSelectedWeekNum((week) => Math.max(weeks[0].week_number, week - 1))}>← Previous week</Button>
                  <div className="roadmap__current-week">Week {activeWeek?.week_number ?? selectedWeekNum} of {weeks.length}</div>
                  <Button variant="secondary" size="sm" disabled={selectedWeekNum >= weeks[weeks.length - 1].week_number} onClick={() => setSelectedWeekNum((week) => Math.min(weeks[weeks.length - 1].week_number, week + 1))}>Next week →</Button>
                </div>
                <div className="roadmap__week-tabs" role="tablist" aria-label="Roadmap weeks">
                  {weeks.map((week) => (
                    <button
                      key={week.id}
                      type="button"
                      role="tab"
                      aria-selected={activeWeek?.id === week.id}
                      className={`roadmap__week-tab ${activeWeek?.id === week.id ? "roadmap__week-tab--active" : ""} ${week.status === "completed" ? "roadmap__week-tab--complete" : ""}`}
                      onClick={() => setSelectedWeekNum(week.week_number)}
                    >
                      <span>Week {week.week_number}</span><small>{Math.round(week.completion_percentage)}%</small>
                    </button>
                  ))}
                </div>
                {activeWeek && (
                  <WeekContent
                    week={activeWeek}
                    updating={updating}
                    expanded={expanded}
                    proofs={proofs}
                    onToggleExpanded={(taskId) => setExpanded((current) => ({ ...current, [taskId]: !current[taskId] }))}
                    onProofChange={(taskId, proof) => setProofs((current) => ({ ...current, [taskId]: proof }))}
                    onUpdateTask={handleUpdateTask}
                  />
                )}
              </>
            ) : (
              <div className="roadmap__empty-inline">No weekly tasks are available yet. Update the roadmap to generate the current schedule.</div>
            )}
          </section>
        )}
      </main>
    </div>
  );
}
