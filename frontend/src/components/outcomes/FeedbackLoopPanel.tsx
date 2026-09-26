import { getFeedback, type EmployerFeedback } from "../../services/outcomes";
import { getGaps } from "../../services/analysis";
import { Link } from "react-router-dom";
import { useEffect, useState } from "react";

type Gap = {
  canonical_name: string;
  skill: string;
  gap: number;
  priority_category: string;
  actionable_advice: string;
};

const messageOf = (e: unknown) => (e instanceof Error ? e.message : String(e));

/**
 * FeedbackLoopPanel composes three INDEPENDENT signals side by side:
 * employer-observed feedback, INAURA-verified gaps, and roadmap next steps.
 * Display-only linkage — employer feedback never writes into skill assessments.
 */
export default function FeedbackLoopPanel({ applicationId }: { applicationId: string }) {
  const [feedback, setFeedback] = useState<EmployerFeedback | null>(null);
  const [gaps, setGaps] = useState<Gap[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    Promise.allSettled([getFeedback(applicationId), getGaps()]).then(([fb, gp]) => {
      if (!alive) return;
      if (fb.status === "fulfilled") setFeedback(fb.value);
      else if (!String(messageOf(fb.reason)).includes("404")) setError(messageOf(fb.reason));
      if (gp.status === "fulfilled") setGaps((gp.value as Gap[]).slice(0, 5));
      setLoading(false);
    });
    return () => {
      alive = false;
    };
  }, [applicationId]);

  if (loading) return <p className="fbloop__wait">Loading feedback loop…</p>;

  return (
    <section className="fbloop" aria-label="Feedback loop">
      <h3>Feedback loop</h3>
      <p className="fbloop__note">
        Employer observations are an independent signal. They do not change INAURA-verified
        assessments — use them together to decide what to practise next.
      </p>
      {error && <p className="fbloop__error">{error}</p>}
      {feedback && feedback.skills.some((s) => (s.skill_gap ?? 0) > 0.05) && (
        <p className="fbloop__note" role="note">
          Career development context: your employer feedback suggests deeper{" "}
          <strong>
            {feedback.skills
              .filter((s) => (s.skill_gap ?? 0) > 0.05)
              .sort((a, b) => (b.skill_gap ?? 0) - (a.skill_gap ?? 0))
              .slice(0, 2)
              .map((s) => s.skill_name || "skill")
              .join(", ")}
          </strong>{" "}
          practice may be useful. Compare with your INAURA-verified gaps — no roadmap task is
          created automatically.
        </p>
      )}
      <div className="fbloop__cols">
        <div>
          <h4>Employer-observed</h4>
          {!feedback ? (
            <p>No employer feedback yet for this application.</p>
          ) : (
            <>
              <ul className="fbloop__list">
                {(
                  [
                    ["Technical ability", feedback.technical_ability],
                    ["Communication", feedback.communication],
                    ["Problem solving", feedback.problem_solving],
                    ["Project readiness", feedback.project_readiness],
                    ["Role readiness", feedback.role_readiness],
                    ["Overall", feedback.overall_rating],
                  ] as [string, number | null][]
                ).map(([label, v]) => (
                  <li key={label}>
                    {label}: <strong>{v ?? "—"}/5</strong>
                  </li>
                ))}
              </ul>
              {feedback.skills.length > 0 && (
                <ul className="fbloop__list">
                  {feedback.skills.map((s) => (
                    <li key={s.id}>
                      <strong>{s.skill_name || `Skill ${s.skill_id.slice(0, 8)}…`}</strong>
                      {s.expected_level != null && s.observed_level != null && (
                        <>
                          : expected {Math.round(s.expected_level * 100)}%, observed{" "}
                          {Math.round(s.observed_level * 100)}% → gap{" "}
                          <strong>{Math.round((s.skill_gap ?? 0) * 100)}pp</strong>
                        </>
                      )}
                      {s.comment && <em> — {s.comment}</em>}
                    </li>
                  ))}
                </ul>
              )}
              {feedback.overall_comment && <p className="fbloop__quote">“{feedback.overall_comment}”</p>}
            </>
          )}
        </div>
        <div>
          <h4>INAURA-verified gaps</h4>
          {gaps.length === 0 ? (
            <p>
              No gap data yet. <Link to="/analysis">Run the analysis</Link> to see verified gaps.
            </p>
          ) : (
            <ul className="fbloop__list">
              {gaps.map((g) => (
                <li key={g.canonical_name}>
                  {g.skill}: gap <strong>{Math.round(g.gap * 100)}pp</strong> ({g.priority_category})
                </li>
              ))}
            </ul>
          )}
          <Link to="/roadmap" className="fbloop__cta">
            Open roadmap
          </Link>
        </div>
      </div>
    </section>
  );
}
