import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { Award, BadgeCheck, BookOpen, Briefcase, Check, Code2, FolderGit2, Milestone, Route, ScanSearch, Target, TrendingUp } from "lucide-react";
import { Grow, Reveal, Stagger, StaggerItem } from "./scroll";
import "./shared.css";
import "./Features.css";

/* Each feature carries a small preview of what it looks like in the product. The examples follow
   one student aiming for Frontend Developer, the same one the rest of the page follows. */

function GapPreview() {
  const gaps = [
    { skill: "React", now: 52, need: 75 },
    { skill: "TypeScript", now: 30, need: 60 },
    { skill: "Testing", now: 18, need: 60 },
  ];
  return (
    <div className="feat__gaps">
      {gaps.map((g, i) => (
        <div key={g.skill} className="feat__gap">
          <span className="feat__gap-name">{g.skill}</span>
          <span className="lp-bar">
            <Grow width={g.now} className="lp-bar__fill" delay={0.2 + i * 0.12} />
            <span className="lp-bar__target" style={{ left: `${g.need}%` }} />
          </span>
          <span className="feat__gap-num">{g.need - g.now}% to go</span>
        </div>
      ))}
      <div className="feat__legend">
        <span>
          <i className="feat__legend-fill" /> Your level
        </span>
        <span>
          <i className="feat__legend-tick" /> Role expects
        </span>
      </div>
    </div>
  );
}

function TrackPreview() {
  const phases = [
    { name: "Foundation", state: "done" },
    { name: "Core stack", state: "active" },
    { name: "Advanced", state: "todo" },
  ];
  return (
    <div className="feat__track">
      <div className="feat__track-head">
        <span className="feat__track-role">Frontend Developer</span>
        <span className="feat__track-pct">58%</span>
      </div>
      <span className="lp-bar">
        <Grow width={58} className="lp-bar__fill" delay={0.2} />
      </span>
      <ol className="feat__phases">
        {phases.map((p) => (
          <li key={p.name} className={`feat__phase feat__phase--${p.state}`}>
            <span className="feat__phase-dot">{p.state === "done" && <Check aria-hidden="true" />}</span>
            {p.name}
          </li>
        ))}
      </ol>
    </div>
  );
}

function EvidencePreview() {
  const sources: { label: string; icon: LucideIcon }[] = [
    { label: "GitHub", icon: Code2 },
    { label: "Projects", icon: FolderGit2 },
    { label: "Certifications", icon: Award },
    { label: "Courses", icon: BookOpen },
  ];
  return (
    <ul className="lp-chips">
      {sources.map((s) => (
        <li key={s.label} className="lp-chip">
          <s.icon aria-hidden="true" />
          {s.label}
          <BadgeCheck className="feat__verified" aria-hidden="true" />
        </li>
      ))}
    </ul>
  );
}

function RoadmapPreview() {
  const weeks = [
    { when: "Weeks 1–3", what: "TypeScript fundamentals" },
    { when: "Weeks 4–6", what: "Ship a React project" },
    { when: "Weeks 7–9", what: "Testing & accessibility" },
  ];
  return (
    <ol className="feat__weeks">
      {weeks.map((w) => (
        <li key={w.when}>
          <span className="feat__weeks-when">{w.when}</span>
          {w.what}
        </li>
      ))}
    </ol>
  );
}

function IndustryPreview() {
  return (
    <div className="feat__bench">
      <div className="feat__bench-row">
        <span>Your profile</span>
        <span className="lp-bar">
          <Grow width={58} className="lp-bar__fill lp-bar__fill--ink" delay={0.2} />
        </span>
      </div>
      <div className="feat__bench-row">
        <span>Role benchmark</span>
        <span className="lp-bar">
          <Grow width={100} className="lp-bar__fill" delay={0.35} />
        </span>
      </div>
      <p className="feat__bench-note">Benchmarks draw on sources such as ACM/IEEE CS2023 and the Stack Overflow Developer Survey.</p>
    </div>
  );
}

function OpportunityPreview() {
  const rows = [
    { title: "Frontend Intern", pct: 82 },
    { title: "Junior React Developer", pct: 72 },
  ];
  return (
    <div className="feat__opps">
      {rows.map((r, i) => (
        <div key={r.title} className="feat__opp">
          <span className="feat__opp-title">{r.title}</span>
          <span className="lp-bar">
            <Grow width={r.pct} className={r.pct >= 80 ? "lp-bar__fill lp-bar__fill--ready" : "lp-bar__fill"} delay={0.2 + i * 0.12} />
          </span>
          <span className="feat__opp-pct">{r.pct}% ready</span>
        </div>
      ))}
    </div>
  );
}

type Feature = {
  n: string;
  title: string;
  desc: string;
  icon: LucideIcon;
  meta: string;
  size: "lg" | "md" | "sm" | "wide";
  preview: ReactNode;
  soon?: boolean;
};

const FEATURES: Feature[] = [
  {
    n: "01",
    title: "Skill Gap Analysis",
    desc: "Identify the difference between your current capabilities and your target role, skill by skill.",
    icon: Target,
    meta: "Updates with every new piece of evidence",
    size: "lg",
    preview: <GapPreview />,
  },
  {
    n: "02",
    title: "Career Track",
    desc: "Choose a target career and see the complete path from where you are to where you need to be.",
    icon: Route,
    meta: "11 careers",
    size: "md",
    preview: <TrackPreview />,
  },
  {
    n: "03",
    title: "Evidence Analysis",
    desc: "Analyze GitHub, projects, certifications, courses and other learning evidence.",
    icon: ScanSearch,
    meta: "8 kinds of evidence",
    size: "sm",
    preview: <EvidencePreview />,
  },
  {
    n: "04",
    title: "Personalized Roadmap",
    desc: "Get prioritized skills, projects and learning recommendations, in the order that matters.",
    icon: Milestone,
    meta: "Week by week",
    size: "sm",
    preview: <RoadmapPreview />,
  },
  {
    n: "05",
    title: "Industry Alignment",
    desc: "Understand what your target industry actually expects, from curated role benchmarks.",
    icon: TrendingUp,
    meta: "Role benchmarks",
    size: "sm",
    preview: <IndustryPreview />,
  },
  {
    n: "06",
    title: "Opportunity Matching",
    desc: "Discover opportunities based on your demonstrated readiness, not the keywords on your resume.",
    icon: Briefcase,
    meta: "Coming soon",
    size: "wide",
    preview: <OpportunityPreview />,
    soon: true,
  },
];

export default function Features() {
  return (
    <section id="features" className="features section section--subtle">
      <div className="container">
        <Reveal className="lp-head">
          <div className="eyebrow">Core features</div>
          <h2 className="lp-title">
            Everything you need
            <br />
            <span className="is-accent">to move forward.</span>
          </h2>
          <p className="lp-lede">
            One connected system: your evidence becomes verified skills, your skills are measured
            against a real role, and the gap becomes a plan.
          </p>
        </Reveal>

        <Stagger className="feat__grid" role="list" gap={0.08} amount={0.1}>
          {FEATURES.map((f) => (
            <StaggerItem key={f.n} className={`lp-cell feat__cell feat__cell--${f.size}`} role="listitem" y={28}>
              <article className={`lp-card feat__card feat__card--${f.size}`}>
                <div className="feat__copy">
                  <div className="feat__top">
                    <span className="lp-icon">
                      <f.icon aria-hidden="true" />
                    </span>
                    <span className="feat__n">{f.n}</span>
                  </div>
                  <h3 className="feat__title">{f.title}</h3>
                  <p className="feat__desc">{f.desc}</p>
                  <span className={f.soon ? "lp-tag lp-tag--soon feat__meta" : "feat__meta"}>{f.meta}</span>
                </div>
                <div className="feat__preview" aria-hidden="true">
                  {f.preview}
                </div>
              </article>
            </StaggerItem>
          ))}
        </Stagger>
      </div>
    </section>
  );
}
