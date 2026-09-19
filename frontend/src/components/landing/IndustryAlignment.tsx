import type { ReactNode } from "react";
import { motion, useTransform, type MotionValue } from "framer-motion";
import { EASE, Reveal, hold, useProgress, useStill } from "./scroll";
import "./IndustryAlignment.css";

const PARTS = 7; // four stages with three arrows between them

/** One piece of the pipeline, revealed in order as the pipeline scrolls through the screen */
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
  const start = (i / PARTS) * 0.85;
  const opacity = useTransform(progress, ...hold(start, start + 0.14, 0, 1));
  const y = useTransform(progress, ...hold(start, start + 0.14, 36, 0));
  return (
    <motion.div
      className={className}
      role={role}
      aria-hidden={hidden || undefined}
      style={reduce ? undefined : { opacity, y }}
    >
      {children}
    </motion.div>
  );
}

/** A meter that fills from the left the first time it's seen */
function Meter({ width, accent }: { width: string; accent?: boolean }) {
  const reduce = useStill();
  return (
    <div className="industry__meter">
      <motion.div
        className={accent ? "industry__meter-fill industry__meter-fill--accent" : "industry__meter-fill"}
        style={{ width, transformOrigin: "left center" }}
        initial={reduce ? false : { scaleX: 0 }}
        whileInView={{ scaleX: 1 }}
        viewport={{ once: true, amount: 1 }}
        transition={{ duration: 1.2, ease: EASE, delay: 0.2 }}
      />
    </div>
  );
}

export default function IndustryAlignment() {
  const { ref, progress } = useProgress(["start 0.85", "end 0.55"]);
  return (
    <section id="industry" className="industry section">
      <div className="container">
        <Reveal className="industry__header">
          <div className="eyebrow">Industry alignment</div>
          <h2 className="industry__title">
            From current skills
            <br />
            to career readiness.
          </h2>
          <p className="industry__desc">
            A clear pipeline that connects what you have to what the role
            requires — with the gap and the roadmap made explicit.
          </p>
        </Reveal>

        <div className="industry__pipeline" role="list" ref={ref}>
          <Part i={0} progress={progress} className="industry__stage" role="listitem">
            <div className="industry__stage-head">
              <span className="industry__stage-num">01</span>
              <span className="industry__stage-label">Your current skills</span>
            </div>
            <div className="industry__card">
              <div className="industry__card-title">Evidence-mapped</div>
              <div className="industry__chips">
                <span>Python</span>
                <span>DSA</span>
                <span>SQL</span>
                <span>Git</span>
              </div>
              <Meter width="62%" />
              <div className="industry__meter-label">Coverage 62%</div>
            </div>
          </Part>

          <Part i={1} progress={progress} className="industry__arrow" hidden>
            <span className="industry__arrow-line" />
            <span className="industry__arrow-dot" />
          </Part>

          <Part i={2} progress={progress} className="industry__stage" role="listitem">
            <div className="industry__stage-head">
              <span className="industry__stage-num">02</span>
              <span className="industry__stage-label">Industry requirements</span>
            </div>
            <div className="industry__card industry__card--accent">
              <div className="industry__card-title">Role benchmark</div>
              <div className="industry__chips">
                <span>System Design</span>
                <span>APIs</span>
                <span>Testing</span>
                <span>Cloud</span>
              </div>
              <Meter width="100%" accent />
              <div className="industry__meter-label">Benchmark 100%</div>
            </div>
          </Part>

          <Part i={3} progress={progress} className="industry__arrow" hidden>
            <span className="industry__arrow-line" />
            <span className="industry__arrow-dot" />
          </Part>

          <Part i={4} progress={progress} className="industry__stage" role="listitem">
            <div className="industry__stage-head">
              <span className="industry__stage-num industry__stage-num--gap">
                03
              </span>
              <span className="industry__stage-label">Skill gap</span>
            </div>
            <div className="industry__card industry__card--gap">
              <div className="industry__card-title">Priority gaps</div>
              <ul className="industry__gap">
                <li>
                  <span>System Design</span>
                  <em>High</em>
                </li>
                <li>
                  <span>API Design</span>
                  <em>Medium</em>
                </li>
                <li>
                  <span>Cloud Basics</span>
                  <em>Medium</em>
                </li>
              </ul>
              <div className="industry__gap-note">3 focus areas</div>
            </div>
          </Part>

          <Part i={5} progress={progress} className="industry__arrow" hidden>
            <span className="industry__arrow-line" />
            <span className="industry__arrow-dot" />
          </Part>

          <Part i={6} progress={progress} className="industry__stage" role="listitem">
            <div className="industry__stage-head">
              <span className="industry__stage-num industry__stage-num--final">
                04
              </span>
              <span className="industry__stage-label">Personalized roadmap</span>
            </div>
            <div className="industry__card industry__card--final">
              <div className="industry__card-title">Sequenced plan</div>
              <div className="industry__timeline">
                <span>
                  <i /> Week 1–3 · Foundations
                </span>
                <span>
                  <i /> Week 4–8 · Build
                </span>
                <span>
                  <i /> Week 9–12 · Ship & Review
                </span>
              </div>
              <div className="industry__roadmap-meta">12 weeks · 3 milestones</div>
            </div>
          </Part>
        </div>

        <Reveal className="industry__bottom">
          <p>
            The connection is explicit: your evidence → industry standard →
            precise gaps → ordered roadmap. No vague advice.
          </p>
        </Reveal>
      </div>
    </section>
  );
}
