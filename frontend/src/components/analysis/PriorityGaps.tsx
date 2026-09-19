import { useState } from "react";
import type { SkillGap } from "../../services/analysis";
import { levelWord, pct, priorityOf, skillName } from "./analysisModel";
import GapExplain from "./GapExplain";
import { SkillActionButtons, type GapActions } from "./gapActions";

const INITIAL = 5;

export default function PriorityGaps({ gaps, actions }: { gaps: SkillGap[]; actions: GapActions }) {
  const [open, setOpen] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const shown = showAll ? gaps : gaps.slice(0, INITIAL);

  if (gaps.length === 0) {
    return <p className="an-empty">No priority gaps. Every skill {actions.targetRole} roles ask for is at or above the required level.</p>;
  }

  return (
    <>
      <ol className="an-gaps">
        {shown.map((g, i) => {
          const expanded = open === g.id;
          const prio = priorityOf(g);
          const current = pct(g.current_proficiency);
          const required = pct(g.required_level);
          return (
            <li key={g.id} className={`an-gap${expanded ? " is-open" : ""}`}>
              <button
                type="button"
                className="an-gap__row"
                aria-expanded={expanded}
                onClick={() => setOpen(expanded ? null : g.id)}
              >
                <span className="an-gap__num an-num">{String(i + 1).padStart(2, "0")}</span>
                <span className="an-gap__main">
                  <span className="an-gap__name">{skillName(g)}</span>
                  <span className="an-gap__meta">
                    <span className={`an-prio an-prio--${prio.tone}`}>{prio.label}</span>
                    <span>{g.evidence_state === "no_evidence" ? "No evidence" : levelWord(g.current_proficiency)}</span>
                    {g.skills?.category && <span className="an-faint">{g.skills.category}</span>}
                  </span>
                </span>
                <span className="an-gap__bar" aria-label={`${current}% of the ${required}% required`}>
                  <span className="an-cmp">
                    <span className="an-cmp__you" style={{ width: `${current}%` }} />
                    <span className="an-cmp__req" style={{ left: `${required}%` }} />
                  </span>
                  <span className="an-gap__nums an-num">
                    {current}
                    <span className="an-faint"> / {required}</span>
                  </span>
                </span>
                <span className="an-why-toggle">{expanded ? "Hide" : "Why?"}</span>
              </button>
              {expanded && (
                <div className="an-gap__detail">
                  <GapExplain
                    gap={g}
                    targetRole={actions.targetRole}
                    roadmap={actions.roadmapFor(g)}
                    onGenerateRoadmap={actions.generateRoadmap}
                    generating={actions.generatingRoadmap}
                  />
                  <SkillActionButtons gap={g} actions={actions} />
                </div>
              )}
            </li>
          );
        })}
      </ol>
      {gaps.length > INITIAL && (
        <button type="button" className="an-more" onClick={() => setShowAll((s) => !s)}>
          {showAll ? "Show fewer" : `Show all ${gaps.length} gaps`}
        </button>
      )}
    </>
  );
}
