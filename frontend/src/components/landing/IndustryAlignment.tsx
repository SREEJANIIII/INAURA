import "./IndustryAlignment.css";

export default function IndustryAlignment() {
  return (
    <section id="industry" className="industry section">
      <div className="container">
        <div className="industry__header">
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
        </div>

        <div className="industry__pipeline" role="list">
          <div className="industry__stage" role="listitem">
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
              <div className="industry__meter">
                <div className="industry__meter-fill" style={{ width: "62%" }} />
              </div>
              <div className="industry__meter-label">Coverage 62%</div>
            </div>
          </div>

          <div className="industry__arrow" aria-hidden="true">
            <span className="industry__arrow-line" />
            <span className="industry__arrow-dot" />
          </div>

          <div className="industry__stage" role="listitem">
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
              <div className="industry__meter">
                <div
                  className="industry__meter-fill industry__meter-fill--accent"
                  style={{ width: "100%" }}
                />
              </div>
              <div className="industry__meter-label">Benchmark 100%</div>
            </div>
          </div>

          <div className="industry__arrow" aria-hidden="true">
            <span className="industry__arrow-line" />
            <span className="industry__arrow-dot" />
          </div>

          <div className="industry__stage" role="listitem">
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
          </div>

          <div className="industry__arrow" aria-hidden="true">
            <span className="industry__arrow-line" />
            <span className="industry__arrow-dot" />
          </div>

          <div className="industry__stage" role="listitem">
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
          </div>
        </div>

        <div className="industry__bottom">
          <p>
            The connection is explicit: your evidence → industry standard →
            precise gaps → ordered roadmap. No vague advice.
          </p>
        </div>
      </div>
    </section>
  );
}
