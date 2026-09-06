import { useNavigate } from "react-router-dom";
import Button from "../ui/Button";
import "./Hero.css";

export default function Hero() {
  const navigate = useNavigate();
  return (
    <section className="hero">
      <div className="container hero__inner">
        <div className="hero__content">
          <div className="eyebrow eyebrow--accent hero__eyebrow">
            Bridging skills to industry.
          </div>

          <h1 className="hero__title">
            Know where
            <br />
            you stand.
            <br />
            <span className="hero__accent">Know where</span>
            <br />
            you&rsquo;re going.
          </h1>

          <p className="hero__desc">
            INAURA analyzes your skills, experience and learning evidence
            against real industry requirements — then builds a personalized
            path toward your career goal.
          </p>

          <div className="hero__ctas">
            <Button
              variant="primary"
              size="lg"
              onClick={() => navigate("/signup")}
            >
              Start Your Journey
            </Button>
            <a href="#how-it-works" className="hero__secondary">
              See How It Works
              <span aria-hidden="true" className="hero__arrow">
                →
              </span>
            </a>
          </div>

          <div className="hero__proof">
            <span className="hero__proof-item">
              <span className="hero__proof-dot" />
              Evidence-driven
            </span>
            <span className="hero__proof-item">
              <span className="hero__proof-dot" />
              Industry-aligned
            </span>
            <span className="hero__proof-item">
              <span className="hero__proof-dot" />
              No guesswork
            </span>
          </div>
        </div>

        <div className="hero__visual" aria-hidden="true">
          <div className="hero__card">
            <div className="hero__card-header">
              <span className="hero__card-label">Progress Pipeline</span>
              <span className="hero__card-badge">Live view</span>
            </div>

            <ol className="hero__pipeline">
              <li className="hero__step hero__step--active">
                <div className="hero__step-dot">
                  <span />
                </div>
                <div className="hero__step-body">
                  <div className="hero__step-title">Current Skills</div>
                  <div className="hero__step-meta">Your evidence</div>
                </div>
                <div className="hero__step-value">64%</div>
              </li>

              <li className="hero__step">
                <div className="hero__step-dot">
                  <span />
                </div>
                <div className="hero__step-body">
                  <div className="hero__step-title">Industry Requirements</div>
                  <div className="hero__step-meta">Role benchmark</div>
                </div>
                <div className="hero__step-value">—</div>
              </li>

              <li className="hero__step hero__step--gap">
                <div className="hero__step-dot hero__step-dot--gap">
                  <span />
                </div>
                <div className="hero__step-body">
                  <div className="hero__step-title">Skill Gap</div>
                  <div className="hero__step-meta">3 priority areas</div>
                </div>
                <div className="hero__step-bars" aria-hidden="true">
                  <span style={{ width: "42%" }} />
                  <span style={{ width: "68%" }} />
                  <span style={{ width: "30%" }} />
                </div>
              </li>

              <li className="hero__step">
                <div className="hero__step-dot">
                  <span />
                </div>
                <div className="hero__step-body">
                  <div className="hero__step-title">Roadmap</div>
                  <div className="hero__step-meta">Personalized sequence</div>
                </div>
                <div className="hero__step-value hero__step-value--accent">
                  12 weeks
                </div>
              </li>

              <li className="hero__step hero__step--final">
                <div className="hero__step-dot hero__step-dot--final">
                  <span />
                </div>
                <div className="hero__step-body">
                  <div className="hero__step-title">Career Readiness</div>
                  <div className="hero__step-meta">Measurable progress</div>
                </div>
                <div className="hero__step-value hero__step-value--final">
                  94%
                </div>
              </li>
            </ol>

            <div className="hero__progress">
              <div className="hero__progress-track">
                <div className="hero__progress-fill" />
              </div>
              <div className="hero__progress-labels">
                <span>0%</span>
                <span>Industry ready</span>
                <span>100%</span>
              </div>
            </div>
          </div>

          <div className="hero__glow" aria-hidden="true" />
        </div>
      </div>
    </section>
  );
}
