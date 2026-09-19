// Section spacing and background bands, shared by every landing section
import "../components/ui/Section.css";
import Navbar from "../components/layout/Navbar";
import Footer from "../components/layout/Footer";
import { useNavigate } from "react-router-dom";
import LiquidMetalHero from "@/components/ui/liquid-metal-hero";
import { MotionSafe } from "../components/landing/scroll";
import HeroFlow from "../components/landing/HeroFlow";
import Problem from "../components/landing/Problem";
import HowItWorks from "../components/landing/HowItWorks";
import Features from "../components/landing/Features";
import EvidenceDriven from "../components/landing/EvidenceDriven";
import CareerTrackSection from "../components/landing/CareerTrackSection";
import Audience from "../components/landing/Audience";
import Opportunities from "../components/landing/Opportunities";
import BeforeAfter from "../components/landing/BeforeAfter";
import FinalCTA from "../components/landing/FinalCTA";

/*
 * One story, top to bottom: the problem → understand yourself → analyze your evidence →
 * identify skill gaps → build a Career Track → follow the roadmap → find opportunities →
 * why it's worth it. Sections run in the same order as the navbar's tabs.
 */
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
            title={
              <>
                Know where you stand.
                <br />
                Know where you&rsquo;re going.
              </>
            }
            subtitle="INAURA analyzes your skills, experience, projects, certifications and learning evidence against real industry requirements — then builds a personalized path toward your target career."
            primaryCtaLabel="Start Your Career Track"
            onPrimaryCtaClick={() => navigate("/signup")}
            secondaryCtaLabel="See How It Works"
            onSecondaryCtaClick={() => document.getElementById("how-it-works")?.scrollIntoView({ behavior: "smooth" })}
            preview={<HeroFlow />}
          />
          <Problem />
          <HowItWorks />
          <Features />
          <EvidenceDriven />
          <CareerTrackSection />
          <Audience />
          <Opportunities />
          <BeforeAfter />
          <FinalCTA />
        </MotionSafe>
      </main>
      <Footer />
    </div>
  );
}
