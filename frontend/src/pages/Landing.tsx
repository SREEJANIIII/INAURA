import Navbar from "../components/layout/Navbar";
import Footer from "../components/layout/Footer";
import Hero from "../components/landing/Hero";
import Problem from "../components/landing/Problem";
import HowItWorks from "../components/landing/HowItWorks";
import EvidenceDriven from "../components/landing/EvidenceDriven";
import IndustryAlignment from "../components/landing/IndustryAlignment";
import FinalCTA from "../components/landing/FinalCTA";

export default function Landing() {
  return (
    <div>
      <Navbar />
      <main>
        <Hero />
        <Problem />
        <HowItWorks />
        <EvidenceDriven />
        <IndustryAlignment />
        <FinalCTA />
      </main>
      <Footer />
    </div>
  );
}
