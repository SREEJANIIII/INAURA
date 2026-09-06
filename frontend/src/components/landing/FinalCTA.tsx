import { useNavigate } from "react-router-dom";
import Button from "../ui/Button";
import "./FinalCTA.css";

export default function FinalCTA() {
  const navigate = useNavigate();
  return (
    <section id="final-cta" className="final section section--dark">
      <div className="container final__inner">
        <div className="final__card">
          <div className="eyebrow final__eyebrow">Bridging skills to industry.</div>
          <h2 className="final__title">
            Your career path
            <br />
            shouldn&rsquo;t be guesswork.
          </h2>
          <p className="final__desc">
            Start with clarity. Build with evidence. Progress with a roadmap
            that’s yours — not generic.
          </p>

          <div className="final__actions">
            <Button
              variant="accent"
              size="lg"
              onClick={() => navigate("/signup")}
            >
              Start with INAURA
            </Button>
            <a href="#how-it-works" className="final__secondary">
              See how it works
            </a>
          </div>

          <div className="final__meta">
            <span>Free to start</span>
            <span className="final__dot" aria-hidden="true" />
            <span>No guesswork</span>
            <span className="final__dot" aria-hidden="true" />
            <span>Evidence-driven</span>
          </div>
        </div>

        <div className="final__subtle">
          <span className="final__subtle-line" />
          <span>
            INAURA is in early access — landing experience only. Product
            features (scoring, roadmap, integrations) are next.
          </span>
        </div>
      </div>
    </section>
  );
}
