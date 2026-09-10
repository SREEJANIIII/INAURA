import { useEffect, useMemo, useState } from "react";
import Button from "../ui/Button";
import {
  startAssessment,
  submitAssessment,
  type StartAssessmentResponse,
  type SubmitAssessmentResponse,
} from "../../services/assessment";
import "./AssessmentModal.css";

type Props = {
  skill: string;
  /** Evidence-based estimate before the assessment, for the before/after view. */
  evidenceProficiency?: number;
  evidenceConfidence?: number;
  onClose: () => void;
  /** Called after a graded submission so the parent can refresh the analysis. */
  onCompleted?: (result: SubmitAssessmentResponse) => void;
};

export default function AssessmentModal({
  skill,
  evidenceProficiency,
  evidenceConfidence,
  onClose,
  onCompleted,
}: Props) {
  const [attempt, setAttempt] = useState<StartAssessmentResponse | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [result, setResult] = useState<SubmitAssessmentResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [startedAt] = useState(() => Date.now());

  // The modal is mounted per selected skill (keyed by skill in the parent),
  // so the attempt is started exactly once and `loading` starts true.
  useEffect(() => {
    let active = true;
    startAssessment(skill)
      .then((data) => {
        if (active) setAttempt(data);
      })
      .catch((e) => {
        if (active) setError(e instanceof Error ? e.message : "Could not start the assessment");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [skill]);

  const answeredCount = useMemo(
    () => Object.values(answers).filter((v) => v && v.trim() !== "").length,
    [answers]
  );
  const total = attempt?.question_count ?? 0;
  const allAnswered = total > 0 && answeredCount === total;

  const handleSubmit = async () => {
    if (!attempt) return;
    setSubmitting(true);
    setError(null);
    try {
      const duration = Math.round((Date.now() - startedAt) / 1000);
      const data = await submitAssessment(attempt.attempt_id, answers, duration);
      setResult(data);
      onCompleted?.(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not submit the assessment");
    } finally {
      setSubmitting(false);
    }
  };

  const pct = (v: number | null | undefined) =>
    v === null || v === undefined ? "—" : `${Math.round(v * 100)}%`;

  return (
    <div className="assess__overlay" role="dialog" aria-modal="true" aria-label={`${skill} assessment`}>
      <div className="assess__modal">
        <header className="assess__header">
          <div>
            <div className="assess__eyebrow">INAURA Skill Assessment</div>
            <h2 className="assess__title">{skill}</h2>
          </div>
          <button className="assess__close" onClick={onClose} aria-label="Close assessment">
            ×
          </button>
        </header>

        {loading && <div className="assess__state">Preparing your questions…</div>}

        {error && !loading && (
          <div className="assess__error">
            {error}
            {error.includes("404") && (
              <div className="assess__error-hint">
                No question set exists for this skill yet.
              </div>
            )}
          </div>
        )}

        {/* ---------------- Questions ---------------- */}
        {attempt && !result && !loading && (
          <>
            <div className="assess__meta">
              <span>
                {answeredCount}/{total} answered
              </span>
              <span>·</span>
              <span>Version {attempt.assessment_version}</span>
            </div>
            <div className="assess__progress">
              <div
                className="assess__progress-bar"
                style={{ width: `${total ? (answeredCount / total) * 100 : 0}%` }}
              />
            </div>

            <div className="assess__questions">
              {attempt.questions.map((q, idx) => (
                <div key={q.id} className="assess__question">
                  <div className="assess__q-head">
                    <span className="assess__q-num">{idx + 1}</span>
                    <span className="assess__q-tag">{q.kind}</span>
                    <span className="assess__q-tag assess__q-tag--diff">{q.difficulty}</span>
                  </div>
                  <pre className="assess__prompt">{q.prompt}</pre>

                  {q.type === "multiple_choice" ? (
                    <div className="assess__options">
                      {q.options.map((opt) => (
                        <label
                          key={opt.id}
                          className={`assess__option ${answers[q.id] === opt.id ? "assess__option--on" : ""}`}
                        >
                          <input
                            type="radio"
                            name={q.id}
                            value={opt.id}
                            checked={answers[q.id] === opt.id}
                            onChange={() => setAnswers({ ...answers, [q.id]: opt.id })}
                          />
                          <span>{opt.text}</span>
                        </label>
                      ))}
                    </div>
                  ) : (
                    <input
                      className="assess__short"
                      type="text"
                      placeholder="Type your answer"
                      value={answers[q.id] || ""}
                      onChange={(e) => setAnswers({ ...answers, [q.id]: e.target.value })}
                    />
                  )}
                </div>
              ))}
            </div>

            <footer className="assess__footer">
              <div className="assess__disclaimer">{attempt.disclaimer}</div>
              <div className="assess__actions">
                <Button variant="secondary" size="md" onClick={onClose} disabled={submitting}>
                  Cancel
                </Button>
                <Button variant="primary" size="md" onClick={handleSubmit} disabled={submitting || answeredCount === 0}>
                  {submitting ? "Grading…" : allAnswered ? "Submit assessment" : `Submit (${answeredCount}/${total})`}
                </Button>
              </div>
            </footer>
          </>
        )}

        {/* ---------------- Result ---------------- */}
        {result && (
          <div className="assess__result">
            <div className="assess__score-row">
              <div className="assess__score">
                <div className="assess__score-label">Assessment</div>
                <div className="assess__score-value">
                  {result.correct_count}/{result.question_count}
                </div>
                <div className="assess__score-sub">{pct(result.score)}</div>
              </div>

              <div className="assess__compare">
                <div className="assess__compare-row">
                  <span>Evidence-based estimate</span>
                  <strong>{pct(evidenceProficiency ?? result.analysis?.skill?.evidence_proficiency)}</strong>
                </div>
                <div className="assess__compare-row">
                  <span>Assessment result</span>
                  <strong>{pct(result.score)}</strong>
                </div>
                <div className="assess__compare-row assess__compare-row--final">
                  <span>Final proficiency</span>
                  <strong>{pct(result.analysis?.skill?.proficiency)}</strong>
                </div>
                <div className="assess__compare-row">
                  <span>Confidence</span>
                  <strong>
                    {pct(evidenceConfidence)} → {pct(result.analysis?.skill?.confidence)}
                  </strong>
                </div>
              </div>
            </div>

            {!result.counts_as_evidence && (
              <div className="assess__warn">
                This attempt was partial or expired, so it is recorded but not used as skill
                evidence. Complete every question to have it counted.
              </div>
            )}

            <div className="assess__feedback">
              {result.feedback.map((f, idx) => (
                <div
                  key={f.question_id}
                  className={`assess__fb ${f.correct ? "assess__fb--ok" : "assess__fb--no"}`}
                >
                  <div className="assess__fb-head">
                    <span>{f.correct ? "✓" : "✗"} Question {idx + 1}</span>
                    <span className="assess__q-tag">{f.kind}</span>
                  </div>
                  <div className="assess__fb-exp">{f.explanation}</div>
                </div>
              ))}
            </div>

            <footer className="assess__footer">
              <div className="assess__disclaimer">{result.disclaimer}</div>
              <div className="assess__actions">
                <Button variant="primary" size="md" onClick={onClose}>
                  Done
                </Button>
              </div>
            </footer>
          </div>
        )}
      </div>
    </div>
  );
}
