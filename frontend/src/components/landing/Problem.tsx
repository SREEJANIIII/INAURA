import type { LucideIcon } from "lucide-react";
import { Compass, Layers, ScanSearch, Shuffle } from "lucide-react";
import { Reveal, ScrubWords, Stagger, StaggerItem } from "./scroll";
import "./shared.css";
import "./Problem.css";

const items: { step: string; icon: LucideIcon; title: string; desc: string; effect: string }[] = [
  {
    step: "01",
    icon: Layers,
    title: "Too many choices",
    desc: "Courses, stacks, certifications and roles all compete for your time. Without a clear signal, everything feels equally urgent.",
    effect: "Effort spread thin",
  },
  {
    step: "02",
    icon: Compass,
    title: "Unclear priorities",
    desc: "It’s hard to tell which skill moves you closest to the role you want, so what to learn next becomes a guess.",
    effect: "Progress feels random",
  },
  {
    step: "03",
    icon: ScanSearch,
    title: "Hidden skill gaps",
    desc: "What’s missing rarely shows on a resume or a course certificate. The gaps that matter stay invisible until an interview finds them.",
    effect: "Surprises in interviews",
  },
  {
    step: "04",
    icon: Shuffle,
    title: "Unstructured preparation",
    desc: "Tutorials without a sequence and projects without a goal: hard work that can’t be measured or shown.",
    effect: "Little to show for it",
  },
];

export default function Problem() {
  return (
    <section id="problem" className="problem section section--subtle">
      <div className="container">
        <Reveal className="lp-head lp-head--center">
          <div className="eyebrow">The reality for most learners</div>
          <h2 className="lp-title problem__title">
            Talent isn&rsquo;t the problem.
            <br />
            <span className="is-muted">Clarity is.</span>
          </h2>
          <p className="lp-lede">
            Most people aren&rsquo;t behind because they lack ability. They&rsquo;re stuck because
            it&rsquo;s hard to see where they stand, and what the industry actually expects.
          </p>
        </Reveal>

        <Stagger className="problem__grid" role="list">
          {items.map((item) => (
            <StaggerItem key={item.step} className="lp-cell" role="listitem">
              <div className="lp-card problem__card">
                <div className="problem__top">
                  <span className="lp-icon">
                    <item.icon aria-hidden="true" />
                  </span>
                  <span className="problem__step">{item.step}</span>
                </div>
                <h3 className="problem__card-title">{item.title}</h3>
                <p className="problem__card-desc">{item.desc}</p>
                <div className="problem__effect">
                  <span aria-hidden="true">↳</span>
                  {item.effect}
                </div>
              </div>
            </StaggerItem>
          ))}
        </Stagger>

        {/* Lights up word by word as it scrolls through the screen */}
        <ScrubWords
          className="problem__statement"
          text="Learning more isn’t always the answer. Knowing what matters next is."
        />
      </div>
    </section>
  );
}
