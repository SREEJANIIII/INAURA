import Navbar from "../components/layout/Navbar";
import Footer from "../components/layout/Footer";
import { useNavigate } from "react-router-dom";
import LiquidMetalHero from "@/components/ui/liquid-metal-hero";
import { MotionSafe } from "../components/landing/scroll";
import Problem from "../components/landing/Problem";
import HowItWorks from "../components/landing/HowItWorks";
import EvidenceDriven from "../components/landing/EvidenceDriven";
import IndustryAlignment from "../components/landing/IndustryAlignment";
import FinalCTA from "../components/landing/FinalCTA";

export default function Landing() {
  const navigate = useNavigate();
  return (
    <div className="landing">
      <Navbar />
      <main>
        <MotionSafe>
          <LiquidMetalHero
            background="section"
            badge="Bridging skills to industry"
            title="Know where you stand. Know where you’re going."
            subtitle="INAURA analyzes your skills, experience and learning evidence against real industry requirements — then builds a personalized path toward your career goal."
            primaryCtaLabel="Start Your Journey"
            onPrimaryCtaClick={() => navigate("/signup")}
            secondaryCtaLabel="See How It Works"
            onSecondaryCtaClick={() => document.getElementById("how-it-works")?.scrollIntoView({ behavior: "smooth" })}
            features={["Evidence-driven", "Industry-aligned", "No guesswork"]}
          />
          <Problem />
          <HowItWorks />
          <EvidenceDriven />
          <IndustryAlignment />
          <FinalCTA />
        </MotionSafe>
      </main>
      <Footer />
    </div>
  );
}
