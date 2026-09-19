import { useNavigate } from "react-router-dom";
import Button from "../ui/app-button";
import { motion, useTransform } from "framer-motion";
import { Reveal, hold, useProgress, useStill } from "./scroll";
import "./FinalCTA.css";

// Faint flowing lines behind the card, echoing the ribbons of the hero's liquid metal
const RIBBONS = [0, 14, 28, 42, 56];

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
          <svg className="final__ribbons" viewBox="0 0 880 420" preserveAspectRatio="none" aria-hidden="true">
            <defs>
              <linearGradient id="final-ribbon" x1="0" y1="0" x2="1" y2="0">
                <stop offset="0" stopColor="#818cf8" stopOpacity="0" />
                <stop offset="0.3" stopColor="#818cf8" />
                <stop offset="0.65" stopColor="#38bdf8" />
                <stop offset="1" stopColor="#c4b5fd" stopOpacity="0" />
              </linearGradient>
            </defs>
            {RIBBONS.map((dy, i) => (
              <path
                key={dy}
                d={`M-60 ${330 + dy} C 140 ${190 + dy}, 330 ${410 + dy}, 520 ${270 + dy} S 820 ${130 + dy}, 960 ${210 + dy}`}
                stroke="url(#final-ribbon)"
                strokeWidth={1.2}
                fill="none"
                opacity={0.55 - i * 0.08}
              />
            ))}
          </svg>

          <Reveal className="final__content">
            <div className="eyebrow final__eyebrow">Bridging skills to industry</div>
            <h2 className="final__title">
              Your career path
              <br />
              <span>shouldn&rsquo;t be guesswork.</span>
            </h2>
            <p className="final__desc">
              Start with clarity. Build with evidence. Progress with a roadmap that&rsquo;s yours — not
              generic.
            </p>

            <div className="final__actions">
              <Button variant="accent" size="lg" className="final__primary" onClick={() => navigate("/signup")}>
                Start with INAURA
              </Button>
              <Button variant="secondary" size="lg" asChild>
                <a href="#how-it-works">See How It Works</a>
              </Button>
            </div>

            <div className="final__meta">
              <span>No guesswork</span>
              <span className="final__dot" aria-hidden="true" />
              <span>Evidence-driven</span>
              <span className="final__dot" aria-hidden="true" />
              <span>Industry-aligned</span>
            </div>
          </Reveal>
        </motion.div>
      </div>
    </section>
  );
}
