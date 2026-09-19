import { Link } from "react-router-dom";
import type { SkillGap } from "../../services/analysis";
import {
  confidenceWord,
  evidenceKindsFor,
  joinOr,
  pct,
  skillName,
  sourceLabels,
  type RoadmapLink,
} from "./analysisModel";
import Button from "@/components/ui/app-button";

type Props = {
  gap: SkillGap;
  targetRole: string;
  roadmap: RoadmapLink;
  onGenerateRoadmap?: () => void;
  generating?: boolean;
};

/**
 * "Why did INAURA say this?" — the requirement, the evidence, what's missing and what to do,
 * all taken from the fields the analysis already returns.
 */
export default function GapExplain({ gap: g, targetRole, roadmap, onGenerateRoadmap, generating }: Props) {
  const name = skillName(g);
  const sources = sourceLabels(g);
  const missingKinds = evidenceKindsFor(g).filter((k) => !k.present).map((k) => k.kind.phrase);
  const requirement =
    g.requirement_description ||
    `${targetRole} roles expect about ${pct(g.required_level)}% proficiency in ${name}` +
      (g.importance ? `, with ${g.importance >= 0.7 ? "high" : g.importance >= 0.4 ? "moderate" : "some"} importance for the role.` : ".");

  return (
    <div className="an-why">
      <div className="an-why__flow" aria-label="How this gap was found">
        <span className="an-why__step">
          <span className="an-why__k">Role needs</span>
          <strong className="an-num">{pct(g.required_level)}%</strong>
        </span>
        <span className="an-why__arrow" aria-hidden="true" />
        <span className="an-why__step">
          <span className="an-why__k">Your evidence shows</span>
          <strong className="an-num">{pct(g.current_proficiency)}%</strong>
        </span>
        <span className="an-why__arrow" aria-hidden="true" />
        <span className="an-why__step an-why__step--gap">
          <span className="an-why__k">Gap</span>
          <strong className="an-num">{pct(g.gap)} pts</strong>
        </span>
        <span className="an-why__arrow" aria-hidden="true" />
        <span className="an-why__step">
          <span className="an-why__k">Roadmap</span>
          <strong>
            {roadmap.state === "planned"
              ? `Week ${roadmap.week.week_number}`
              : roadmap.state === "missing"
                ? "Not planned"
                : "No roadmap"}
          </strong>
        </span>
      </div>

      <dl className="an-why__grid">
        <div>
          <dt>Target requirement</dt>
          <dd>{requirement}</dd>
        </div>
        <div>
          <dt>Your evidence</dt>
          <dd>{sources.length ? sources.join(", ") : "Nothing INAURA could find shows this skill yet."}</dd>
        </div>
        <div>
          <dt>Missing evidence</dt>
          <dd>
            {g.evidence_state_label && g.evidence_state !== "evidence_estimate" ? `${g.evidence_state_label}. ` : ""}
            {missingKinds.length ? `Not yet backed by ${joinOr(missingKinds.slice(0, 3))}.` : "Every kind of evidence is present."}
          </dd>
        </div>
        <div>
          <dt>Confidence</dt>
          <dd>
            {confidenceWord(g.confidence)} ({pct(g.confidence)}%)
            {g.source_diversity ? `, from ${g.source_diversity} independent source${g.source_diversity === 1 ? "" : "s"}` : ""}
          </dd>
        </div>
        {(g.actionable_advice || g.explanation) && (
          <div className="an-why__wide">
            <dt>Recommendation</dt>
            <dd>{g.actionable_advice || g.explanation}</dd>
          </div>
        )}
      </dl>

      <div className="an-why__roadmap">
        {roadmap.state === "planned" && (
          <>
            <span>
              Planned in your roadmap: <strong>Week {roadmap.week.week_number}, {roadmap.week.title}</strong>
            </span>
            <Link to="/roadmap" className="an-link">Open roadmap</Link>
          </>
        )}
        {roadmap.state === "missing" && (
          <>
            <span>This gap isn’t in your current roadmap. Rebalancing the roadmap uses your latest analysis.</span>
            <Link to="/roadmap" className="an-link">Go to roadmap</Link>
          </>
        )}
        {roadmap.state === "none" && (
          <>
            <span>You don’t have a roadmap yet. It’s built from your priority gaps, including this one.</span>
            {onGenerateRoadmap ? (
              <Button variant="secondary" onClick={onGenerateRoadmap} disabled={generating}>
                {generating ? "Building roadmap…" : "Build my roadmap"}
              </Button>
            ) : (
              <Link to="/roadmap" className="an-link">Go to roadmap</Link>
            )}
          </>
        )}
      </div>
    </div>
  );
}
