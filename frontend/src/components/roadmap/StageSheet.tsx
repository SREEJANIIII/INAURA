import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { levelName } from "../career-track/careerTrackModel.ts";
import { SIGNAL_STAGES } from "../home/homeModel.ts";
import type { RoadmapTask } from "../../services/roadmap";
import { useDialog } from "../../lib/useDialog";
import Button from "@/components/ui/app-button";
import {
  STATE_META,
  isCleared,
  missingFor,
  readableHours,
  skillReasons,
  stageReasons,
  stageStatusLabel,
  tierLabel,
  type Journey,
  type JourneySkill,
  type JourneyStage,
} from "./journeyModel";
import StateGlyph from "./StateGlyph";

const TASK_TYPE: Record<RoadmapTask["task_type"], string> = {
  learn: "Learn",
  practice: "Practice",
  build: "Build",
  validate: "Validate",
};

type Handlers = {
  updating: string | null;
  /** The skill whose tasks are being marked done together, if any */
  bulkBusy: string | null;
  onToggleTask: (task: RoadmapTask, done: boolean) => void;
  onStart: (skill: JourneySkill) => void;
  onCompleteSkill: (skill: JourneySkill) => void;
  onShowWeek: (week: number) => void;
};

type Props = Handlers & {
  journey: Journey;
  stage: JourneyStage;
  role: string;
  openSkill: string | null;
  onOpenSkill: (key: string | null) => void;
  onSelectStage: (index: number) => void;
  onClose: () => void;
  /** Phones: the detail slides up over the page instead of opening beneath the map */
  asSheet: boolean;
};

/** Where a skill stands against the role: filled to your level, with a mark at the level needed */
function LevelBar({ current, required }: { current: number | null; required: number | null }) {
  return (
    <span className="jr-lvl" aria-hidden="true">
      <span className="jr-lvl__fill" style={{ width: `${current ?? 0}%` }} />
      {required !== null && <span className="jr-lvl__target" style={{ left: `${required}%` }} />}
    </span>
  );
}

const firstResource = (skill: JourneySkill) => {
  const learn = skill.tasks.find((t) => t.task.task_type === "learn" && t.task.resources.length > 0);
  return (learn ?? skill.tasks.find((t) => t.task.resources.length > 0))?.task.resources[0] ?? null;
};

function SkillRow({
  skill,
  journey,
  role,
  open,
  onToggle,
  updating,
  bulkBusy,
  onToggleTask,
  onStart,
  onCompleteSkill,
  onShowWeek,
}: Handlers & { skill: JourneySkill; journey: Journey; role: string; open: boolean; onToggle: () => void }) {
  const [confirming, setConfirming] = useState(false);
  const ref = useRef<HTMLLIElement>(null);
  const reasons = open ? skillReasons(skill, journey, role) : [];
  const missing = missingFor(skill);
  const resource = firstResource(skill);
  const signal = SIGNAL_STAGES.find((s) => s.key === skill.evidence);
  const remainingTasks = skill.tasks.filter((t) => !isCleared(t.task));
  const busy = bulkBusy === skill.key;
  const focus = skill.tasks.map((t) => t.task.personalization_context?.primary_gap).find((g): g is string => typeof g === "string");

  // Opening a skill brings its name to the top, unless it's already comfortably in view
  useEffect(() => {
    const el = ref.current;
    if (!open || !el) return;
    const top = el.getBoundingClientRect().top;
    const view = el.closest(".jr-sheet--float")?.getBoundingClientRect() ?? { top: 0, bottom: window.innerHeight };
    if (top > view.top + 60 && top < view.top + (view.bottom - view.top) * 0.5) return;
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    el.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
  }, [open]);

  return (
    <li ref={ref} id={`jr-skill-${skill.key}`} className={`jr-skill jr-skill--${skill.state}${open ? " is-open" : ""}`}>
      <button type="button" className="jr-skill__row" aria-expanded={open} onClick={onToggle}>
        <StateGlyph state={skill.state} size={16} />
        <span className="jr-skill__name">{skill.name}</span>
        <span className={`jr-skill__state jr-skill__state--${skill.state}`}>{STATE_META[skill.state].label}</span>
        <span className="jr-skill__levels">
          <LevelBar current={skill.current} required={skill.required} />
          <span className="jr-num">
            {skill.current ?? "—"}
            <span className="jr-faint"> / {skill.required ?? "—"}</span>
          </span>
        </span>
        <span className="jr-skill__left jr-num">
          {skill.tasksDone ? "Tasks done" : `${readableHours(skill.remainingMinutes)} left`}
        </span>
        <svg className="jr-skill__chev" width="14" height="14" viewBox="0 0 16 16" aria-hidden="true">
          <path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {open && (
        <div className="jr-skill__detail">
          <div className="jr-skill__why">
            <h4>Why it’s on your road</h4>
            <dl className="jr-reasons">
              {reasons.map((r) => (
                <div key={r.label}>
                  <dt>{r.label}</dt>
                  <dd>{r.text}</dd>
                </div>
              ))}
            </dl>
            {(missing || focus) && (
              <>
                <h4>What’s missing</h4>
                {missing && <p className="jr-missing">{missing}</p>}
                {focus && <p className="jr-missing">Your tasks focus first on: {focus}.</p>}
              </>
            )}
          </div>

          <div className="jr-skill__facts">
            <dl className="jr-levels">
              <div>
                <dt>Current level</dt>
                <dd>
                  {skill.current === null ? "Not scored" : `${skill.current}%`}
                  {skill.current !== null && <span>{levelName(skill.current)}</span>}
                </dd>
              </div>
              <div>
                <dt>Target level</dt>
                <dd>
                  {skill.required === null ? "Not scored" : `${skill.required}%`}
                  {skill.required !== null && <span>{levelName(skill.required)}</span>}
                </dd>
              </div>
              <div>
                <dt>Evidence strength</dt>
                <dd>
                  {signal ? signal.label : "Not scored"}
                  {skill.gap?.evidence_count ? (
                    <span>
                      {skill.gap.evidence_count} source{skill.gap.evidence_count === 1 ? "" : "s"}
                    </span>
                  ) : null}
                </dd>
              </div>
              <div>
                <dt>Estimated effort</dt>
                <dd>
                  {readableHours(skill.remainingMinutes)} left
                  <span>of {readableHours(skill.minutes)}</span>
                </dd>
              </div>
            </dl>

            <h4>Roadmap tasks</h4>
            <ul className="jr-tasks">
              {skill.tasks.map(({ task, week }) => {
                const done = task.status === "completed" || task.completion_percentage >= 100;
                return (
                  <li key={task.id} className={`jr-task${done ? " is-done" : ""}${task.status === "skipped" ? " is-skipped" : ""}`}>
                    <label className="jr-task__check">
                      <input
                        type="checkbox"
                        checked={done}
                        disabled={updating === task.id || busy}
                        onChange={(e) => onToggleTask(task, e.target.checked)}
                      />
                      <span className="sr-only">Mark “{task.title}” done</span>
                    </label>
                    <span className="jr-task__text">
                      <span className="jr-task__title">{task.title}</span>
                      <span className="jr-task__meta">
                        {TASK_TYPE[task.task_type]}, {readableHours(task.estimated_minutes)}
                        {updating === task.id && ", saving…"}
                        {task.status === "skipped" && ", skipped"}
                      </span>
                    </span>
                    <button type="button" className="jr-task__week" onClick={() => onShowWeek(week)}>
                      Week {week}
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>

          <div className="jr-skill__actions">
            {confirming ? (
              <div className="jr-confirm" role="group" aria-label={`Mark ${skill.name} complete`}>
                <p>
                  Mark the {remainingTasks.length} remaining task{remainingTasks.length === 1 ? "" : "s"} done? That records the work.
                  The skill stays “Needs proof” until your analysis confirms the level.
                </p>
                <Button
                  size="sm"
                  variant="primary"
                  disabled={busy}
                  onClick={() => {
                    setConfirming(false);
                    onCompleteSkill(skill);
                  }}
                >
                  Mark {remainingTasks.length} done
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>
                  Cancel
                </Button>
              </div>
            ) : (
              <>
                {!skill.tasksDone &&
                  (skill.started ? (
                    <Button size="sm" variant="primary" onClick={() => remainingTasks[0] && onShowWeek(remainingTasks[0].week)}>
                      Continue
                    </Button>
                  ) : (
                    <Button size="sm" variant="primary" disabled={busy || !!updating} onClick={() => onStart(skill)}>
                      Start
                    </Button>
                  ))}
                {resource && (
                  <Button asChild size="sm" variant="secondary">
                    <a href={resource.url} target="_blank" rel="noreferrer" aria-label={`Learn: ${resource.title} (opens in a new tab)`} title={resource.title}>
                      Learn
                    </a>
                  </Button>
                )}
                <Button asChild size="sm" variant="secondary">
                  <Link to="/analysis">Add evidence</Link>
                </Button>
                {remainingTasks.length > 0 && (
                  <Button size="sm" variant="ghost" disabled={busy} onClick={() => setConfirming(true)}>
                    {busy ? "Marking done…" : "Mark complete"}
                  </Button>
                )}
                {!skill.started && skill.prerequisites.some((p) => !p.met) && (
                  <span className="jr-hint">
                    Planned after {skill.prerequisites.filter((p) => !p.met).map((p) => p.name).join(" and ")}, but you can start it now.
                  </span>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </li>
  );
}

export default function StageSheet(props: Props) {
  const { journey, stage, role, openSkill, onOpenSkill, onSelectStage, onClose, asSheet } = props;
  const dialogRef = useDialog<HTMLElement>(asSheet, onClose);
  const inlineRef = useRef<HTMLElement>(null);
  const names = stage.skills.map((s) => s.name);
  const fullTitle = names.length <= 1 ? names[0] : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;

  // Beneath the map: bring the detail into view when a checkpoint is picked
  useEffect(() => {
    if (asSheet || openSkill) return;
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    inlineRef.current?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "nearest" });
  }, [stage.index, asSheet, openSkill]);

  const body = (
    <>
      <header className="jr-sheet__head">
        <div className="jr-sheet__heading">
          <p className="jr-sheet__kicker">
            <span className="jr-sheet__num">Checkpoint {stage.number}</span>
            {stage.phase && <span>{stage.phase}</span>}
            <span className={`jr-sheet__tier jr-sheet__tier--${stage.tier}`}>{tierLabel(stage.tier, role)}</span>
          </p>
          <h2 id="jr-sheet-title">{fullTitle}</h2>
        </div>
        <button type="button" className="jr-sheet__close" onClick={onClose} aria-label="Close checkpoint detail">
          <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
            <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          </svg>
        </button>
      </header>

      <dl className="jr-sheet__facts">
        <div>
          <dt>Status</dt>
          <dd>{stageStatusLabel(stage)}</dd>
        </div>
        <div>
          <dt>Done</dt>
          <dd className="jr-num">{stage.progress}%</dd>
        </div>
        <div>
          <dt>Effort</dt>
          <dd className="jr-num">
            {readableHours(stage.remainingMinutes)} left of {readableHours(stage.minutes)}
          </dd>
        </div>
        <div>
          <dt>Planned</dt>
          <dd className="jr-num">{stage.firstWeek === stage.lastWeek ? `Week ${stage.firstWeek}` : `Weeks ${stage.firstWeek}–${stage.lastWeek}`}</dd>
        </div>
      </dl>

      <p className="jr-sheet__why">{stageReasons(stage, journey, role).join(" ")}</p>

      <ol className="jr-skills">
        {stage.skills.map((skill) => (
          <SkillRow
            key={skill.key}
            {...props}
            skill={skill}
            open={openSkill === skill.key}
            onToggle={() => onOpenSkill(openSkill === skill.key ? null : skill.key)}
          />
        ))}
      </ol>

      <nav className="jr-sheet__foot" aria-label="Other checkpoints">
        <Button size="sm" variant="ghost" disabled={stage.index === 0} onClick={() => onSelectStage(stage.index - 1)}>
          Previous checkpoint
        </Button>
        <Button size="sm" variant="secondary" disabled={stage.index >= journey.stages.length - 1} onClick={() => onSelectStage(stage.index + 1)}>
          Next checkpoint
        </Button>
      </nav>
    </>
  );

  if (asSheet) {
    return (
      <div className="jr-sheet-layer" onClick={onClose}>
        <section
          ref={dialogRef}
          id="jr-sheet"
          className="jr-sheet jr-sheet--float"
          role="dialog"
          aria-modal="true"
          aria-labelledby="jr-sheet-title"
          tabIndex={-1}
          onClick={(e) => e.stopPropagation()}
        >
          <span className="jr-sheet__grip" aria-hidden="true" />
          {body}
        </section>
      </div>
    );
  }

  return (
    <section
      ref={inlineRef}
      id="jr-sheet"
      className="jr-sheet"
      aria-labelledby="jr-sheet-title"
      onKeyDown={(e) => {
        if (e.key === "Escape") onClose();
      }}
    >
      {body}
    </section>
  );
}
