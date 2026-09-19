import { Fragment, type ReactNode } from "react";
import { motion, useTransform, type MotionValue } from "framer-motion";
import { EASE, Grow, hold, useIsWide, useProgress, useStill } from "./scroll";
import "./shared.css";
import "./ReadinessPipeline.css";

const STAGES = 5;
/** Matches ReadinessPipeline.css: wider than this, the stages sit side by side */
const ACROSS = "(min-width: 1081px)";
const PARTS = STAGES * 2 - 1; // five stages with four arrows between them

/**
 * One piece of the pipeline. Across a wide screen the pieces arrive in order as the pipeline
 * scrolls through; stacked on a narrow one, each piece rises in as it reaches the screen.
 */
function Part({
  i,
  progress,
  className,
  role,
  hidden,
  children,
}: {
  i: number;
  progress: MotionValue<number>;
  className: string;
  role?: string;
  hidden?: boolean;
  children: ReactNode;
}) {
  const reduce = useStill();
  const wide = useIsWide(ACROSS);
  const start = (i / PARTS) * 0.85;
  const opacity = useTransform(progress, ...hold(start, start + 0.12, 0, 1));
  const y = useTransform(progress, ...hold(start, start + 0.12, 30, 0));
  if (reduce || !wide) {
    return (
      <motion.div
        className={className}
        role={role}
        aria-hidden={hidden || undefined}
        initial={reduce ? false : { opacity: 0, y: 24 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, amount: 0.4 }}
        transition={{ duration: 0.7, ease: EASE }}
      >
        {children}
      </motion.div>
    );
  }
  return (
    <motion.div className={className} role={role} aria-hidden={hidden || undefined} style={{ opacity, y }}>
      {children}
    </motion.div>
  );
}

type Stage = { label: string; tone?: "accent" | "gap" | "final"; body: ReactNode };

// The same example student as the rest of the page: aiming for Frontend Developer
const stages: Stage[] = [
  {
    label: "Evidence",
    body: (
      <>
        <div className="pipe__card-title">4 sources linked</div>
        <ul className="pipe__rows">
          <li>
            <span>GitHub</span>
            <em>12 repos</em>
          </li>
          <li>
            <span>Projects</span>
            <em>5</em>
          </li>
          <li>
            <span>Certificates</span>
            <em>3</em>
          </li>
          <li>
            <span>LeetCode</span>
            <em>340 solved</em>
          </li>
        </ul>
      </>
    ),
  },
  {
    label: "Verified skills",
    body: (
      <>
        <div className="pipe__card-title">From your evidence</div>
        <ul className="pipe__rows">
          <li>
            <span>JavaScript</span>
            <em className="is-high">High</em>
          </li>
          <li>
            <span>Git</span>
            <em className="is-high">High</em>
          </li>
          <li>
            <span>React</span>
            <em>Medium</em>
          </li>
          <li>
            <span>TypeScript</span>
            <em className="is-low">Low</em>
          </li>
        </ul>
      </>
    ),
  },
  {
    label: "Industry requirements",
    tone: "accent",
    body: (
      <>
        <div className="pipe__card-title">Frontend Developer benchmark</div>
        <ul className="lp-chips pipe__chips">
          <li className="lp-chip">React</li>
          <li className="lp-chip">TypeScript</li>
          <li className="lp-chip">Testing</li>
          <li className="lp-chip">Accessibility</li>
          <li className="lp-chip">Git</li>
        </ul>
      </>
    ),
  },
  {
    label: "Skill gaps",
    tone: "gap",
    body: (
      <>
        <div className="pipe__card-title">Prioritized</div>
        <ul className="pipe__rows pipe__rows--gap">
          <li>
            <span>TypeScript</span>
            <em className="is-high">High</em>
          </li>
          <li>
            <span>React · advanced</span>
            <em className="is-high">High</em>
          </li>
          <li>
            <span>Testing</span>
            <em>Medium</em>
          </li>
        </ul>
      </>
    ),
  },
  {
    label: "Career readiness",
    tone: "final",
    body: (
      <>
        <div className="pipe__card-title">Frontend Developer</div>
        <div className="pipe__score">
          58<span>%</span>
        </div>
        <span className="lp-bar pipe__bar">
          <Grow width={58} className="lp-bar__fill pipe__bar-fill" delay={0.3} />
        </span>
        <div className="pipe__next">Next: React → Advanced</div>
      </>
    ),
  },
];

/**
 * Evidence → verified skills → industry requirements → skill gaps → career readiness,
 * as one dashboard whose stages arrive in order while it scrolls through the screen.
 */
export default function ReadinessPipeline() {
  const { ref, progress } = useProgress(["start 0.85", "end 0.6"]);
  return (
    <div id="industry" className="lp-panel pipe">
      <div className="lp-panel__head">
        <div>
          <span className="lp-kicker">Readiness pipeline</span>
          <span className="lp-panel-title">From what you&rsquo;ve done to how ready you are</span>
        </div>
        <span className="pipe__head-note">Example · Frontend Developer</span>
      </div>

      <div className="pipe__stages" role="list" ref={ref}>
        {stages.map((stage, s) => (
          <Fragment key={stage.label}>
            {s > 0 && (
              <Part i={s * 2 - 1} progress={progress} className="pipe__arrow" hidden>
                <span className="pipe__arrow-line" />
                <span className="pipe__arrow-dot" />
              </Part>
            )}
            <Part i={s * 2} progress={progress} className="pipe__stage" role="listitem">
              <div className="pipe__stage-head">
                <span className={`pipe__stage-num${stage.tone ? ` pipe__stage-num--${stage.tone}` : ""}`}>
                  {String(s + 1).padStart(2, "0")}
                </span>
                <span className="pipe__stage-label">{stage.label}</span>
              </div>
              <div className={`pipe__card${stage.tone ? ` pipe__card--${stage.tone}` : ""}`}>{stage.body}</div>
            </Part>
          </Fragment>
        ))}
      </div>
    </div>
  );
}
