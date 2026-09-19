import { useNavigate } from "react-router-dom";
import Button from "../ui/app-button";
import { motion, useTransform } from "framer-motion";
import { Reveal, hold, useProgress, useStill } from "./scroll";
import "./FinalCTA.css";

export default function FinalCTA() {
  const navigate = useNavigate();
  const reduce = useStill();
  // The card grows to full size as it arrives, like a product coming forward
  const { ref, progress } = useProgress(["start 1", "start 0.3"]);
  const scale = useTransform(progress, [0, 1], [0.84, 1]);
  const y = useTransform(progress, [0, 1], [80, 0]);
  const opacity = useTransform(progress, ...hold(0, 0.6, 0.2, 1));
  return (
    <section id="final-cta" className="final section section--dark dark">
      <div className="container final__inner" ref={ref}>
        <motion.div className="final__card" style={reduce ? undefined : { scale, y, opacity }}>
          <Reveal>
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
          </Reveal>
        </motion.div>

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
