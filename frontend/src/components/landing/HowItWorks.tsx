import { useRef, type CSSProperties } from "react";
import { motion, useScroll, useTransform, type MotionValue } from "framer-motion";
import { Reveal, hold, useIsWide, useStill } from "./scroll";
import "./shared.css";
import "./HowItWorks.css";

const steps = [
  {
    n: "01",
    title: "Understand You",
    desc: "Collect your skills, projects, certifications, experience and learning evidence.",
    out: "Your starting profile",
  },
  {
    n: "02",
    title: "Analyze Your Evidence",
    desc: "Analyze what you have actually built, learned and demonstrated.",
    out: "Verified skills",
  },
  {
    n: "03",
    title: "Map Industry Requirements",
    desc: "Compare your current profile against the requirements of your target role.",
    out: "Role benchmark",
  },
  {
    n: "04",
    title: "Build Your Roadmap",
    desc: "Identify skill gaps and create a prioritized learning and project roadmap.",
    out: "Prioritized roadmap",
  },
  {
    n: "05",
    title: "Track Your Progress",
    desc: "Continuously track progress and update your career path.",
    out: "A live Career Track",
  },
];

type StepData = (typeof steps)[number];

// The steps finish playing a little before the pinned scene lets go
const PLAY = 0.88;

/**
 * One step on the path. Its number lights up when the scroll reaches it (--lit), and the
 * line to the next step draws itself while it's the current step (--draw). Both are 0–1.
 */
function Step({ step, last, lit, draw }: { step: StepData; last: boolean; lit: number | MotionValue<number>; draw: number | MotionValue<number> }) {
  return (
    <motion.div
      className="how__step"
      style={{ "--lit": lit, "--draw": draw } as unknown as CSSProperties}
    >
      <div className="how__marker" aria-hidden="true">
        {!last && (
          <span className="how__line">
            <span className="how__line-fill" />
          </span>
        )}
        <span className="how__node">{step.n}</span>
      </div>
      <div className="lp-card how__card">
        <h3 className="how__card-title">{step.title}</h3>
        <p className="how__card-desc">{step.desc}</p>
        <div className="how__out">
          <span className="how__out-label">Output</span>
          {step.out}
        </div>
      </div>
    </motion.div>
  );
}

function ScrollStep({ step, i, progress }: { step: StepData; i: number; progress: MotionValue<number> }) {
  const start = (i / steps.length) * PLAY;
  const next = ((i + 1) / steps.length) * PLAY;
  const lit = useTransform(progress, ...hold(start - 0.04, start + 0.02, i === 0 ? 1 : 0, 1));
  const draw = useTransform(progress, ...hold(start + 0.02, next, 0, 1));
  // Fades up just before its turn (and stays in line, so the path's line meets its number);
  // the first step is lit from the start
  const opacity = useTransform(progress, ...hold(start - 0.1, start + 0.02, i === 0 ? 1 : 0.35, 1));
  return (
    <motion.div className="lp-cell" role="listitem" style={{ opacity }}>
      <Step step={step} last={i === steps.length - 1} lit={lit} draw={draw} />
    </motion.div>
  );
}

function Header() {
  return (
    <Reveal className="lp-head">
      <div className="eyebrow">How INAURA works</div>
      <h2 className="lp-title">From evidence to employability.</h2>
      <p className="lp-lede">
        Five connected steps, no black boxes. You always know what was evaluated, what&rsquo;s
        missing, and what to do next.
      </p>
    </Reveal>
  );
}

function Note() {
  return (
    <div className="how__note">
      <span className="how__note-dot" />
      <p>Deterministic scoring + curated industry knowledge — intelligence without the AI theatre.</p>
    </div>
  );
}

/**
 * Wide screens: the section pins in place and the five steps play in order as you scroll.
 * Phones: no pinning (five steps don't fit one screen); the steps play as you scroll past.
 */
function Scene({ pinned }: { pinned: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({
    target: ref,
    offset: pinned ? ["start start", "end end"] : ["start 0.8", "end 0.55"],
  });
  return (
    <div ref={ref} className={pinned ? "how__track how__track--pinned" : "how__track"}>
      <div className="how__stage">
        <div className="container">
          <Header />
          <div className="how__path" role="list">
            {steps.map((s, i) => (
              <ScrollStep key={s.n} step={s} i={i} progress={scrollYProgress} />
            ))}
          </div>
          <Note />
        </div>
      </div>
    </div>
  );
}

export default function HowItWorks() {
  const wide = useIsWide();
  const reduce = useStill();
  return (
    <section id="how-it-works" className="how section">
      {reduce ? (
        <div className="container">
          <Header />
          <div className="how__path" role="list">
            {steps.map((s, i) => (
              <div key={s.n} className="lp-cell" role="listitem">
                <Step step={s} last={i === steps.length - 1} lit={1} draw={1} />
              </div>
            ))}
          </div>
          <Note />
        </div>
      ) : (
        // Remounts when the screen crosses the phone/desktop line, so the scroll mapping matches
        <Scene key={wide ? "pinned" : "flow"} pinned={wide} />
      )}
    </section>
  );
}
