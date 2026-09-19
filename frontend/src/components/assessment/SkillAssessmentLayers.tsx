import { useMemo, useState } from "react";
import {
  type AssessmentLayerKey,
  type AvailableAssessment,
} from "../../services/assessment";
import PracticalModal from "./PracticalModal";
import InterviewModal from "./InterviewModal";
import "./SkillAssessmentLayers.css";
import Button from "@/components/ui/app-button";

type Props = {
  items: AvailableAssessment[];
  /** Open the existing knowledge (MCQ) assessment for a skill. */
  onStartKnowledge: (item: AvailableAssessment) => void;
  /** Refresh analysis + assessment list after any layer completes. */
  onCompleted: () => void;
};

const LAYER_META: Record<AssessmentLayerKey, { title: string; question: string; eta: string }> = {
  knowledge: { title: "Knowledge", question: "Do you understand it?", eta: "About 10 min" },
  practical: { title: "Practical", question: "Can you apply it?", eta: "About 20 min" },
  interview: { title: "AI interview", question: "Can you explain your reasoning?", eta: "About 10 min" },
};

const LAYER_ORDER: AssessmentLayerKey[] = ["knowledge", "practical", "interview"];

const FILTERS = [
  { id: "all", label: "All" },
  { id: "todo", label: "Not started" },
  { id: "doing", label: "In progress" },
  { id: "done", label: "Validated" },
] as const;

type FilterId = (typeof FILTERS)[number]["id"];

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

/** Everything the list and the summary need about one skill, worked out once. */
type SkillRow = {
  item: AvailableAssessment;
  applicable: AssessmentLayerKey[];
  states: Record<string, { status: string; score: number | null }>;
  doneCount: number;
  next: AssessmentLayerKey | null;
  scores: number[];
};

function buildRow(item: AvailableAssessment): SkillRow {
  const applicable = LAYER_ORDER.filter((l) => layerApplicable(item, l));
  const states: SkillRow["states"] = {};
  const scores: number[] = [];
  for (const layer of applicable) {
    const st = layerState(item, layer);
    states[layer] = st;
    if (isDone(st.status) && st.score !== null) scores.push(st.score);
  }
  const doneCount = applicable.filter((l) => isDone(states[l].status)).length;
  const next = applicable.find((l) => states[l].status === "not_started") ?? null;
  return { item, applicable, states, doneCount, next, scores };
}

const Tick = () => (
  <svg className="sa-pip__tick" width="11" height="11" viewBox="0 0 12 12" aria-hidden="true">
    <path d="M2 6.2 4.6 8.8 10 3.4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

export default function SkillAssessmentLayers({ items, onStartKnowledge, onCompleted }: Props) {
  const [practicalSkill, setPracticalSkill] = useState<string | null>(null);
  const [interviewSkill, setInterviewSkill] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [filter, setFilter] = useState<FilterId>("all");

  // Unfinished skills first, most important first — the useful thing is always on top
  const rows = useMemo(() => {
    const built = items.map(buildRow);
    return built.sort((a, b) => {
      const aDone = a.doneCount === a.applicable.length;
      const bDone = b.doneCount === b.applicable.length;
      if (aDone !== bDone) return aDone ? 1 : -1;
      return (b.item.priority_score ?? 0) - (a.item.priority_score ?? 0);
    });
  }, [items]);

  const summary = useMemo(() => {
    const totalLayers = rows.reduce((n, r) => n + r.applicable.length, 0);
    const doneLayers = rows.reduce((n, r) => n + r.doneCount, 0);
    const allScores = rows.flatMap((r) => r.scores);
    return {
      skills: rows.length,
      validated: rows.filter((r) => r.applicable.length > 0 && r.doneCount === r.applicable.length).length,
      totalLayers,
      doneLayers,
      average: allScores.length ? Math.round((allScores.reduce((a, b) => a + b, 0) / allScores.length) * 100) : null,
    };
  }, [rows]);

  const counts: Record<FilterId, number> = {
    all: rows.length,
    todo: rows.filter((r) => r.doneCount === 0).length,
    doing: rows.filter((r) => r.doneCount > 0 && r.doneCount < r.applicable.length).length,
    done: rows.filter((r) => r.applicable.length > 0 && r.doneCount === r.applicable.length).length,
  };

  const shown = rows.filter((r) => {
    if (filter === "todo") return r.doneCount === 0;
    if (filter === "doing") return r.doneCount > 0 && r.doneCount < r.applicable.length;
    if (filter === "done") return r.applicable.length > 0 && r.doneCount === r.applicable.length;
    return true;
  });

  if (items.length === 0) return null;

  const starter = (item: AvailableAssessment, layer: AssessmentLayerKey) => () => {
    if (layer === "knowledge") onStartKnowledge(item);
    else if (layer === "practical") setPracticalSkill(item.skill);
    else setInterviewSkill(item.skill);
  };

  return (
    <div className="sa">
      <dl className="sa-sum">
        <div>
          <dt>Skills to validate</dt>
          <dd className="an-num">{summary.skills}</dd>
        </div>
        <div>
          <dt>Fully validated</dt>
          <dd className="an-num">
            {summary.validated}
            <small>of {summary.skills}</small>
          </dd>
        </div>
        <div>
          <dt>Checks completed</dt>
          <dd className="an-num">
            {summary.doneLayers}
            <small>of {summary.totalLayers}</small>
          </dd>
        </div>
        <div>
          <dt>Average score</dt>
          <dd className="an-num">{summary.average === null ? "—" : `${summary.average}%`}</dd>
        </div>
      </dl>

      <p className="sa-intro">
        Each skill can be checked in up to three ways — <strong>Knowledge</strong> (do you understand it),{" "}
        <strong>Practical</strong> (can you apply it) and an <strong>AI interview</strong> (can you explain your
        reasoning). Do the ones that apply; every result is combined with your evidence to sharpen your skill gaps and
        your roadmap.
      </p>

      {rows.length > 4 && (
        <div className="sa-bar">
          <div className="an-seg" role="tablist" aria-label="Filter skills">
            {FILTERS.map((f) => (
              <button
                key={f.id}
                type="button"
                role="tab"
                aria-selected={filter === f.id}
                className={filter === f.id ? "is-on" : ""}
                onClick={() => {
                  setFilter(f.id);
                  setOpen(null);
                }}
              >
                {f.label} <span className="an-num">{counts[f.id]}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {shown.length === 0 ? (
        <p className="an-empty">No skills in this group yet.</p>
      ) : (
        <ul className="sa-skills">
          {shown.map((row) => {
            const { item, applicable, states, doneCount, next } = row;
            const expanded = open === item.skill_key;
            const complete = applicable.length > 0 && doneCount === applicable.length;
            return (
              <li key={item.skill_key} className={`sa-skill${expanded ? " is-open" : ""}`}>
                <div className="sa-skill__row">
                  <button
                    type="button"
                    className="sa-skill__main"
                    aria-expanded={expanded}
                    onClick={() => setOpen(expanded ? null : item.skill_key)}
                  >
                    <span className="sa-skill__name">
                      {item.skill}
                      <span className="an-faint">
                        {applicable.length === 0
                          ? "No checks available yet"
                          : `${doneCount} of ${applicable.length} checks done`}
                        {item.reason_label ? ` · ${item.reason_label}` : ""}
                      </span>
                    </span>
                    <span className="sa-track">
                      {applicable.map((layer) => {
                        const st = states[layer];
                        const done = isDone(st.status);
                        const review = st.status === "awaiting_review";
                        const isNext = !done && !review && layer === next;
                        const cls = done ? "is-done" : review ? "is-review" : isNext ? "is-next" : "is-todo";
                        return (
                          <span key={layer} className={`sa-pip ${cls}`}>
                            {done && <Tick />}
                            {LAYER_META[layer].title}
                            {done && st.score !== null && <b className="an-num">{pct(st.score)}</b>}
                          </span>
                        );
                      })}
                    </span>
                  </button>

                  {applicable.length === 0 ? (
                    <span className="sa-flag an-faint">Not available yet</span>
                  ) : complete ? (
                    <span className="sa-flag is-done">
                      <Tick />
                      Validated
                    </span>
                  ) : (
                    <Button variant="secondary"
                      className="sa-cta"
                      onClick={starter(item, next ?? applicable[0])}
>
                      Start {LAYER_META[next ?? applicable[0]].title.toLowerCase()}
                    </Button>
                  )}
                </div>

                {expanded && (
                  <div className="sa-skill__detail">
                    {applicable.length === 0 ? (
                      <p className="an-empty">INAURA doesn’t have a check for this skill yet.</p>
                    ) : (
                      <ol className="sa-layers">
                        {applicable.map((layer, i) => {
                          const meta = LAYER_META[layer];
                          const st = states[layer];
                          const done = isDone(st.status);
                          const review = st.status === "awaiting_review";
                          const score = pct(st.score);
                          const comms = item.layers?.interview?.communication_score;
                          return (
                            <li key={layer} className={`sa-layer${done ? " is-done" : ""}${review ? " is-review" : ""}`}>
                              <span className="sa-layer__n" aria-hidden="true">
                                {done ? <Tick /> : i + 1}
                              </span>
                              <span className="sa-layer__text">
                                <span className="sa-layer__title">{meta.title}</span>
                                <span className="sa-layer__q">{meta.question}</span>
                              </span>
                              <span className="sa-layer__status">
                                {done ? (
                                  <>
                                    Completed{score ? ` · ${score}` : ""}
                                    {layer === "interview" && comms != null && (
                                      <span className="an-faint"> Communication {pct(comms)}</span>
                                    )}
                                  </>
                                ) : review ? (
                                  "Answers saved · awaiting review"
                                ) : (
                                  meta.eta
                                )}
                              </span>
                              {review ? (
                                <span />
                              ) : (
                                <Button variant={done ? "secondary" : "primary"}
                                  className="sa-layer__btn"
                                  onClick={starter(item, layer)}
>
                                  {done ? "Retake" : st.score != null ? "Continue" : "Start"}
                                </Button>
                              )}
                            </li>
                          );
                        })}
                      </ol>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}

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
    </div>
  );
}
