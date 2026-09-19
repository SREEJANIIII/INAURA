import type { LucideIcon } from "lucide-react";
import { BookOpen, Briefcase, GraduationCap, Laptop, Signpost } from "lucide-react";
import { Reveal, Stagger, StaggerItem } from "./scroll";
import "./shared.css";
import "./Audience.css";

type Audience = { id: string; n: string; icon: LucideIcon; title: string; desc: string; focus: string };

// Each card has its own id, so the footer's "For" links can land on it
const AUDIENCES: Audience[] = [
  {
    id: "for-students",
    n: "01",
    icon: BookOpen,
    title: "Students",
    desc: "Build the right skills before graduation, in the order your target role needs them.",
    focus: "Your first role",
  },
  {
    id: "for-graduates",
    n: "02",
    icon: GraduationCap,
    title: "Fresh Graduates",
    desc: "Turn academic knowledge into job-ready capability, with evidence an employer can see.",
    focus: "Job-ready proof",
  },
  {
    id: "for-career-switchers",
    n: "03",
    icon: Signpost,
    title: "Career Switchers",
    desc: "Understand exactly which skills you need to move into a new role, and which ones carry over.",
    focus: "A new direction",
  },
  {
    id: "for-professionals",
    n: "04",
    icon: Briefcase,
    title: "Working Professionals",
    desc: "Identify the gaps between your current role and the next one, and plan your move.",
    focus: "The next step up",
  },
  {
    id: "for-freelancers",
    n: "05",
    icon: Laptop,
    title: "Freelancers",
    desc: "Build stronger skills and demonstrate your capabilities with work that speaks for itself.",
    focus: "Proof for clients",
  },
];

export default function Audience() {
  return (
    <section id="who-its-for" className="audience section">
      <div className="container">
        <Reveal className="lp-head lp-head--center">
          <div className="eyebrow">Who INAURA is for</div>
          <h2 className="lp-title">
            Built for every stage
            <br />
            <span className="is-muted">of the career journey.</span>
          </h2>
          <p className="lp-lede">
            Wherever you&rsquo;re starting from, the question is the same: where do you stand, and
            what matters next for the role you want?
          </p>
        </Reveal>

        <Stagger className="audience__grid" role="list" gap={0.08}>
          {AUDIENCES.map((a) => (
            <StaggerItem key={a.id} className="lp-cell audience__cell" role="listitem" y={28}>
              <article id={a.id} className="lp-card audience__card">
                <div className="audience__top">
                  <span className="lp-icon audience__icon">
                    <a.icon aria-hidden="true" />
                  </span>
                  <span className="audience__n">{a.n}</span>
                </div>
                <h3 className="audience__title">{a.title}</h3>
                <p className="audience__desc">{a.desc}</p>
                <div className="audience__focus">
                  <span>Focus</span>
                  {a.focus}
                </div>
              </article>
            </StaggerItem>
          ))}
        </Stagger>
      </div>
    </section>
  );
}
