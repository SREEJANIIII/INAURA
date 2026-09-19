import { motion } from "framer-motion";
import { Check } from "lucide-react";
import { EASE, Reveal, Stagger, StaggerItem, useStill } from "./scroll";
import "./shared.css";
import "./BeforeAfter.css";

const WITHOUT = ["Random courses", "Random certifications", "Scattered projects", "Unclear skill gaps", "No clear direction"];

// The same example student as the rest of the page, so each step shows what it produced
const WITH = [
  { step: "Evidence", meta: "12 repos · 5 projects" },
  { step: "Skill analysis", meta: "6 verified skills" },
  { step: "Industry requirements", meta: "Frontend Developer" },
  { step: "Prioritized gaps", meta: "3 focus areas" },
  { step: "Career Track", meta: "58% ready" },
  { step: "Opportunities", meta: "Matched to readiness" },
];

export default function BeforeAfter() {
  const reduce = useStill();
  return (
    <section id="why-inaura" className="compare section">
      <div className="container">
        <Reveal className="lp-head lp-head--center">
          <div className="eyebrow">Why INAURA</div>
          <h2 className="lp-title compare__title">
            Stop learning randomly.
            <br />
            <span className="is-accent">Start moving intentionally.</span>
          </h2>
          <p className="lp-lede">
            The same effort, pointed in one direction. Here&rsquo;s the difference a clear path makes.
          </p>
        </Reveal>

        <div className="compare__grid">
          <Reveal className="compare__side compare__side--without" y={32}>
            <div className="compare__head">
              <span className="compare__label">Without INAURA</span>
              <span className="compare__tag">Scattered</span>
            </div>
            <Stagger className="compare__scatter" role="list" gap={0.1}>
              {WITHOUT.map((item) => (
                <StaggerItem key={item} className="compare__loose" role="listitem" y={12}>
                  {item}
                </StaggerItem>
              ))}
            </Stagger>
            <p className="compare__foot">Plenty of effort. No way to tell if it&rsquo;s working.</p>
          </Reveal>

          <Reveal className="compare__side compare__side--with" y={32} delay={0.1}>
            <div className="compare__head">
              <span className="compare__label">With INAURA</span>
              <span className="compare__tag compare__tag--on">Structured</span>
            </div>
            <div className="compare__path">
              {/* The line through the steps draws itself in as they arrive */}
              <motion.span
                className="compare__line"
                aria-hidden="true"
                initial={reduce ? false : { scaleY: 0 }}
                whileInView={{ scaleY: 1 }}
                viewport={{ once: true, amount: 0.4 }}
                transition={{ duration: 1.4, ease: EASE, delay: 0.2 }}
              />
              <Stagger className="compare__steps" role="list" gap={0.14} amount={0.4}>
                {WITH.map((w) => (
                  <StaggerItem key={w.step} className="compare__step" role="listitem" y={12}>
                    <span className="compare__node" aria-hidden="true">
                      <Check />
                    </span>
                    <span className="compare__step-name">{w.step}</span>
                    <span className="compare__step-meta">{w.meta}</span>
                  </StaggerItem>
                ))}
              </Stagger>
            </div>
            <p className="compare__foot compare__foot--on">Every step builds on the last, and you can see it happening.</p>
          </Reveal>
        </div>
      </div>
    </section>
  );
}
