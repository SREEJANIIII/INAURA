import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { Check, Lock } from "lucide-react";
import Button from "../ui/app-button";
import { useCountUp, useInViewOnce } from "../career-track/motion";
import { EASE, Grow, Reveal, Stagger, StaggerItem, useStill } from "./scroll";
import { DEFAULT_ROLE, EXAMPLE_TRACKS, type ExamplePhase } from "./careerTrackExamples";
import "./shared.css";
import "./CareerTrackSection.css";

const POINTS = [
  {
    title: "Learn the right order",
    desc: "Skills arrive in phases: foundations first, advanced topics once you’re ready for them. You always know what’s next.",
  },
  {
    title: "Understand the role",
    desc: "Every skill shows where your evidence puts you and where the role expects you to be. The gap is a number, not a feeling.",
  },
  {
    title: "Unlock opportunities",
    desc: "As skills reach the bar, you see which opportunities come within reach, so progress turns into something you can apply for.",
  },
];

const PHASE_META = (phase: ExamplePhase) =>
  phase.state === "locked" ? "Locked" : `${phase.skills.filter((s) => s.status === "ready").length} of ${phase.skills.length} ready`;

function Phase({ phase, index }: { phase: ExamplePhase; index: number }) {
  return (
    <div className={`ctrack__phase ctrack__phase--${phase.state}`}>
      <div className="ctrack__phase-head">
        <span className="ctrack__station" aria-hidden="true">
          {phase.state === "done" ? <Check /> : phase.state === "locked" ? <Lock /> : index + 1}
        </span>
        <h3 className="ctrack__phase-name">{phase.title}</h3>
        <span className="ctrack__phase-meta">{PHASE_META(phase)}</span>
      </div>
      <ul className="ctrack__steps">
        {phase.skills.map((s, i) => (
          <li key={s.name} className={`ctrack__step ctrack__step--${s.status}`}>
            <span className="ctrack__step-text">
              <span className="ctrack__step-name">
                {s.name}
                {s.status === "current" && <em className="ctrack__here">You are here</em>}
              </span>
              <span className="ctrack__step-levels">{s.levels}</span>
            </span>
            <span className="lp-bar ctrack__bar" aria-hidden="true">
              {s.now > 0 && (
                <Grow
                  width={s.now}
                  className={`lp-bar__fill${s.status === "ready" ? " lp-bar__fill--ready" : s.status === "next" ? " lp-bar__fill--soft" : ""}`}
                  delay={0.15 + index * 0.12 + i * 0.08}
                />
              )}
              <span className="lp-bar__target" style={{ left: `${s.need}%` }} />
            </span>
            <span className="ctrack__step-status">{s.label}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function CareerTrackSection() {
  const navigate = useNavigate();
  const reduce = useStill();
  const [role, setRole] = useState(DEFAULT_ROLE);
  const track = useMemo(() => EXAMPLE_TRACKS.find((t) => t.role === role) ?? EXAMPLE_TRACKS[0], [role]);
  const [boardRef, inView] = useInViewOnce<HTMLDivElement>();
  const readiness = useCountUp(track.readiness, inView);

  const skills = track.phases.flatMap((p) => p.skills);
  const stats = [
    { label: "Skills", value: skills.length },
    { label: "Ready", value: skills.filter((s) => s.status === "ready").length },
    { label: "In progress", value: skills.filter((s) => s.status === "current" || s.status === "next").length },
    { label: "Locked", value: skills.filter((s) => s.status === "locked").length },
  ];
  const current = skills.find((s) => s.status === "current");

  return (
    <section id="career-track" className="ctrack section section--subtle">
      <div className="container">
        <Reveal className="lp-head lp-head--center ctrack__head">
          <div className="eyebrow">Career Track</div>
          <h2 className="lp-title ctrack__title">
            Pick a career.
            <br />
            <span className="is-accent">See the whole path.</span>
          </h2>
          <p className="lp-lede">
            Choose the role you&rsquo;re aiming for and INAURA maps the skills, milestones and
            opportunities between where you are and where you need to be.
          </p>
        </Reveal>

        <Reveal className="ctrack__picker" y={20}>
          <span className="lp-kicker ctrack__picker-label" id="ctrack-picker-label">
            Preview a career
          </span>
          <div className="ctrack__roles" role="group" aria-labelledby="ctrack-picker-label">
            {EXAMPLE_TRACKS.map((t) => {
              const active = t.role === role;
              return (
                <button
                  key={t.role}
                  type="button"
                  className={active ? "ctrack__role is-active" : "ctrack__role"}
                  aria-pressed={active}
                  onClick={() => setRole(t.role)}
                >
                  {active && (
                    <motion.span
                      layoutId="ctrack-role"
                      className="ctrack__role-pill"
                      transition={reduce ? { duration: 0 } : { type: "spring", stiffness: 420, damping: 34 }}
                    />
                  )}
                  <span className="ctrack__role-label">{t.role}</span>
                </button>
              );
            })}
          </div>
        </Reveal>

        <div className="ctrack__stage">
          <Reveal className="ctrack__board-wrap" y={48} amount={0.15}>
            <div ref={boardRef} className="lp-panel ctrack__board" aria-label={`Example Career Track: ${track.role}`} role="region">
              <div className="lp-panel__head ctrack__board-head">
                <div>
                  <span className="lp-kicker">Your Career Track</span>
                  <span className="ctrack__role-title" aria-live="polite">
                    {track.role}
                  </span>
                </div>
                <div className="ctrack__readiness">
                  <span className="ctrack__readiness-num">{readiness}%</span>
                  <span className="ctrack__readiness-label">Ready</span>
                </div>
              </div>

              <div className="ctrack__summary">
                <span className="lp-bar ctrack__summary-bar" aria-hidden="true">
                  <Grow key={track.role} width={track.readiness} className="lp-bar__fill" delay={0.1} />
                </span>
                <dl className="ctrack__stats">
                  {stats.map((s) => (
                    <div key={s.label}>
                      <dt>{s.label}</dt>
                      <dd>{s.value}</dd>
                    </div>
                  ))}
                </dl>
              </div>

              <AnimatePresence mode="wait" initial={false}>
                <motion.div
                  key={track.role}
                  className="ctrack__phases"
                  initial={reduce ? false : { opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={reduce ? undefined : { opacity: 0, y: -6 }}
                  transition={{ duration: 0.28, ease: EASE }}
                >
                  {track.phases.map((phase, i) => (
                    <Phase key={phase.title} phase={phase} index={i} />
                  ))}
                </motion.div>
              </AnimatePresence>

              <div className="lp-panel__foot ctrack__foot">
                <span>
                  Next milestone: <strong>{current ? `${current.name} → ${current.levels.split(" → ")[1]}` : "—"}</strong>
                </span>
                <span>Example track · yours is built from your own evidence</span>
              </div>
            </div>
          </Reveal>

          <div className="ctrack__side">
            <Stagger className="ctrack__points" role="list" gap={0.12}>
              {POINTS.map((p, i) => (
                <StaggerItem key={p.title} className="ctrack__point" role="listitem" y={20}>
                  <span className="lp-num">{String(i + 1).padStart(2, "0")}</span>
                  <div>
                    <h3 className="ctrack__point-title">{p.title}</h3>
                    <p className="ctrack__point-desc">{p.desc}</p>
                  </div>
                </StaggerItem>
              ))}
            </Stagger>

            <Reveal className="ctrack__cta" y={16}>
              <Button variant="primary" size="md" onClick={() => navigate("/signup")}>
                Start your Career Track
              </Button>
              <p className="ctrack__cta-note">
                Change your mind any time: your evidence carries over and the track rebuilds for the new role.
              </p>
            </Reveal>
          </div>
        </div>
      </div>
    </section>
  );
}
