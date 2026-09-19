import { useState } from "react";
import type { SkillGap } from "../../services/analysis";
import { confidenceWord, pct, priorityOf, skillName, sourceLabels } from "./analysisModel";
import { SkillActionButtons, type GapActions } from "./gapActions";

const INITIAL = 8;

type Props = { roleSkills: SkillGap[]; secondary: SkillGap[]; actions: GapActions };

export default function SkillOverview({ roleSkills, secondary, actions }: Props) {
  const [tab, setTab] = useState<"role" | "secondary">("role");
  const [open, setOpen] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const list = tab === "role" ? roleSkills : secondary;
  const shown = showAll ? list : list.slice(0, INITIAL);

  return (
    <>
      <div className="an-overview__bar">
        {secondary.length > 0 ? (
          <div className="an-seg" role="tablist" aria-label="Which skills to show">
            <button type="button" role="tab" aria-selected={tab === "role"} className={tab === "role" ? "is-on" : ""} onClick={() => { setTab("role"); setOpen(null); }}>
              Role requirements <span className="an-num">{roleSkills.length}</span>
            </button>
            <button type="button" role="tab" aria-selected={tab === "secondary"} className={tab === "secondary" ? "is-on" : ""} onClick={() => { setTab("secondary"); setOpen(null); }}>
              Other skills found <span className="an-num">{secondary.length}</span>
            </button>
          </div>
        ) : (
          <span />
        )}
        <span className="an-legend" aria-hidden="true">
          <span className="an-legend__you" /> You
          {tab === "role" && (
            <>
              <span className="an-legend__req" /> Required
            </>
          )}
        </span>
      </div>

      {tab === "secondary" && (
        <p className="an-note">Skills found in your evidence that {actions.targetRole} roles don’t require. They don’t change your readiness score.</p>
      )}

      {list.length === 0 ? (
        <p className="an-empty">No skill requirements were found for this role. Try re-running your analysis.</p>
      ) : (
        <ul className="an-skills">
          {shown.map((g) => {
            const expanded = open === g.id;
            const you = pct(g.current_proficiency);
            const req = pct(g.required_level);
            const meets = tab === "secondary" || you >= req;
            return (
              <li key={g.id} className={`an-skill${expanded ? " is-open" : ""}${g.is_overridden ? " is-overridden" : ""}`}>
                <button type="button" className="an-skill__row" aria-expanded={expanded} onClick={() => setOpen(expanded ? null : g.id)}>
                  <span className="an-skill__name">
                    {skillName(g)}
                    {g.skills?.category && <span className="an-faint">{g.skills.category}</span>}
                  </span>
                  <span className="an-cmp an-cmp--lg" aria-label={tab === "role" ? `You ${you}%, required ${req}%` : `You ${you}%`}>
                    <span className={`an-cmp__you${meets ? " is-met" : ""}`} style={{ width: `${you}%` }} />
                    {tab === "role" && <span className="an-cmp__req" style={{ left: `${req}%` }} />}
                  </span>
                  <span className="an-skill__nums an-num">
                    <span>{you}</span>
                    {tab === "role" && <span className="an-faint">{req}</span>}
                  </span>
                  <span className={`an-skill__status${meets ? " is-met" : ""}`}>
                    {tab === "secondary" ? confidenceWord(g.confidence) : meets ? "Meets" : `−${req - you}`}
                  </span>
                </button>

                {expanded && (
                  <div className="an-skill__detail">
                    <dl className="an-facts">
                      <div><dt>Current level</dt><dd className="an-num">{you}%</dd></div>
                      {tab === "role" && <div><dt>Target requirement</dt><dd className="an-num">{req}%</dd></div>}
                      {tab === "role" && <div><dt>Gap</dt><dd className="an-num">{Math.max(0, req - you)} pts</dd></div>}
                      <div><dt>Confidence</dt><dd>{confidenceWord(g.confidence)} ({pct(g.confidence)}%)</dd></div>
                      {tab === "role" && <div><dt>Priority</dt><dd>{priorityOf(g).label}</dd></div>}
                      <div className="an-facts__wide">
                        <dt>Evidence</dt>
                        <dd>{sourceLabels(g).join(", ") || g.evidence_state_label || "No evidence yet"}</dd>
                      </div>
                      {(g.actionable_advice || g.explanation) && (
                        <div className="an-facts__wide">
                          <dt>Recommended action</dt>
                          <dd>{g.actionable_advice || g.explanation}</dd>
                        </div>
                      )}
                    </dl>
                    <SkillActionButtons gap={g} actions={actions} />
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {list.length > INITIAL && (
        <button type="button" className="an-more" onClick={() => setShowAll((s) => !s)}>
          {showAll ? "Show fewer" : `Show all ${list.length} skills`}
        </button>
      )}
    </>
  );
}
