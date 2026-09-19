import type { SkillGap } from "../../services/analysis";
import type { AvailableAssessment } from "../../services/assessment";
import type { RoadmapLink } from "./analysisModel";
import Button from "@/components/ui/app-button";

/** Everything a skill row can do — wired to the existing assessment, override and provenance features */
export type GapActions = {
  targetRole: string;
  assessmentFor: (g: SkillGap) => AvailableAssessment | undefined;
  startAssessment: (item: AvailableAssessment) => void;
  openDetails: (g: SkillGap) => void;
  requestOverride: (g: SkillGap) => void;
  roadmapFor: (g: SkillGap) => RoadmapLink;
  generateRoadmap?: () => void;
  generatingRoadmap: boolean;
};

export function SkillActionButtons({ gap: g, actions }: { gap: SkillGap; actions: GapActions }) {
  const assessment = actions.assessmentFor(g);
  const canOverride = !g.is_overridden && !g.is_portfolio && g.evidence_state !== "no_evidence" && g.evidence_state !== "user_override";
  return (
    <div className="an-actions">
      {assessment && (
        <Button variant="primary" onClick={() => actions.startAssessment(assessment)}>
          {assessment.last_assessment ? "Re-take assessment" : "Prove it with an assessment"}
        </Button>
      )}
      <Button variant="secondary" onClick={() => actions.openDetails(g)}>
        Evidence details
      </Button>
      {canOverride && (
        <Button variant="ghost" onClick={() => actions.requestOverride(g)}>
          I don’t actually know this yet
        </Button>
      )}
      {g.is_overridden && <span className="an-note an-note--warn">You marked this as not known. New evidence or an assessment can restore it.</span>}
    </div>
  );
}
