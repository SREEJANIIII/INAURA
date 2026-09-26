import { useState } from "react";
import { Link } from "react-router-dom";
import type { RoadmapTask } from "../../services/roadmap";
import {
  relativeDay,
  type ActivityEvent,
  type CoverageItem,
  type Insight,
  type NextAction,
} from "../home/homeModel";
import type { TrackSkill } from "./careerTrackModel";
import { useSkillNavigation } from "./motion";
import CareerActivity from "../outcomes/CareerActivity";

type Props = {
  weekNumber?: number;
  actions: NextAction[];
  priority: TrackSkill[];
  careerId: string;
  coverage: { items: CoverageItem[]; presentCount: number };
  insights: Insight[];
  activity: ActivityEvent[];
  onToggleTask: (task: RoadmapTask, done: boolean) => Promise<void>;
};

/** Supporting information beside the path: what to do now, what's missing, what changed */
export default function HomeAside({ weekNumber, actions, priority, careerId, coverage, insights, activity, onToggleTask }: Props) {
  const [done, setDone] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [taskError, setTaskError] = useState<string | null>(null);
  const [openInsight, setOpenInsight] = useState<string | null>(null);
  const go = useSkillNavigation();

  const toggle = async (task: RoadmapTask) => {
    const next = !done[task.id];
    setBusy(task.id);
    setTaskError(null);
    setDone((d) => ({ ...d, [task.id]: next }));
    try {
      await onToggleTask(task, next);
    } catch {
      setDone((d) => ({ ...d, [task.id]: !next }));
      setTaskError("That task couldn’t be updated. Check your connection and try again.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <aside className="ct-aside" aria-label="Your next steps and evidence">
      <section className="ct-block">
        <div className="ct-block__head">
          <h2 className="ct-block__title">Next up</h2>
          {weekNumber ? <span className="ct-faint">Week {weekNumber}</span> : null}
        </div>
        {actions.length === 0 ? (
          <p className="ct-muted">Nothing pressing. Your evidence and roadmap are up to date.</p>
        ) : (
          <ul className="ct-todo">
            {actions.map((a) =>
              a.kind === "task" ? (
                <li key={a.id}>
                  <label className={`ct-todo__item${done[a.task.id] ? " is-done" : ""}`}>
                    <input
                      type="checkbox"
                      className="ct-check"
                      checked={!!done[a.task.id]}
                      disabled={busy === a.task.id}
                      onChange={() => toggle(a.task)}
                    />
                    <span className="ct-todo__text">
                      <span className="ct-todo__title">{a.title}</span>
                      {a.meta && <span className="ct-faint">{a.meta}</span>}
                    </span>
                  </label>
                </li>
              ) : (
                <li key={a.id}>
                  <Link to={a.to} className="ct-todo__item ct-todo__item--link">
                    <span className="ct-todo__dot" aria-hidden="true" />
                    <span className="ct-todo__text">
                      <span className="ct-todo__title">{a.title}</span>
                      {a.meta && <span className="ct-faint">{a.meta}</span>}
                    </span>
                  </Link>
                </li>
              )
            )}
          </ul>
        )}
        {taskError && <p className="ct-error" role="alert">{taskError}</p>}
      </section>

      {priority.length > 0 && (
        <section className="ct-block">
          <div className="ct-block__head">
            <h2 className="ct-block__title">Biggest gaps</h2>
          </div>
          <ul className="ct-gaps">
            {priority.map((s) => {
              const to = `/career-track/${careerId}/${s.id}`;
              return (
                <li key={s.id}>
                  <Link to={to} className="ct-gaps__row" onClick={(e) => go(e, to, null)}>
                    <span className="ct-gaps__name">{s.name}</span>
                    <span className="ct-bar ct-bar--sm" aria-hidden="true">
                      <span className="ct-bar__fill" style={{ width: `${s.currentProgress}%` }} />
                      <span className="ct-bar__target" style={{ left: `${s.requiredProgress}%` }} />
                    </span>
                    <span className="ct-gaps__gap ct-num">{s.gap}%</span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      <section className="ct-block">
        <div className="ct-block__head">
          <h2 className="ct-block__title">Evidence</h2>
          <span className="ct-faint">
            <span className="ct-num">{coverage.presentCount}</span> of {coverage.items.length}
          </span>
        </div>
        <ul className="ct-sources">
          {coverage.items.map((i) => (
            <li key={i.key}>
              <Link to={i.to} className={`ct-source ct-source--${i.state}`}>
                <span className="ct-source__glyph" aria-hidden="true">
                  {i.state === "verified" || i.state === "included" ? "✓" : i.state === "failed" ? "!" : i.state === "added" ? "◐" : "＋"}
                </span>
                <span className="ct-source__label">{i.label}</span>
                <span className="ct-source__detail">{i.detail}</span>
              </Link>
            </li>
          ))}
        </ul>
      </section>

      {(insights.length > 0 || activity.length > 0) && (
        <section className="ct-block">
          <div className="ct-block__head">
            <h2 className="ct-block__title">What changed</h2>
          </div>
          {insights.length > 0 && (
            <ul className="ct-insights">
              {insights.slice(0, 3).map((i) => {
                const open = openInsight === i.id;
                return (
                  <li key={i.id} className={`ct-insight ct-insight--${i.tone}`}>
                    <button type="button" className="ct-insight__row" aria-expanded={open} onClick={() => setOpenInsight(open ? null : i.id)}>
                      <span className="ct-insight__mark" aria-hidden="true" />
                      <span>{i.title}</span>
                    </button>
                    {open && (
                      <div className="ct-insight__detail">
                        <p>{i.detail}</p>
                        <Link to={i.to} className="ct-link">See in skill analysis</Link>
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
          {activity.length > 0 && (
            <ol className="ct-activity">
              {activity.slice(0, 4).map((e) => (
                <li key={e.id} className={`ct-activity__item ct-activity__item--${e.tone}`}>
                  <span className="ct-activity__dot" aria-hidden="true" />
                  <span>{e.text}</span>
                  <time dateTime={e.at} className="ct-faint">{relativeDay(e.at)}</time>
                </li>
              ))}
            </ol>
          )}
        </section>
      )}

      <CareerActivity />
    </aside>
  );
}
