/* eslint-disable react-hooks/set-state-in-effect */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { getLatestAnalysis, type AnalysisResult } from "../services/analysis";
import { getProfile, type Profile } from "../services/profile";
import {
  generateRoadmap,
  getLatestRoadmap,
  getRoadmapWeeks,
  reassessRoadmap,
  updateRoadmapTask,
  type Roadmap,
  type RoadmapTask,
  type RoadmapWeek,
} from "../services/roadmap";
import Button from "../components/ui/Button";
import "./Roadmap.css";

const STAGES: RoadmapTask["task_type"][] = ["learn", "practice", "build", "validate"];

function formatDate(value?: string | null) {
  if (!value) return "Unavailable";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Unavailable"
    : date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
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

type TaskUpdate = {
  status?: RoadmapTask["status"];
  completion_percentage?: number;
};

type TaskCardProps = {
  task: RoadmapTask;
  updating: boolean;
  expanded: boolean;
  onToggleExpanded: () => void;
  onUpdate: (patch: TaskUpdate) => void;
};

function TaskCard({ task, updating, expanded, onToggleExpanded, onUpdate }: TaskCardProps) {
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

        </div>
      )}
    </article>
  );
}

type WeekContentProps = {
  week: RoadmapWeek;
  updating: string | null;
  expanded: Record<string, boolean>;
  onToggleExpanded: (taskId: string) => void;
  onUpdateTask: (task: RoadmapTask, patch: TaskUpdate) => void;
};

function WeekContent({ week, updating, expanded, onToggleExpanded, onUpdateTask }: WeekContentProps) {
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
                  onToggleExpanded={() => onToggleExpanded(task.id)}
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
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [reassessing, setReassessing] = useState(false);
  const [updating, setUpdating] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [showAdaptiveNotice, setShowAdaptiveNotice] = useState(false);

  const loadAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [prof, ana] = await Promise.all([
        getProfile().catch(() => null),
        getLatestAnalysis().catch(() => null),
      ]);
      setProfile(prof);
      setAnalysis(ana);

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
    if (!profile?.hours_per_week) {
      setError("Update your weekly availability to create a realistic timeline.");
      return;
    }
    setGenerating(true);
    setError(null);
    try {
      const generated = await generateRoadmap(analysis?.target_role, profile.hours_per_week);
      setRoadmap(generated);
      if (generated.weeks?.length) {
        setWeeks(generated.weeks);
        setSelectedWeekNum(generated.current_week_index || generated.weeks[0].week_number);
      }
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
          <div className="roadmap__eyebrow roadmap__eyebrow--header">INAURA Adaptive Learning Plan</div>
          <h1 className="roadmap__title">{roadmap?.title || "Personalized Weekly Roadmap"}</h1>
          <p className="roadmap__subtitle">A focused week-by-week plan built around the skills you need for your target role.</p>
          <div className="roadmap__header-meta">
            <span>Target role: <strong>{roadmap?.target_role || analysis?.target_role || "Not set"}</strong></span>
            <span>Generated: {formatDate(roadmap?.created_at)}</span>
          </div>
        </div>
      </header>

      <main className="container roadmap__main">
        {error && <div className="roadmap__error" role="alert">{error}</div>}

        {adaptiveNotice && roadmap && (
          <div className="roadmap__adaptive-alert" role="status">
            <span aria-hidden="true">⚡</span>
            <div><strong>Your roadmap was updated.</strong><span> Completed work is preserved; only future work is adjusted.</span></div>
          </div>
        )}

        <section className="roadmap__card roadmap__card--primary" aria-label="Roadmap overview">
          <div className="roadmap__overview-grid">
            <Metric label="Target role" value={roadmap?.target_role || analysis?.target_role || "Not set"} />
            <Metric label="Total weeks" value={totalWeeks ? `${totalWeeks}` : "—"} />
            <Metric label="Hours / week" value={hoursPerWeek ? `${hoursPerWeek}h` : "—"} />
            <Metric label="Estimated hours" value={roadmap ? `${roadmap.total_estimated_hours}h` : "—"} />
            <Metric label="Generated" value={formatDate(roadmap?.created_at)} />
          </div>
          {roadmap && <div className="roadmap__overall-progress"><span>Overall progress</span><strong>{Math.round(progress)}%</strong><ProgressBar value={progress} /></div>}
        </section>

        {!roadmap ? (
          <section className="roadmap__empty">
            <h2>Generate your personalized roadmap</h2>
            <p>{analysis ? "Turn your latest skill gaps into a realistic week-by-week plan." : "Your latest analysis will be used to build a realistic week-by-week plan."}</p>
            <Button variant="primary" size="lg" onClick={handleGenerate} disabled={generating || !profile?.hours_per_week}>
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
                <p>Complete tasks in order. Each week builds toward practical, job-ready capability.</p>
              </div>
              <Button variant="secondary" size="sm" onClick={handleAdaptiveReassess} disabled={reassessing || generating}>
                {reassessing ? "Updating…" : "Refresh your plan"}
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
                    onToggleExpanded={(taskId) => setExpanded((current) => ({ ...current, [taskId]: !current[taskId] }))}
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
