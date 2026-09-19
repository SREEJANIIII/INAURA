import { useRef, type CSSProperties } from "react";
import { Link } from "react-router-dom";
import { STATUS_LABEL, type TrackPhase, type TrackSkill } from "./careerTrackModel";
import { useInViewOnce, useSkillNavigation } from "./motion";

type Props = {
  phases: TrackPhase[];
  careerId: string;
  /** The skill you're on — marked "You are here" */
  current: TrackSkill | null;
};

function SkillStep({ skill, careerId, current }: { skill: TrackSkill; careerId: string; current: boolean }) {
  const markRef = useRef<HTMLSpanElement>(null);
  const go = useSkillNavigation();
  const to = `/career-track/${careerId}/${skill.id}`;
  const done = skill.status === "completed";

  return (
    <li className={`path-step path-step--${skill.status}${current ? " is-current" : ""}`}>
      <Link
        to={to}
        className="path-step__link"
        onClick={(e) => go(e, to, markRef.current)}
        aria-label={`${skill.name}: ${STATUS_LABEL[skill.status]}, ${skill.currentProgress}% of ${skill.requiredProgress}% required`}
      >
        <span ref={markRef} className="path-step__node" aria-hidden="true">
          {done ? (
            <svg width="11" height="11" viewBox="0 0 12 12">
              <path d="M2.5 6.4 5 8.8l4.5-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          ) : skill.status === "locked" ? (
            <svg width="10" height="10" viewBox="0 0 12 12">
              <rect x="2.5" y="5.5" width="7" height="5" rx="1.2" fill="none" stroke="currentColor" strokeWidth="1.5" />
              <path d="M4 5.5V4a2 2 0 0 1 4 0v1.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
            </svg>
          ) : null}
        </span>

        <span className="path-step__text">
          <span className="path-step__name">
            {skill.name}
            {current && <span className="path-step__here">You are here</span>}
          </span>
          <span className="path-step__levels">
            {skill.status === "locked" && skill.prerequisites.some((p) => !p.met)
              ? `After ${skill.prerequisites.filter((p) => !p.met).map((p) => p.name).join(" and ")}`
              : `${skill.currentLevel} → ${skill.requiredLevel}`}
          </span>
        </span>

        <span className="path-step__meter">
          <span className="ct-bar ct-bar--sm" aria-hidden="true">
            <span className={`ct-bar__fill${done ? " is-done" : ""}`} style={{ width: `${skill.currentProgress}%` }} />
            <span className="ct-bar__target" style={{ left: `${skill.requiredProgress}%` }} />
          </span>
          <span className="path-step__nums ct-num">
            {skill.currentProgress}
            <span className="ct-faint"> / {skill.requiredProgress}</span>
          </span>
        </span>

        <span className={`path-step__status path-step__status--${skill.status}`}>
          {done ? "Ready" : skill.gap > 0 ? `${skill.gap}% to go` : STATUS_LABEL[skill.status]}
        </span>

        <svg className="path-step__chev" width="15" height="15" viewBox="0 0 16 16" aria-hidden="true">
          <path d="M6 3.5 10.5 8 6 12.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </Link>
    </li>
  );
}

function Phase({ phase, index, careerId, current }: { phase: TrackPhase; index: number; careerId: string; current: TrackSkill | null }) {
  const [ref, inView] = useInViewOnce<HTMLLIElement>();
  return (
    <li ref={ref} className={`path-phase path-phase--${phase.status}${inView ? " is-in" : ""}`} style={{ "--i": index } as CSSProperties}>
      <div className="path-phase__head">
        <span className="path-phase__station" aria-hidden="true">
          {phase.status === "completed" ? (
            <svg width="13" height="13" viewBox="0 0 12 12">
              <path d="M2.5 6.4 5 8.8l4.5-5" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          ) : (
            <span className="ct-num">{index + 1}</span>
          )}
        </span>
        <h3 className="path-phase__name">{phase.title}</h3>
        <span className="path-phase__meta">
          <span className="ct-num">{phase.progress}%</span>
          <span className="ct-faint">
            {phase.skills.filter((s) => s.status === "completed").length} of {phase.skills.length} ready
          </span>
        </span>
      </div>
      <ol className="path-phase__steps">
        {phase.skills.map((s) => (
          <SkillStep key={s.id} skill={s} careerId={careerId} current={current?.id === s.id} />
        ))}
      </ol>
    </li>
  );
}

/** The career path: phases as stations on one line, each skill a step along it */
export default function CareerPath({ phases, careerId, current }: Props) {
  if (phases.length === 0) {
    return <p className="ct-empty">No skills to map for this role yet. Run your analysis to fill in your path.</p>;
  }
  return (
    <ol className="path">
      {phases.map((p, i) => (
        <Phase key={p.id} phase={p} index={i} careerId={careerId} current={current} />
      ))}
    </ol>
  );
}
