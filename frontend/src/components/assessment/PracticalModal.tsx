import { useEffect, useMemo, useState } from "react";
import Button from "../ui/app-button";
import {
  startPracticalAssessment,
  submitPracticalAssessment,
  type StartPracticalResponse,
  type SubmitPracticalResponse,
} from "../../services/assessment";
import { friendlyError } from "../../lib/errors";
import "./PracticalModal.css";

type Props = {
  skill: string;
  onClose: () => void;
  /** Called after a graded submission so the parent can refresh the analysis. */
  onCompleted?: (result: SubmitPracticalResponse) => void;
};

export default function PracticalModal({ skill, onClose, onCompleted }: Props) {
  const [attempt, setAttempt] = useState<StartPracticalResponse | null>(null);
  const [code, setCode] = useState("");
  const [result, setResult] = useState<SubmitPracticalResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [startedAt] = useState(() => Date.now());

  useEffect(() => {
    let active = true;
    startPracticalAssessment(skill)
      .then((data) => {
        if (!active) return;
        setAttempt(data);
        setCode(data.task.starter_code || "");
      })
      .catch((e) => {
        if (active) setError(friendlyError(e, "Could not start the practical task"));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [skill]);

  const nonEmpty = useMemo(() => code.trim().length > 0, [code]);

  const handleSubmit = async () => {
    if (!attempt || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const duration = Math.round((Date.now() - startedAt) / 1000);
      const data = await submitPracticalAssessment(attempt.attempt_id, code, duration);
      setResult(data);
      onCompleted?.(data);
    } catch (e) {
      setError(friendlyError(e, "Could not submit your solution"));
    } finally {
      setSubmitting(false);
    }
  };

  const pct = (v: number | null | undefined) =>
    v === null || v === undefined ? "—" : `${Math.round(v * 100)}%`;

  return (
    <div className="pract__overlay" role="dialog" aria-modal="true" aria-label={`${skill} practical assessment`}>
      <div className="pract__modal">
        <header className="pract__header">
          <div>
            <div className="pract__eyebrow">💻 Practical Assessment · {skill}</div>
            <h2 className="pract__title">{attempt?.task.title ?? skill}</h2>
            {attempt && (
              <div className="pract__meta">
                {attempt.task.task_type} · ~{attempt.task.estimated_minutes} min ·{" "}
                {attempt.task.dimensions.map((d) => d.label).join(" · ")}
              </div>
            )}
          </div>
          <button className="pract__close" onClick={onClose} aria-label="Close practical assessment">
            ×
          </button>
        </header>

        {loading && <div className="pract__state">Preparing your task…</div>}

        {error && !loading && !result && (
          <div className="pract__error">
            {error}
            {error.includes("404") && (
              <div className="pract__error-hint">
                This skill does not have a practical task yet — the knowledge and interview layers still apply.
              </div>
            )}
          </div>
        )}

        {attempt && !result && (
          <>
            <p className="pract__prompt">{attempt.task.prompt}</p>
            <label className="pract__label" htmlFor="pract-code">
              Your solution (checked automatically — never executed on our servers)
            </label>
            <textarea
              id="pract-code"
              className="pract__code"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              spellCheck={false}
              rows={14}
              placeholder="Write your solution here…"
            />
            {error && <div className="pract__error">{error}</div>}
            <div className="pract__footer">
              <span className="pract__hint">Show INAURA that you can apply this skill.</span>
              <Button onClick={handleSubmit} disabled={!nonEmpty || submitting}>
                {submitting ? "Checking…" : "Submit solution"}
              </Button>
            </div>
          </>
        )}

        {result && (
          <div className="pract__result">
            <div className="pract__score">
              {skill} practical assessment: <strong>{pct(result.score)}</strong>
            </div>
            {!result.counts_as_evidence && (
              <div className="pract__note">
                Empty submissions are recorded but do not count as evidence.
              </div>
            )}
            {result.counts_as_evidence && (
              <div className="pract__note pract__note--ok">
                Assessment evidence added to your skill profile.
              </div>
            )}
            <ul className="pract__checks">
              {result.checks.map((c) => (
                <li key={c.check_id} className={c.passed ? "pract__check--pass" : "pract__check--miss"}>
                  {c.passed ? "✓" : "·"} {c.description}
                </li>
              ))}
            </ul>
            <div className="pract__footer">
              <span className="pract__hint">{result.disclaimer}</span>
              <Button onClick={onClose}>Done</Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
