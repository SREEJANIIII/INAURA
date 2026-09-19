import { useRef } from "react";
import { motion, useScroll, useTransform, type MotionValue } from "framer-motion";
import { Reveal, hold, useIsWide, useStill } from "./scroll";
import "./HowItWorks.css";

const steps = [
  {
    n: "01",
    title: "Understand You",
    desc: "Your goals, background, interests and constraints — captured cleanly at the start.",
  },
  {
    n: "02",
    title: "Analyze Your Evidence",
    desc: "Projects, coursework, experience and learning history mapped to actual skills.",
  },
  {
    n: "03",
    title: "Map Industry Requirements",
    desc: "Curated role benchmarks show what great looks like — not generic advice.",
  },
  {
    n: "04",
    title: "Build Your Roadmap",
    desc: "A sequenced, personalized plan that closes your gaps in the right order.",
  },
  {
    n: "05",
    title: "Track Your Progress",
    desc: "Evidence-linked progress that’s measurable, not just motivational.",
  },
];

// The steps finish playing a little before the pinned scene lets go
const PLAY = 0.88;

function Card({ step, fill }: { step: (typeof steps)[number]; fill?: MotionValue<number> }) {
  return (
    <div className="how__card">
      <div className="how__num">{step.n}</div>
      <h3 className="how__card-title">{step.title}</h3>
      <p className="how__card-desc">{step.desc}</p>
      <div className="how__bar" aria-hidden="true">
        <motion.span style={fill ? { scaleX: fill } : undefined} />
      </div>
    </div>
  );
}

/** One step: lights up as the scroll reaches it, and its bar fills while it's the current step */
function Step({ step, i, progress }: { step: (typeof steps)[number]; i: number; progress: MotionValue<number> }) {
  const start = (i / steps.length) * PLAY;
  const end = ((i + 1) / steps.length) * PLAY;
  const fill = useTransform(progress, ...hold(start, end, 0, 1));
  // Lights up just before its turn; the first step is lit from the start
  const opacity = useTransform(progress, ...hold(start - 0.1, start + 0.02, i === 0 ? 1 : 0.3, 1));
  const y = useTransform(progress, ...hold(start - 0.1, start + 0.02, i === 0 ? 0 : 24, 0));
  return (
    <motion.div className="lp-cell" role="listitem" style={{ opacity, y }}>
      <Card step={step} fill={fill} />
    </motion.div>
  );
}

function Header() {
  return (
    <Reveal className="how__header">
      <div className="eyebrow">How INAURA works</div>
      <h2 className="how__title">From evidence to employability.</h2>
      <p className="how__desc">
        Five clear steps — no black boxes. You always know what was
        evaluated, what’s missing, and what to do next.
      </p>
    </Reveal>
  );
}

function Note() {
  return (
    <div className="how__note">
      <span className="how__note-dot" />
      <p>
        Deterministic scoring + curated industry knowledge — intelligence
        without the AI theatre.
      </p>
    </div>
  );
}

/**
 * Wide screens: the section pins in place and the five steps play in order as you scroll.
 * Phones: no pinning (five cards don't fit one screen); the steps play as you scroll past.
 */
function Scene({ pinned }: { pinned: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({
    target: ref,
    offset: pinned ? ["start start", "end end"] : ["start 0.85", "end 0.6"],
  });
  return (
    <div ref={ref} className={pinned ? "how__track how__track--pinned" : "how__track"}>
      <div className="how__stage">
        <div className="container">
          <Header />
          <div className="how__grid" role="list">
            {steps.map((s, i) => (
              <Step key={s.n} step={s} i={i} progress={scrollYProgress} />
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
          <div className="how__grid" role="list">
            {steps.map((s) => (
              <div key={s.n} className="lp-cell" role="listitem">
                <Card step={s} />
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
