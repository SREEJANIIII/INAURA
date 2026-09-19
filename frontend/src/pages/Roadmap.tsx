/* eslint-disable react-hooks/set-state-in-effect */
import { useCallback, useEffect, useLayoutEffect, useMemo, useState, useSyncExternalStore } from "react";
import { Link } from "react-router-dom";
import { type AnalysisResult } from "../services/analysis";
import { type Profile } from "../services/profile";
import {
  generateRoadmap,
  getLatestRoadmap,
  reassessRoadmap,
  updateRoadmapTask,
  type Roadmap,
  type RoadmapTask,
  type RoadmapWeek,
} from "../services/roadmap";
import { roadmapPageData } from "../lib/pageData";
import { getRoleSync, resetRoleSync, subscribeRoleSync } from "../lib/roleSync";
import Button from "@/components/ui/app-button";
import AssessmentModal from "../components/assessment/AssessmentModal";

type RoadmapPageData = NonNullable<ReturnType<typeof roadmapPageData.peek>>;
import "./Roadmap.css";

export type RoadmapPhase = {
  phaseNumber: number;
  title: string;
  shortTitle: string;
  description: string;
  startWeek: number;
  endWeek: number;
  completionPercentage: number;
  isCompleted: boolean;
};

const STAGES: RoadmapTask["task_type"][] = ["learn", "practice", "build", "validate"];

const STAGE_LABEL: Record<RoadmapTask["task_type"], string> = {
  learn: "Learn",
  practice: "Practice",
  build: "Build",
  validate: "Validate",
};

const STAGE_HINT: Record<RoadmapTask["task_type"], string> = {
  learn: "Understand the idea",
  practice: "Use it on small problems",
  build: "Put it into something real",
  validate: "Prove you can do it",
};

const TASK_STATUS_LABEL: Record<RoadmapTask["status"], string> = {
  not_started: "Not started",
  in_progress: "In progress",
  completed: "Done",
  skipped: "Skipped",
};

const WEEK_STATUS_LABEL: Record<RoadmapWeek["status"], string> = {
  locked: "Not started yet",
  current: "In progress",
  completed: "Completed",
  behind_schedule: "Behind schedule",
};

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

/** Minutes as something readable: 45 min, 1h 30m, 2h */
function readableMinutes(minutes: number) {
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours}h ${rest}m` : `${hours}h`;
}

function Meter({ value, tone = "accent" }: { value: number; tone?: "accent" | "done" }) {
  const safe = Math.max(0, Math.min(100, value));
  return (
    <span className={`rm-meter rm-meter--${tone}`} aria-hidden="true">
      <span style={{ width: `${safe}%` }} />
    </span>
  );
}

const Tick = () => (
  <svg className="rm-tick" width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
    <path d="M2 6.2 4.6 8.8 10 3.4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

type TaskUpdate = {
  status?: RoadmapTask["status"];
  completion_percentage?: number;
};

type TaskRowProps = {
  task: RoadmapTask;
  updating: boolean;
  expanded: boolean;
  onToggleExpanded: () => void;
  onUpdate: (patch: TaskUpdate) => void;
  onLaunchAssessment: (skillName: string, task: RoadmapTask) => void;
};

function TaskRow({ task, updating, expanded, onToggleExpanded, onUpdate, onLaunchAssessment }: TaskRowProps) {
  const done = task.status === "completed" || task.completion_percentage >= 100;
  const partway = !done && task.completion_percentage > 0;
  const focus = task.personalization_context && typeof task.personalization_context.primary_gap === "string"
    ? String(task.personalization_context.primary_gap)
    : null;

  return (
    <li className={`rm-task${expanded ? " is-open" : ""}${done ? " is-done" : ""}`}>
      <div className="rm-task__row">
        <label className="rm-check" title={done ? "Mark as not done" : "Mark as done"}>
          <input
            type="checkbox"
            checked={done}
            disabled={updating}
            onChange={(event) => onUpdate({
              status: event.target.checked ? "completed" : "in_progress",
              completion_percentage: event.target.checked ? 100 : Math.min(task.completion_percentage, 99),
            })}
          />
          <span className="sr-only">Mark “{task.title}” complete</span>
        </label>

        <button type="button" className="rm-task__main" aria-expanded={expanded} onClick={onToggleExpanded}>
          <span className="rm-task__title">{task.title}</span>
          <span className="rm-task__meta">
            <span className="rm-task__skill">{task.skill_name}</span>
            <span>{readableMinutes(task.estimated_minutes)}</span>
            {focus && <span>Focus: {focus}</span>}
            {partway && <span>{Math.round(task.completion_percentage)}% done</span>}
          </span>
        </button>

        <span className={`rm-state rm-state--${task.status}`}>
          {updating ? "Saving…" : TASK_STATUS_LABEL[task.status]}
        </span>
      </div>

      {partway && <Meter value={task.completion_percentage} />}

      {expanded && (
        <div className="rm-task__detail">
          {task.description && <p className="rm-task__desc">{task.description}</p>}

          {task.why_this_task && (
            <p className="rm-why">
              <span>Why this task</span>
              {task.why_this_task}
            </p>
          )}

          <dl className="rm-facts">
            <div>
              <dt>How you’ll know it’s done</dt>
              <dd>{task.validation_method || "Check it yourself against the task description."}</dd>
            </div>
            <div>
              <dt>Status</dt>
              <dd>
                <select
                  className="rm-select"
                  value={task.status}
                  disabled={updating}
                  onChange={(event) => onUpdate({
                    status: event.target.value as RoadmapTask["status"],
                    completion_percentage: event.target.value === "completed" ? 100 : task.completion_percentage,
                  })}
                  aria-label={`Status of ${task.title}`}
                >
                  <option value="not_started">Not started</option>
                  <option value="in_progress">In progress</option>
                  <option value="completed">Done</option>
                  <option value="skipped">Skipped</option>
                </select>
              </dd>
            </div>
          </dl>

          {task.resources.length > 0 && (
            <div className="rm-res">
              <h4>Resources</h4>
              <ul>
                {task.resources.map((resource, index) => (
                  <li key={`${resource.url}-${index}`}>
                    <a href={resource.url} target="_blank" rel="noreferrer">
                      <span className="rm-res__title">{resource.title}</span>
                      <span className="rm-res__from">{resource.provider || resource.type || "Open resource"}</span>
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="rm-task__actions">
            {task.task_type === "validate" && (
              <>
                <Button
                  size="sm"
                  variant="primary"
                  disabled={updating || done}
                  onClick={() => onLaunchAssessment(task.skill_name, task)}
                >
                  Take {task.skill_name} Assessment
                </Button>
                <Button asChild size="sm" variant="ghost">
                  <Link to="/interview">Mock Interview Practice →</Link>
                </Button>
                <span className="rm-task__action-hint">
                  Passing this assessment marks this milestone complete automatically.
                </span>
              </>
            )}
            {task.task_type === "build" && (
              <>
                <Button asChild size="sm" variant="secondary">
                  <Link to="/analysis">Add Project Evidence →</Link>
                </Button>
                <span className="rm-task__action-hint">
                  Link a GitHub repo or deliverable to verify this build milestone.
                </span>
              </>
            )}
            {task.task_type === "practice" && task.resources.length > 0 && (
              <Button asChild size="sm" variant="secondary">
                <a href={task.resources[0].url} target="_blank" rel="noreferrer">
                  Open Practice Drill ({task.resources[0].provider || "Practice"}) ↗
                </a>
              </Button>
            )}
            {task.task_type === "learn" && task.resources.length > 0 && (
              <Button asChild size="sm" variant="ghost">
                <a href={task.resources[0].url} target="_blank" rel="noreferrer">
                  Study: {task.resources[0].title} ↗
                </a>
              </Button>
            )}
          </div>
        </div>
      )}
    </li>
  );
}

type WeekPanelProps = {
  week: RoadmapWeek;
  weekCount: number;
  currentPhase?: RoadmapPhase | null;
  updating: string | null;
  expanded: Record<string, boolean>;
  onToggleExpanded: (taskId: string) => void;
  onUpdateTask: (task: RoadmapTask, patch: TaskUpdate) => void;
  onLaunchAssessment: (skillName: string, task: RoadmapTask) => void;
  onStep: (delta: number) => void;
  canPrev: boolean;
  canNext: boolean;
};

function WeekPanel({
  week,
  weekCount,
  currentPhase,
  updating,
  expanded,
  onToggleExpanded,
  onUpdateTask,
  onLaunchAssessment,
  onStep,
  canPrev,
  canNext,
}: WeekPanelProps) {
  const tasks = week.tasks ?? [];
  const doneCount = tasks.filter((t) => t.status === "completed" || t.completion_percentage >= 100).length;
  const remainingMinutes = tasks
    .filter((t) => t.status !== "completed" && t.status !== "skipped")
    .reduce((total, t) => total + t.estimated_minutes, 0);

  return (
    <section className="rm-panel" aria-labelledby="rm-week-title">
      <header className="rm-panel__head">
        <div>
          <p className="rm-eyebrow">
            Week {week.week_number} of {weekCount}
            {currentPhase && <span className="rm-phase-tag">{currentPhase.shortTitle}</span>}
            <span className={`rm-wstate rm-wstate--${week.status}`}>{WEEK_STATUS_LABEL[week.status]}</span>
            {week.start_date && <span className="rm-faint">{formatDate(week.start_date)} – {formatDate(week.target_completion_date)}</span>}
          </p>
          <h2 id="rm-week-title">{week.title}</h2>
          {week.objective && <p className="rm-obj">{week.objective}</p>}
        </div>
        <div className="rm-panel__time">
          <strong className="rm-num">{week.estimated_hours}h</strong>
          <span>planned this week</span>
          {remainingMinutes > 0 && <span className="rm-faint">{readableMinutes(remainingMinutes)} left</span>}
        </div>
      </header>

      <div className="rm-panel__progress">
        <Meter value={week.completion_percentage} tone={week.completion_percentage >= 100 ? "done" : "accent"} />
        <span className="rm-num">
          {doneCount} of {tasks.length} task{tasks.length === 1 ? "" : "s"} done · {Math.round(week.completion_percentage)}%
        </span>
      </div>

      {(week.skills ?? []).length > 0 && (
        <ul className="rm-tags">
          {(week.skills ?? []).map((skill) => (
            <li key={skill} className="rm-tag">{skill}</li>
          ))}
        </ul>
      )}

      {tasks.length === 0 ? (
        <p className="rm-empty">This week has no tasks yet. Refresh your plan to fill it in.</p>
      ) : (
        STAGES.map((stage) => {
          const stageTasks = tasks.filter((task) => task.task_type === stage);
          if (stageTasks.length === 0) return null;
          const stageMinutes = stageTasks.reduce((total, t) => total + t.estimated_minutes, 0);
          return (
            <section className="rm-stage" key={stage} aria-labelledby={`${week.id}-${stage}`}>
              <header className="rm-stage__head">
                <h3 id={`${week.id}-${stage}`}>
                  <span className={`rm-dot rm-dot--${stage}`} aria-hidden="true" />
                  {STAGE_LABEL[stage]}
                  <span className="rm-faint">{STAGE_HINT[stage]}</span>
                </h3>
                <span className="rm-faint rm-num">
                  {stageTasks.length} task{stageTasks.length === 1 ? "" : "s"} · {readableMinutes(stageMinutes)}
                </span>
              </header>
              <ul className="rm-tasks">
                {stageTasks.map((task) => (
                  <TaskRow
                    key={task.id}
                    task={task}
                    updating={updating === task.id}
                    expanded={Boolean(expanded[task.id])}
                    onToggleExpanded={() => onToggleExpanded(task.id)}
                    onUpdate={(patch) => onUpdateTask(task, patch)}
                    onLaunchAssessment={onLaunchAssessment}
                  />
                ))}
              </ul>
            </section>
          );
        })
      )}

      <div className="rm-panel__foot">
        <Button variant="ghost" disabled={!canPrev} onClick={() => onStep(-1)}>
          ← Previous week
        </Button>
        <Button variant="secondary" disabled={!canNext} onClick={() => onStep(1)}>
          Next week →
        </Button>
      </div>
    </section>
  );
}

export default function Roadmap() {
  const [roadmap, setRoadmap] = useState<Roadmap | null>(null);
  const [weeks, setWeeks] = useState<RoadmapWeek[]>([]);
  const [selectedWeekNum, setSelectedWeekNum] = useState(1);
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [loading, setLoading] = useState(() => !roadmapPageData.peek());
  const [error, setError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [reassessing, setReassessing] = useState(false);
  const [updating, setUpdating] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [showAdaptiveNotice, setShowAdaptiveNotice] = useState(false);
  const [assessingTarget, setAssessingTarget] = useState<{ skillName: string; task: RoadmapTask } | null>(null);

  const applyData = useCallback((data: RoadmapPageData) => {
    setProfile(data.profile);
    setAnalysis(data.analysis);
    setRoadmap(data.roadmap);
    setWeeks(data.weeks);
    if (data.roadmap) {
      const preferredWeek = data.roadmap.current_week_index || data.weeks.find((week) => week.status === "current")?.week_number || data.weeks[0]?.week_number || 1;
      setSelectedWeekNum(preferredWeek);
    }
  }, []);

  const loadAll = useCallback(async (force = true) => {
    // Only show the full-page loader when there's nothing on screen yet
    if (!roadmapPageData.peek()) setLoading(true);
    setError(null);
    try {
      applyData(await roadmapPageData.fetch(force));
    } catch (loadError) {
      // A failed background refresh keeps the last-seen roadmap on screen
      if (!force && roadmapPageData.peek()) return;
      const message = errorMessage(loadError, "Failed to load roadmap");
      if (message.includes("503")) setError("Roadmap tables not configured — run backend/supabase/022_adaptive_weekly_roadmap.sql");
      else if (message.includes("401")) setError("Session expired. Please log in again.");
      else setError(message);
    } finally {
      setLoading(false);
    }
  }, [applyData]);

  // Show last-seen data before the first paint, then refresh in the background
  useLayoutEffect(() => {
    const cachedData = roadmapPageData.peek();
    if (cachedData) applyData(cachedData);
    void loadAll(false);
  }, [applyData, loadAll]);

  // A career change rebuilds the plan in the background; show the new one as soon as it lands
  const roleSync = useSyncExternalStore(subscribeRoleSync, getRoleSync);
  const rebuilding = roleSync.stage === "analysing" || roleSync.stage === "building";
  useEffect(() => {
    if (roleSync.stage !== "done") return;
    const rebuilt = roadmapPageData.peek();
    if (rebuilt) applyData(rebuilt);
  }, [roleSync.stage, applyData]);

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
      // Refresh the remembered copy so reopening Roadmap shows this change
      roadmapPageData.fetch(true).catch(() => undefined);
    } catch (updateError) {
      setError(errorMessage(updateError, "Failed to update task"));
    } finally {
      setUpdating(null);
    }
  };

  const activeIndex = useMemo(() => {
    const found = weeks.findIndex((week) => week.week_number === selectedWeekNum);
    return found === -1 ? 0 : found;
  }, [selectedWeekNum, weeks]);
  const activeWeek = weeks[activeIndex] ?? null;

  const phases = useMemo<RoadmapPhase[]>(() => {
    if (weeks.length === 0) return [];
    const milestones = roadmap?.milestones ?? [];
    const phaseCount = milestones.length > 0 ? milestones.length : Math.min(4, Math.max(1, Math.ceil(weeks.length / 4)));
    const perPhase = Math.ceil(weeks.length / phaseCount);

    return Array.from({ length: phaseCount }, (_, i) => {
      const phaseStartIdx = i * perPhase;
      const phaseEndIdx = Math.min((i + 1) * perPhase, weeks.length);
      const phaseWeeks = weeks.slice(phaseStartIdx, phaseEndIdx);
      if (phaseWeeks.length === 0) return null;

      const startWeek = phaseWeeks[0].week_number;
      const endWeek = phaseWeeks[phaseWeeks.length - 1].week_number;
      const totalPct = phaseWeeks.reduce((acc, w) => acc + w.completion_percentage, 0);
      const avgPct = Math.round(totalPct / phaseWeeks.length);
      const milestone = milestones[i];

      const fullTitle = milestone?.title || `Phase ${i + 1}: Module ${i + 1}`;
      let shortTitle = `Phase ${i + 1}`;
      if (fullTitle.includes(":")) {
        const parts = fullTitle.split(":");
        const namePart = parts[1].trim();
        const shortName = namePart.split("&")[0].trim().split(" ")[0] || namePart;
        shortTitle = `${parts[0].trim()}: ${shortName}`;
      }

      return {
        phaseNumber: i + 1,
        title: fullTitle,
        shortTitle,
        description: milestone?.description || "",
        startWeek,
        endWeek,
        completionPercentage: avgPct,
        isCompleted: avgPct >= 100,
      };
    }).filter(Boolean) as RoadmapPhase[];
  }, [weeks, roadmap?.milestones]);

  const activePhase = useMemo(() => {
    if (!activeWeek) return null;
    return phases.find(
      (p) => activeWeek.week_number >= p.startWeek && activeWeek.week_number <= p.endWeek
    ) ?? null;
  }, [phases, activeWeek]);

  const handleSelectPhase = (phase: RoadmapPhase) => {
    const targetWeek = weeks.find(
      (w) => w.week_number >= phase.startWeek && w.week_number <= phase.endWeek && w.completion_percentage < 100
    ) || weeks.find((w) => w.week_number === phase.startWeek);
    if (targetWeek) setSelectedWeekNum(targetWeek.week_number);
  };

  // Step through the weeks we actually have, rather than assuming they're numbered 1, 2, 3…
  const stepWeek = (delta: number) => {
    const next = weeks[activeIndex + delta];
    if (next) setSelectedWeekNum(next.week_number);
  };

  const progress = roadmap?.progress ?? 0;
  const totalWeeks = roadmap?.total_weeks ?? roadmap?.estimated_weeks ?? weeks.length;
  const hoursPerWeek = roadmap?.weekly_hours_budget ?? roadmap?.hours_per_week ?? profile?.hours_per_week;
  const targetRole = roadmap?.target_role || analysis?.target_role || "Not set";
  const adaptiveNotice = showAdaptiveNotice || Boolean((roadmap?.adaptive_rebalance_count ?? 0) > 0);

  if (loading) {
    return (
      <div className="rm">
        <div className="rm__inner" aria-busy="true">
          <div className="rm-skel rm-skel--head" />
          <div className="rm-skel rm-skel--stats" />
          <div className="rm-skel rm-skel--block" />
          <p className="sr-only">Loading your roadmap</p>
        </div>
      </div>
    );
  }

  return (
    <div className="rm">
      <div className="rm__inner">
        <header className="rm-head">
          <div>
            <p className="rm-kicker">Your learning plan</p>
            <h1 className="rm-title">{roadmap?.title || "Weekly roadmap"}</h1>
            <p className="rm-sub">
              A week-by-week plan built from the skills {targetRole} needs
              {roadmap?.created_at ? `. Made on ${formatDate(roadmap.created_at)}` : ""}.
            </p>
          </div>
          <div className="rm-head__actions">
            <Button asChild variant="secondary"><Link to="/analysis/results">See your analysis</Link></Button>
            {roadmap && (
              <>
                <Button variant="secondary" onClick={handleAdaptiveReassess} disabled={reassessing || generating || rebuilding}>
                  {reassessing ? "Updating…" : "Adjust schedule"}
                </Button>
                <Button variant="primary" onClick={handleGenerate} disabled={generating || rebuilding || !profile?.hours_per_week}>
                  {generating ? "Rebuilding…" : "Rebuild roadmap"}
                </Button>
              </>
            )}
          </div>
        </header>

        {error && <div className="rm-alert rm-alert--error" role="alert">{error}</div>}

        {roleSync.stage !== "idle" && roleSync.role && (
          <div className={`rm-alert${rebuilding ? " rm-alert--busy" : ""}${roleSync.stage === "failed" ? " rm-alert--error" : ""}`} role="status">
            {rebuilding && <span className="rm-spin" aria-hidden="true" />}
            <span>
              {roleSync.stage === "analysing" && <>You changed your career to <strong>{roleSync.role}</strong>. Re-reading your evidence against it…</>}
              {roleSync.stage === "building" && <>Building your new weekly plan for <strong>{roleSync.role}</strong>…</>}
              {roleSync.stage === "done" && (roleSync.message ?? <><strong>This plan is now for {roleSync.role}.</strong> Your old plan was replaced.</>)}
              {roleSync.stage === "failed" && roleSync.message}
            </span>
            {!rebuilding && (
              <button type="button" className="rm-alert__close" onClick={resetRoleSync} aria-label="Dismiss">
                <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true">
                  <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                </svg>
              </button>
            )}
          </div>
        )}

        {adaptiveNotice && roadmap && (
          <div className="rm-alert" role="status">
            <strong>Your plan was updated.</strong> Work you’ve already finished is kept — only what’s ahead changed.
          </div>
        )}

        {roadmap && (
          <dl className="rm-stats">
            <div className="rm-stat">
              <dt>Target role</dt>
              <dd className="rm-stat__role">{targetRole}</dd>
            </div>
            <div className="rm-stat rm-stat--main">
              <dt>Overall progress</dt>
              <dd>
                <span className="rm-stat__big rm-num">{Math.round(progress)}<span className="rm-stat__unit">%</span></span>
                <Meter value={progress} tone={progress >= 100 ? "done" : "accent"} />
              </dd>
            </div>
            <div className="rm-stat">
              <dt>You’re on</dt>
              <dd><span className="rm-stat__num rm-num">Week {activeWeek?.week_number ?? selectedWeekNum}</span> of {totalWeeks || "—"}</dd>
            </div>
            <div className="rm-stat">
              <dt>Time</dt>
              <dd>
                <span className="rm-stat__num rm-num">{hoursPerWeek ? `${hoursPerWeek}h` : "—"}</span> a week
                {roadmap.total_estimated_hours ? <span className="rm-faint"> · {roadmap.total_estimated_hours}h in total</span> : null}
              </dd>
            </div>
          </dl>
        )}

        {!roadmap ? (
          <section className="rm-blank">
            <h2>Build your weekly roadmap</h2>
            <p>
              {analysis
                ? "INAURA turns your latest skill gaps into a realistic week-by-week plan you can actually follow."
                : "Run your analysis first — INAURA then turns your skill gaps into a realistic week-by-week plan."}
            </p>
            <div className="rm-blank__actions">
              <Button variant="primary" onClick={handleGenerate} disabled={generating || rebuilding || !profile?.hours_per_week}>
                {generating ? "Building your plan…" : "Build my roadmap"}
              </Button>
              {!profile?.hours_per_week && (
                <Button asChild variant="secondary"><Link to="/profile">Set your hours per week first</Link></Button>
              )}
            </div>
          </section>
        ) : weeks.length === 0 ? (
          <p className="rm-empty">No weekly tasks yet. Refresh your plan to build this week’s schedule.</p>
        ) : (
          <div className={`rm-plan${rebuilding ? " is-stale" : ""}`} aria-busy={rebuilding || undefined}>
            {phases.length > 1 && (
              <nav className="rm-phases" aria-label="Curriculum phases">
                {phases.map((phase) => {
                  const isActive = activePhase?.phaseNumber === phase.phaseNumber;
                  return (
                    <button
                      key={phase.phaseNumber}
                      type="button"
                      className={`rm-phase-pill${isActive ? " is-active" : ""}${phase.isCompleted ? " is-done" : ""}`}
                      onClick={() => handleSelectPhase(phase)}
                    >
                      <span>{phase.shortTitle} (W{phase.startWeek}–W{phase.endWeek})</span>
                      <span className="rm-num">
                        {phase.isCompleted ? <Tick /> : `${phase.completionPercentage}%`}
                      </span>
                    </button>
                  );
                })}
              </nav>
            )}

            <nav className="rm-weeks" role="tablist" aria-label="Weeks">
              {weeks.map((week) => {
                const active = activeWeek?.id === week.id;
                const complete = week.completion_percentage >= 100 || week.status === "completed";
                return (
                  <button
                    key={week.id}
                    type="button"
                    role="tab"
                    aria-selected={active}
                    className={`rm-week${active ? " is-active" : ""}${complete ? " is-done" : ""}`}
                    onClick={() => setSelectedWeekNum(week.week_number)}
                  >
                    <span className="rm-week__n">Week {week.week_number}</span>
                    <span className="rm-week__pct rm-num">
                      {complete ? <Tick /> : `${Math.round(week.completion_percentage)}%`}
                    </span>
                    <Meter value={week.completion_percentage} tone={complete ? "done" : "accent"} />
                  </button>
                );
              })}
            </nav>

            {activeWeek && (
              <WeekPanel
                week={activeWeek}
                weekCount={weeks.length}
                currentPhase={activePhase}
                updating={updating}
                expanded={expanded}
                onToggleExpanded={(taskId) => setExpanded((current) => ({ ...current, [taskId]: !current[taskId] }))}
                onUpdateTask={handleUpdateTask}
                onLaunchAssessment={(skillName, task) => setAssessingTarget({ skillName, task })}
                onStep={stepWeek}
                canPrev={activeIndex > 0}
                canNext={activeIndex < weeks.length - 1}
              />
            )}
          </div>
        )}
      </div>

      {assessingTarget && (
        <AssessmentModal
          skill={assessingTarget.skillName}
          onClose={() => setAssessingTarget(null)}
          onCompleted={async () => {
            await handleUpdateTask(assessingTarget.task, {
              status: "completed",
              completion_percentage: 100,
            });
            setAssessingTarget(null);
          }}
        />
      )}
    </div>
  );
}
