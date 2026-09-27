import { Link } from "react-router-dom";
import type { RoadmapTask, RoadmapWeek } from "../../services/roadmap";
import Button from "@/components/ui/app-button";
import type { JourneyStage } from "./journeyModel";

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

/** The score a knowledge check has to reach to count as proof — the same bar the analysis uses */
export const PASS_SCORE = 0.6;

export type TaskUpdate = {
  status?: RoadmapTask["status"];
  completion_percentage?: number;
};

function formatDate(value?: string | null) {
  if (!value) return "Unavailable";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Unavailable"
    : date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
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
            // Unticking means "not done after all": back to the start, not left at 99%
            onChange={(event) => onUpdate(event.target.checked
              ? { status: "completed", completion_percentage: 100 }
              : { status: "not_started", completion_percentage: 0 })}
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
                  Take the {task.skill_name} check
                </Button>
                <Button asChild size="sm" variant="ghost">
                  <Link to="/interview">Practise in a mock interview</Link>
                </Button>
                <span className="rm-task__action-hint">
                  Scoring {Math.round(PASS_SCORE * 100)}% or more marks this task done.
                </span>
              </>
            )}
            {task.task_type === "build" && (
              <>
                <Button asChild size="sm" variant="secondary">
                  <Link to="/analysis">Add project evidence</Link>
                </Button>
                <span className="rm-task__action-hint">
                  Link a GitHub repo or deliverable so INAURA can check this build.
                </span>
              </>
            )}
            {task.task_type === "practice" && task.resources.length > 0 && (
              <Button asChild size="sm" variant="secondary">
                <a href={task.resources[0].url} target="_blank" rel="noreferrer">
                  Open practice drill ({task.resources[0].provider || "Practice"})
                </a>
              </Button>
            )}
            {task.task_type === "learn" && task.resources.length > 0 && (
              <Button asChild size="sm" variant="ghost">
                <a href={task.resources[0].url} target="_blank" rel="noreferrer">
                  Study: {task.resources[0].title}
                </a>
              </Button>
            )}
          </div>
        </div>
      )}
    </li>
  );
}

type WeekPlanProps = {
  weeks: RoadmapWeek[];
  week: RoadmapWeek;
  /** The first week with anything left to do */
  currentWeek: number | null;
  /** The checkpoint this week's first task belongs to */
  stage: JourneyStage | null;
  updating: string | null;
  expanded: Record<string, boolean>;
  onToggleExpanded: (taskId: string) => void;
  onUpdateTask: (task: RoadmapTask, patch: TaskUpdate) => void;
  onLaunchAssessment: (skillName: string, task: RoadmapTask) => void;
  onPickWeek: (weekNumber: number) => void;
  onOpenStage: (index: number) => void;
};

/** This week's work: a strip of every week, then the chosen week's tasks grouped by stage */
export default function WeekPlan({
  weeks,
  week,
  currentWeek,
  stage,
  updating,
  expanded,
  onToggleExpanded,
  onUpdateTask,
  onLaunchAssessment,
  onPickWeek,
  onOpenStage,
}: WeekPlanProps) {
  const tasks = week.tasks ?? [];
  const index = weeks.findIndex((w) => w.id === week.id);
  const doneCount = tasks.filter((t) => t.status === "completed" || t.completion_percentage >= 100).length;
  const remainingMinutes = tasks
    .filter((t) => t.status !== "completed" && t.status !== "skipped")
    .reduce((total, t) => total + t.estimated_minutes, 0);
  const isCurrent = week.week_number === currentWeek;

  return (
    <section className="rm-week-plan" aria-labelledby="rm-week-title">
      <header className="rm-week-plan__head">
        <h2 id="rm-week-title">{isCurrent ? "This week" : `Week ${week.week_number}`}</h2>
        {!isCurrent && currentWeek !== null && (
          <button type="button" className="rm-textbtn" onClick={() => onPickWeek(currentWeek)}>
            Back to this week
          </button>
        )}
      </header>

      <div className="rm-strip" role="tablist" aria-label="Weeks">
        {weeks.map((w) => {
          const complete = w.completion_percentage >= 100 || w.status === "completed";
          const active = w.id === week.id;
          return (
            <button
              key={w.id}
              type="button"
              role="tab"
              aria-selected={active}
              aria-label={`Week ${w.week_number}: ${Math.round(w.completion_percentage)}% done${w.week_number === currentWeek ? ", this week" : ""}`}
              className={`rm-tick${active ? " is-active" : ""}${complete ? " is-done" : ""}${w.week_number === currentWeek ? " is-now" : ""}`}
              onClick={() => onPickWeek(w.week_number)}
            >
              <span className="rm-tick__n">{w.week_number}</span>
              <span className="rm-tick__fill" style={{ height: `${Math.max(0, Math.min(100, w.completion_percentage))}%` }} />
            </button>
          );
        })}
      </div>

      <div className="rm-panel">
        <header className="rm-panel__head">
          <div>
            <p className="rm-eyebrow">
              <span>
                Week {week.week_number} of {weeks.length}
              </span>
              <span className={`rm-wstate rm-wstate--${week.status}`}>{WEEK_STATUS_LABEL[week.status]}</span>
              {week.start_date && (
                <span className="rm-faint">
                  {formatDate(week.start_date)} to {formatDate(week.target_completion_date)}
                </span>
              )}
            </p>
            <h3 className="rm-panel__title">{week.title.replace(/^Week \d+:\s*/, "")}</h3>
            {week.objective && <p className="rm-obj">{week.objective}</p>}
            {stage && (
              <button type="button" className="rm-onmap" onClick={() => onOpenStage(stage.index)}>
                On your road: checkpoint {stage.number}, {stage.title}
              </button>
            )}
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
            {doneCount} of {tasks.length} task{tasks.length === 1 ? "" : "s"} done, {Math.round(week.completion_percentage)}%
          </span>
        </div>

        {tasks.length === 0 ? (
          <p className="rm-empty">This week has no tasks yet. Rebuild your plan to fill it in.</p>
        ) : (
          STAGES.map((stageType) => {
            const stageTasks = tasks.filter((task) => task.task_type === stageType);
            if (stageTasks.length === 0) return null;
            const stageMinutes = stageTasks.reduce((total, t) => total + t.estimated_minutes, 0);
            return (
              <section className="rm-stage" key={stageType} aria-labelledby={`${week.id}-${stageType}`}>
                <header className="rm-stage__head">
                  <h4 id={`${week.id}-${stageType}`}>
                    <span className={`rm-dot rm-dot--${stageType}`} aria-hidden="true" />
                    {STAGE_LABEL[stageType]}
                    <span className="rm-faint">{STAGE_HINT[stageType]}</span>
                  </h4>
                  <span className="rm-faint rm-num">
                    {stageTasks.length} task{stageTasks.length === 1 ? "" : "s"}, {readableMinutes(stageMinutes)}
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

        {(week.skills ?? []).length > 0 && (
          <p className="rm-revise">
            Keep this week’s skills from slipping: <Link to="/revision">revise them in a few minutes</Link>.
          </p>
        )}

        <div className="rm-panel__foot">
          <Button variant="ghost" size="sm" disabled={index <= 0} onClick={() => onPickWeek(weeks[index - 1].week_number)}>
            Previous week
          </Button>
          <Button variant="secondary" size="sm" disabled={index >= weeks.length - 1} onClick={() => onPickWeek(weeks[index + 1].week_number)}>
            Next week
          </Button>
        </div>
      </div>
    </section>
  );
}
