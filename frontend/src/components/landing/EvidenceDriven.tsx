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

export default function EvidenceDriven() {
  return (
    <section id="evidence" className="evidence section section--subtle">
      <div className="container evidence__inner">
        <div className="evidence__copy">
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

          <div className="evidence__list">
            <div className="evidence__list-head">
              Future evidence sources — presentation only
            </div>
            <div className="evidence__chips">
              {evidence.map((e) => (
                <span key={e} className="evidence__chip">
                  {e}
                </span>
              ))}
            </div>
            <p className="evidence__hint">
              No integrations required today. Visual commitment to a verifiable
              future — when ready, your GitHub, Kaggle, and coursework become
              measurable signals.
            </p>
          </div>
        </div>

        <div className="evidence__visual" aria-hidden="true">
          <div className="evidence__mock">
            <div className="evidence__mock-header">
              <span className="evidence__mock-title">Evidence → Skills</span>
              <span className="evidence__mock-badge">Verified</span>
            </div>

            <div className="evidence__mock-rows">
              <div className="evidence__row">
                <div className="evidence__row-left">
                  <span className="evidence__icon evidence__icon--gh">◆</span>
                  <span className="evidence__row-label">
                    github.com/you/repo
                  </span>
                </div>
                <span className="evidence__row-pill evidence__row-pill--high">
                  High
                </span>
              </div>

              <div className="evidence__row">
                <div className="evidence__row-left">
                  <span className="evidence__icon evidence__icon--lc">◇</span>
                  <span className="evidence__row-label">
                    LeetCode · 340 solved
                  </span>
                </div>
                <span className="evidence__row-pill">Medium</span>
              </div>

              <div className="evidence__row">
                <div className="evidence__row-left">
                  <span className="evidence__icon evidence__icon--kg">○</span>
                  <span className="evidence__row-label">
                    Kaggle · 2 competitions
                  </span>
                </div>
                <span className="evidence__row-pill">Strong</span>
              </div>

              <div className="evidence__row">
                <div className="evidence__row-left">
                  <span className="evidence__icon">◎</span>
                  <span className="evidence__row-label">
                    Coursework · DBMS, DSA
                  </span>
                </div>
                <span className="evidence__row-pill evidence__row-pill--muted">
                  Linked
                </span>
              </div>
            </div>

            <div className="evidence__mock-footer">
              <div className="evidence__footer-label">Signal strength</div>
              <div className="evidence__footer-bars">
                <span style={{ width: "82%" }} />
                <span style={{ width: "64%" }} />
                <span style={{ width: "48%" }} />
              </div>
            </div>
          </div>

          <div className="evidence__note">
            <strong>Principle:</strong> Every claim maps to an artifact. No
            artifact, no score.
          </div>
        </div>
      </div>
    </section>
  );
}
