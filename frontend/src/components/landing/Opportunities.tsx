import type { LucideIcon } from "lucide-react";
import { ChartNoAxesColumn, Milestone, Target } from "lucide-react";
import { motion } from "framer-motion";
import { EASE, Reveal, Stagger, StaggerItem, useStill } from "./scroll";
import "./shared.css";
import "./Opportunities.css";

// Opportunities isn't built yet (the app's sidebar shows it as "Soon"), so this section
// describes what's planned and labels the example card as a preview.

const POINTS: { title: string; desc: string; icon: LucideIcon }[] = [
  {
    title: "Matched to your career",
    desc: "Internships and entry-level roles for the career you’re tracking, instead of an endless generic job board.",
    icon: Target,
  },
  {
    title: "Ranked by real readiness",
    desc: "Readiness compares your evidence-backed skill levels with what each opening requires, the same measure as your Career Track.",
    icon: ChartNoAxesColumn,
  },
  {
    title: "Gaps become next steps",
    desc: "When an opening asks for a skill you haven’t proven yet, it goes onto your roadmap, so you know exactly what stands between you and applying.",
    icon: Milestone,
  },
];

type Match = { title: string; where: string; match: number; met: string; missing: string[] };

// Example openings for the preview card (no real companies), for the page's example student
const MATCHES: Match[] = [
  { title: "Frontend Intern", where: "Product startup · Bengaluru", match: 82, met: "5 of 6 requirements met", missing: [] },
  { title: "Junior React Developer", where: "SaaS company · Remote", match: 72, met: "4 of 6 requirements met", missing: ["Testing"] },
  { title: "Graduate UI Engineer", where: "Fintech · Hyderabad", match: 58, met: "3 of 6 requirements met", missing: ["TypeScript", "Testing"] },
];

const R = 19;

/** How ready you are for an opening: a ring that draws itself in the first time it's seen */
function MatchRing({ value, delay }: { value: number; delay: number }) {
  const reduce = useStill();
  const tone = value >= 80 ? "high" : value >= 65 ? "mid" : "low";
  return (
    <span className={`opps__ring opps__ring--${tone}`}>
      <svg width="46" height="46" viewBox="0 0 46 46">
        <circle className="opps__ring-track" cx="23" cy="23" r={R} />
        {reduce ? (
          <circle className="opps__ring-value" cx="23" cy="23" r={R} pathLength={100} strokeDasharray={`${value} 100`} />
        ) : (
          <motion.circle
            className="opps__ring-value"
            cx="23"
            cy="23"
            r={R}
            initial={{ pathLength: 0 }}
            whileInView={{ pathLength: value / 100 }}
            viewport={{ once: true, amount: 1 }}
            transition={{ duration: 1.2, ease: EASE, delay }}
          />
        )}
      </svg>
      <span className="opps__ring-num">{value}%</span>
    </span>
  );
}

export default function Opportunities() {
  return (
    <section id="opportunities" className="opps section section--subtle">
      <div className="container">
        <Reveal className="lp-head">
          <div className="opps__eyebrow-row">
            <div className="eyebrow">Opportunities</div>
            <span className="lp-tag lp-tag--soon">Coming soon</span>
          </div>
          <h2 className="lp-title">
            Readiness that
            <br />
            <span className="is-muted">opens doors.</span>
          </h2>
          <p className="lp-lede">
            The next step after your Career Track is opportunities matched to the role you&rsquo;re
            targeting, ranked by the skills you&rsquo;ve actually demonstrated.
          </p>
        </Reveal>

        <div className="opps__inner">
          <Stagger className="opps__points" role="list" gap={0.12}>
            {POINTS.map((p) => (
              <StaggerItem key={p.title} className="lp-cell" role="listitem" y={24}>
                <div className="lp-card opps__point">
                  <span className="lp-icon">
                    <p.icon aria-hidden="true" />
                  </span>
                  <div>
                    <h3 className="opps__point-title">{p.title}</h3>
                    <p className="opps__point-desc">{p.desc}</p>
                  </div>
                </div>
              </StaggerItem>
            ))}
          </Stagger>

          <Reveal className="opps__visual" y={48} amount={0.2}>
            <div className="lp-panel opps__mock" aria-hidden="true">
              <div className="lp-panel__head">
                <div>
                  <span className="lp-kicker">Matched for you</span>
                  <span className="lp-panel-title">Frontend Developer</span>
                </div>
                <span className="opps__badge">Preview</span>
              </div>

              <div className="opps__formula">
                Readiness = your verified skills measured against the opening&rsquo;s requirements
              </div>

              <Stagger className="opps__rows" gap={0.14} amount={0.3}>
                {MATCHES.map((m, i) => (
                  <StaggerItem key={m.title} className="opps__row" y={18}>
                    <MatchRing value={m.match} delay={0.3 + i * 0.12} />
                    <span className="opps__row-text">
                      <span className="opps__row-title">{m.title}</span>
                      <span className="opps__row-meta">
                        {m.where} · {m.met}
                      </span>
                    </span>
                    <span className="opps__tags">
                      {m.missing.length === 0 ? (
                        <span className="lp-tag lp-tag--ready">Ready to apply</span>
                      ) : (
                        m.missing.map((skill) => (
                          <span key={skill} className="lp-tag">
                            Missing: {skill}
                          </span>
                        ))
                      )}
                    </span>
                  </StaggerItem>
                ))}
              </Stagger>

              <div className="lp-panel__foot">Illustrative preview · Opportunities is in development</div>
            </div>
          </Reveal>
        </div>
      </div>
    </section>
  );
}
