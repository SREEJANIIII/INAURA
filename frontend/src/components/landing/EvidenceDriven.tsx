import { motion, useTransform } from "framer-motion";
import { EASE, Reveal, Stagger, StaggerItem, hold, useProgress, useStill } from "./scroll";
import "./EvidenceDriven.css";

const evidence = [
  "GitHub",
  "LeetCode",
  "Codeforces",
  "Kaggle",
  "LinkedIn",
  "Projects",
  "Courses",
  "Certifications",
  "College coursework",
  "Resume",
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
    <section id="evidence" className="evidence section section--subtle">
      <div className="container evidence__inner">
        <div className="evidence__copy">
          <Reveal>
          <div className="eyebrow">Evidence-driven — not self-reported</div>
          <h2 className="evidence__title">
            Don&rsquo;t just claim
            <br />
            your skills.
            <br />
            <span>Show them.</span>
          </h2>
          <p className="evidence__desc">
            INAURA connects what you&rsquo;ve actually built, learned and
            shipped — not just what you write on a resume. Evidence makes
            scoring credible and roadmaps actionable.
          </p>
          </Reveal>

          <div className="evidence__list">
            <div className="evidence__list-head">
              Future evidence sources — presentation only
            </div>
            <Stagger className="evidence__chips" gap={0.05}>
              {evidence.map((e) => (
                <StaggerItem key={e} className="evidence__chip" y={14}>
                  {e}
                </StaggerItem>
              ))}
            </Stagger>
            <p className="evidence__hint">
              No integrations required today. Visual commitment to a verifiable
              future — when ready, your GitHub, Kaggle, and coursework become
              measurable signals.
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
              <StaggerItem className="evidence__row" y={18}>
                <div className="evidence__row-left">
                  <span className="evidence__icon evidence__icon--gh">◆</span>
                  <span className="evidence__row-label">
                    github.com/you/repo
                  </span>
                </div>
                <span className="evidence__row-pill evidence__row-pill--high">
                  High
                </span>
              </StaggerItem>

              <StaggerItem className="evidence__row" y={18}>
                <div className="evidence__row-left">
                  <span className="evidence__icon evidence__icon--lc">◇</span>
                  <span className="evidence__row-label">
                    LeetCode · 340 solved
                  </span>
                </div>
                <span className="evidence__row-pill">Medium</span>
              </StaggerItem>

              <StaggerItem className="evidence__row" y={18}>
                <div className="evidence__row-left">
                  <span className="evidence__icon evidence__icon--kg">○</span>
                  <span className="evidence__row-label">
                    Kaggle · 2 competitions
                  </span>
                </div>
                <span className="evidence__row-pill">Strong</span>
              </StaggerItem>

              <StaggerItem className="evidence__row" y={18}>
                <div className="evidence__row-left">
                  <span className="evidence__icon">◎</span>
                  <span className="evidence__row-label">
                    Coursework · DBMS, DSA
                  </span>
                </div>
                <span className="evidence__row-pill evidence__row-pill--muted">
                  Linked
                </span>
              </StaggerItem>
            </Stagger>

            <div className="evidence__mock-footer">
              <div className="evidence__footer-label">Signal strength</div>
              <div className="evidence__footer-bars">
                {SIGNAL.map((w, i) => (
                  <motion.span
                    key={w}
                    style={{ width: `${w}%`, transformOrigin: "left center" }}
                    initial={reduce ? false : { scaleX: 0 }}
                    whileInView={{ scaleX: 1 }}
                    viewport={{ once: true, amount: 0.8 }}
                    transition={{ duration: 1.1, ease: EASE, delay: 0.3 + i * 0.15 }}
                  />
                ))}
              </div>
            </div>
          </motion.div>

          <div className="evidence__note">
            <strong>Principle:</strong> Every claim maps to an artifact. No
            artifact, no score.
          </div>
        </div>
      </div>
    </section>
  );
}
