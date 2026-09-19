import { useState } from "react";
import type { SkillGap } from "../../services/analysis";
import { confidenceWord, evidenceKindsFor, levelWord, pct, skillName, sourceLabels } from "./analysisModel";
import { SkillActionButtons, type GapActions } from "./gapActions";

const INITIAL = 4;

export default function EvidenceGaps({ gaps, actions }: { gaps: SkillGap[]; actions: GapActions }) {
  const [open, setOpen] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const shown = showAll ? gaps : gaps.slice(0, INITIAL);

  if (gaps.length === 0) {
    return <p className="an-empty">No evidence gaps. Every skill INAURA assessed has independent proof behind it.</p>;
  }

  return (
    <>
      <ul className="an-claims">
        {shown.map((g) => {
          const expanded = open === g.id;
          const sources = sourceLabels(g, 3);
          const kinds = evidenceKindsFor(g);
          const conf = confidenceWord(g.confidence);
          return (
            <li key={g.id} className={`an-claim${expanded ? " is-open" : ""}`}>
              <button type="button" className="an-claim__row" aria-expanded={expanded} onClick={() => setOpen(expanded ? null : g.id)}>
                <span className="an-claim__name">{skillName(g)}</span>
                <span className="an-claim__flow">
                  <span className="an-claim__step">
                    <span className="an-claim__k">Claimed or estimated</span>
                    <span className="an-claim__v">{g.evidence_state === "no_evidence" ? "Required" : levelWord(g.current_proficiency)}</span>
                  </span>
                  <span className="an-claim__arrow" aria-hidden="true" />
                  <span className="an-claim__step">
                    <span className="an-claim__k">Evidence</span>
                    <span className="an-claim__v">
                      {sources.length ? `${g.evidence_sources?.length ?? sources.length} source${(g.evidence_sources?.length ?? 1) === 1 ? "" : "s"}` : "None"}
                    </span>
                  </span>
                  <span className="an-claim__arrow" aria-hidden="true" />
                  <span className="an-claim__step">
                    <span className="an-claim__k">Confidence</span>
                    <span className={`an-claim__v an-conf an-conf--${conf.toLowerCase()}`}>{conf}</span>
                  </span>
                </span>
                <span className="an-why-toggle">{expanded ? "Hide" : "Why?"}</span>
              </button>

              {expanded && (
                <div className="an-claim__detail">
                  <p className="an-claim__q">Why is confidence {conf.toLowerCase()}?</p>
                  <ul className="an-kinds" aria-label="Kinds of evidence for this skill">
                    {kinds.map(({ kind, present }) => (
                      <li key={kind.key} className={present ? "is-present" : ""}>
                        <span className="an-kinds__mark" aria-hidden="true">{present ? "✓" : "✕"}</span>
                        {kind.label}
                        <span className="an-visually-hidden">{present ? ": present" : ": missing"}</span>
                      </li>
                    ))}
                  </ul>
                  <p className="an-claim__text">
                    {sources.length ? <>Found in {sources.join(", ")}. </> : null}
                    Confidence is {pct(g.confidence)}%. {g.actionable_advice || `Submit a repository, project or certificate that demonstrates ${skillName(g)}.`}
                  </p>
                  <SkillActionButtons gap={g} actions={actions} />
                </div>
              )}
            </li>
          );
        })}
      </ul>
      {gaps.length > INITIAL && (
        <button type="button" className="an-more" onClick={() => setShowAll((s) => !s)}>
          {showAll ? "Show fewer" : `Show all ${gaps.length} skills`}
        </button>
      )}
    </>
  );
}
