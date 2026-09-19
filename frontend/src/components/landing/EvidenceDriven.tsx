import { motion, useTransform } from "framer-motion";
import { Grow, Reveal, Stagger, StaggerItem, hold, useProgress, useStill } from "./scroll";
import ReadinessPipeline from "./ReadinessPipeline";
import "./shared.css";
import "./EvidenceDriven.css";

const evidence = ["GitHub", "LeetCode", "Certifications", "Kaggle", "LinkedIn", "Projects", "Courses", "Resume"];

const ROWS = [
  { icon: "◆", tone: "gh", label: "github.com/you/portfolio", skills: "React · TypeScript", pill: "High", pillTone: "high" },
  { icon: "◇", tone: "lc", label: "LeetCode · 340 solved", skills: "Data structures · Algorithms", pill: "Medium" },
  { icon: "○", tone: "kg", label: "Kaggle · 2 competitions", skills: "Python · Data analysis", pill: "Strong" },
  { icon: "◎", tone: "", label: "Coursework · DBMS, DSA", skills: "SQL · Fundamentals", pill: "Linked", pillTone: "muted" },
];

const SIGNAL = [82, 64, 48];

export default function EvidenceDriven() {
  const reduce = useStill();
  // The mock card starts tilted back and settles flat as it scrolls into place
  const { ref: visualRef, progress } = useProgress(["start 0.95", "center 0.55"]);
  const rotateX = useTransform(progress, [0, 1], [16, 0]);
  const scale = useTransform(progress, [0, 1], [0.88, 1]);
  const y = useTransform(progress, [0, 1], [70, 0]);
  const opacity = useTransform(progress, ...hold(0, 0.5, 0.3, 1));
  return (
    <section id="evidence" className="evidence section">
      <div className="container">
        <div className="evidence__inner">
          <div className="evidence__copy">
            <Reveal>
              <div className="eyebrow">Evidence-driven — not self-reported</div>
              <h2 className="lp-title evidence__title">
                Don&rsquo;t just claim
                <br />
                your skills.
                <br />
                <span className="is-accent">Show them.</span>
              </h2>
              <p className="lp-lede">
                Your profile is built from evidence — what you&rsquo;ve built, learned and shipped.
              </p>
            </Reveal>

            {/* The question INAURA changes */}
            <Stagger className="evidence__ask" gap={0.15}>
              <StaggerItem className="evidence__ask-row evidence__ask-row--old" y={14}>
                <span className="evidence__ask-who">Most profiles ask</span>
                <q>What skills do you say you have?</q>
              </StaggerItem>
              <StaggerItem className="evidence__ask-row evidence__ask-row--new" y={14}>
                <span className="evidence__ask-who">INAURA asks</span>
                <q>What evidence demonstrates those skills?</q>
              </StaggerItem>
            </Stagger>

            <div className="evidence__list">
              <div className="evidence__list-head">Evidence INAURA reads</div>
              <Stagger className="evidence__chips" gap={0.05}>
                {evidence.map((e) => (
                  <StaggerItem key={e} className="evidence__chip" y={14}>
                    {e}
                  </StaggerItem>
                ))}
              </Stagger>
              <p className="evidence__hint">
                Link your profiles or upload files. Each source becomes a measurable signal, weighted by
                how strongly it proves a skill.
              </p>
            </div>
          </div>

          <div className="evidence__visual" aria-hidden="true" ref={visualRef}>
            <motion.div
              className="evidence__mock"
              style={reduce ? undefined : { rotateX, scale, y, opacity, transformPerspective: 1200 }}
            >
              <div className="evidence__mock-header">
                <span className="evidence__mock-title">Evidence → Skills</span>
                <span className="evidence__mock-badge">Verified</span>
              </div>

              <Stagger className="evidence__mock-rows" gap={0.14} amount={0.4}>
                {ROWS.map((r) => (
                  <StaggerItem key={r.label} className="evidence__row" y={18}>
                    <div className="evidence__row-left">
                      <span className={`evidence__icon${r.tone ? ` evidence__icon--${r.tone}` : ""}`}>{r.icon}</span>
                      <span className="evidence__row-text">
                        <span className="evidence__row-label">{r.label}</span>
                        <span className="evidence__row-skills">→ {r.skills}</span>
                      </span>
                    </div>
                    <span className={`evidence__row-pill${r.pillTone ? ` evidence__row-pill--${r.pillTone}` : ""}`}>{r.pill}</span>
                  </StaggerItem>
                ))}
              </Stagger>

              <div className="evidence__mock-footer">
                <div className="evidence__footer-label">Signal strength</div>
                <div className="evidence__footer-bars">
                  {SIGNAL.map((w, i) => (
                    <span key={w} className="evidence__footer-bar">
                      <Grow width={w} className="evidence__footer-fill" delay={0.3 + i * 0.15} />
                    </span>
                  ))}
                </div>
              </div>
            </motion.div>

            <div className="evidence__note">
              <strong>Principle:</strong> Every claim maps to an artifact. No artifact, no score.
            </div>
          </div>
        </div>

        {/* The whole chain, from evidence to a readiness score; its stages arrive as it scrolls in */}
        <div className="evidence__pipeline">
          <ReadinessPipeline />
        </div>
      </div>
    </section>
  );
}
