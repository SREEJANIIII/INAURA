import { useState } from "react";
import Button from "../ui/Button";
import {
  type AssessmentLayerKey,
  type AvailableAssessment,
} from "../../services/assessment";
import PracticalModal from "./PracticalModal";
import InterviewModal from "./InterviewModal";
import "./SkillAssessmentLayers.css";

type Props = {
  items: AvailableAssessment[];
  /** Open the existing knowledge (MCQ) assessment for a skill. */
  onStartKnowledge: (item: AvailableAssessment) => void;
  /** Refresh analysis + assessment list after any layer completes. */
  onCompleted: () => void;
};

const LAYER_META: Record<AssessmentLayerKey, { icon: string; title: string; question: string; eta: string }> = {
  knowledge: { icon: "🧠", title: "Knowledge", question: "Do you understand it?", eta: "~10 min" },
  practical: { icon: "💻", title: "Practical", question: "Can you apply it?", eta: "~20 min" },
  interview: { icon: "🎤", title: "AI Interview", question: "Can you explain and reason about it?", eta: "~10 min" },
};

const LAYER_ORDER: AssessmentLayerKey[] = ["knowledge", "practical", "interview"];

function layerApplicable(item: AvailableAssessment, layer: AssessmentLayerKey): boolean {
  const caps = item.capabilities;
  // Before the backend upgrade (or when capabilities are absent), only the
  // knowledge layer is known — never assume a practical task exists.
  if (!caps) return layer === "knowledge";
  if (layer === "knowledge") return caps.knowledge_assessment;
  if (layer === "practical") return caps.practical_assessment;
  return caps.interview_assessment;
}

function layerState(item: AvailableAssessment, layer: AssessmentLayerKey): { status: string; score: number | null } {
  const entry = item.layers?.[layer];
  if (entry) return { status: entry.status, score: entry.score ?? null };
  // Backward compatibility: pre-layers backends only expose last_assessment.
  if (layer === "knowledge" && item.last_assessment) {
    return { status: "completed", score: item.last_assessment.score };
  }
  return { status: "not_started", score: null };
}

function isDone(status: string) {
  return status === "completed" || status === "graded";
}

const pct = (v: number | null | undefined) =>
  v === null || v === undefined ? null : `${Math.round(v * 100)}%`;

export default function SkillAssessmentLayers({ items, onStartKnowledge, onCompleted }: Props) {
  const [practicalSkill, setPracticalSkill] = useState<string | null>(null);
  const [interviewSkill, setInterviewSkill] = useState<string | null>(null);

  if (items.length === 0) return null;

  return (
    <section className="layers" aria-label="Skill assessments by layer">
      <div className="layers__intro">
        <h2>🎯 Build your most complete readiness profile</h2>
        <p>
          For the most complete readiness score and personalized roadmap, complete all applicable
          assessment layers for your skills.
        </p>
        <ul className="layers__intro-list">
          <li>
            <strong>🧠 Knowledge</strong> — Do you understand it?
          </li>
          <li>
            <strong>💻 Practical</strong> — Can you apply it?
          </li>
          <li>
            <strong>🎤 AI Interview</strong> — Can you explain and reason about it?
          </li>
        </ul>
        <p className="layers__intro-note">
          Your assessment results are combined with your existing evidence to help INAURA identify
          skill gaps and personalize your roadmap.
        </p>
      </div>

      <div className="layers__cards">
        {items.map((item) => {
          const applicable = LAYER_ORDER.filter((l) => layerApplicable(item, l));
          const doneCount = applicable.filter((l) => isDone(layerState(item, l).status)).length;
          return (
            <div key={item.skill_key} className="layers__skill">
              <div className="layers__skill-head">
                <strong>{item.skill}</strong>
                <span className="layers__skill-progress">
                  {doneCount}/{applicable.length} layers complete
                </span>
              </div>
              <div className="layers__steps">
                {applicable.map((layer, i) => {
                  const meta = LAYER_META[layer];
                  const st = layerState(item, layer);
                  const done = isDone(st.status);
                  const score = pct(st.score);
                  const start =
                    layer === "knowledge"
                      ? () => onStartKnowledge(item)
                      : layer === "practical"
                        ? () => setPracticalSkill(item.skill)
                        : () => setInterviewSkill(item.skill);
                  return (
                    <div key={layer}>
                      <div className={`layers__step ${done ? "layers__step--done" : ""}`}>
                        <div className="layers__step-info">
                          <span className="layers__step-title">
                            {meta.icon} {meta.title}
                          </span>
                          <span className="layers__step-desc">{meta.question}</span>
                          <span className="layers__step-eta">
                            {done && score ? (
                              <>
                                Completed ✓ <strong>{score}</strong>
                                {layer === "interview" &&
                                  item.layers?.interview?.communication_score != null && (
                                    <> · Communication {pct(item.layers.interview.communication_score)}</>
                                  )}
                              </>
                            ) : st.status === "awaiting_review" ? (
                              "Answers saved · awaiting review"
                            ) : (
                              meta.eta
                            )}
                          </span>
                        </div>
                        {done || st.status === "awaiting_review" ? (
                          done ? (
                            <Button onClick={start}>Retry</Button>
                          ) : null
                        ) : (
                          <Button onClick={start}>{st.score != null ? "Continue" : "Start"}</Button>
                        )}
                      </div>
                      {i < applicable.length - 1 && (
                        <div className="layers__arrow" aria-hidden="true">
                          ↓
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
              {applicable.length === 0 && (
                <div className="layers__none">No assessment layers apply to this skill yet.</div>
              )}
            </div>
          );
        })}
      </div>

      {practicalSkill && (
        <PracticalModal
          skill={practicalSkill}
          onClose={() => setPracticalSkill(null)}
          onCompleted={() => {
            setPracticalSkill(null);
            onCompleted();
          }}
        />
      )}
      {interviewSkill && (
        <InterviewModal
          skill={interviewSkill}
          onClose={() => setInterviewSkill(null)}
          onCompleted={() => onCompleted()}
        />
      )}
    </section>
  );
}
