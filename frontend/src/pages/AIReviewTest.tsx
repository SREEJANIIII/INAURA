import { useState } from "react";
import { Link } from "react-router-dom";
import { runAiReview, type AIReviewResult } from "../services/aiReview";
import Button from "../components/ui/Button";
import "./AIReviewTest.css";

type Review = Record<string, any>;

function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function Score({ value, label }: { value: unknown; label: string }) {
  const v = num(value);
  return (
    <div className="airev-score">
      <div className="airev-score-value">{v === null ? "—" : `${Math.round(v)} / 100`}</div>
      <div className="airev-score-label">{label}</div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="airev-section">
      <h2 className="airev-section-title">{title}</h2>
      {children}
    </section>
  );
}

export default function AIReviewTest() {
  const [result, setResult] = useState<AIReviewResult | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showRaw, setShowRaw] = useState(false);

  const handleRun = async () => {
    setRunning(true);
    setError(null);
    try {
      const res = await runAiReview();
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "AI review failed");
    } finally {
      setRunning(false);
    }
  };

  const review: Review = (result?.review || {}) as Review;
  const ratings: Review = (review.ratings || {}) as Review;
  const usage = result?.meta.usage;

  return (
    <div className="airev">
      <header className="airev-header">
        <div className="container">
          <Link to="/dashboard" className="airev-back">← Back to Dashboard</Link>
          <div className="airev-badge">EXPERIMENTAL — ONE LLM CALL</div>
          <h1 className="airev-title">AI Career Intelligence</h1>
          <p className="airev-subtitle">
            Experimental one-call review: all INAURA data is combined into a single
            context and analyzed by Gemini in exactly one LLM invocation. This is not
            an official INAURA score.
          </p>
          <Button variant="secondary" size="sm" onClick={handleRun} disabled={running}>
            {running ? "Running AI review…" : result ? "Re-run AI Career Review" : "Run AI Career Review"}
          </Button>
        </div>
      </header>

      <main className="container airev-main">
        {error && (
          <div className="airev-error" role="alert">{error}</div>
        )}

        {result && (
          <>
            <section className="airev-stats">
              <div><strong>LLM Calls:</strong> {result.meta.llm_calls}</div>
              <div><strong>Model:</strong> {result.meta.model}</div>
              <div><strong>Sources:</strong> {(result.meta.data_sources || []).join(", ") || "—"}</div>
              <div><strong>Status:</strong> Complete</div>
              <div><strong>Latency:</strong> {(result.meta.latency_ms / 1000).toFixed(1)}s</div>
            </section>

            <section className="airev-hero">
              <Score value={ratings.overall_rating} label="AI Experimental Rating" />
              <div className="airev-hero-grid">
                <Score value={ratings.industry_readiness} label="Industry readiness" />
                <Score value={ratings.technical_strength} label="Technical strength" />
                <Score value={ratings.problem_solving} label="Problem solving" />
                <Score value={ratings.project_strength} label="Project strength" />
                <Score value={ratings.resume_strength} label="Resume strength" />
                <Score value={ratings.profile_strength} label="Profile strength" />
                <Score value={ratings.evidence_strength} label="Evidence strength" />
                <Score value={ratings.interview_readiness} label="Interview readiness" />
              </div>
              {ratings.reasoning && <p className="airev-reasoning">{ratings.reasoning}</p>}
            </section>

            {review.executive_summary && (
              <Section title="Executive summary"><p>{review.executive_summary}</p></Section>
            )}

            {Array.isArray(review.strengths) && review.strengths.length > 0 && (
              <Section title="Strengths">
                <ul>{review.strengths.map((s: any, i: number) => <li key={i}>{String(s)}</li>)}</ul>
              </Section>
            )}

            {Array.isArray(review.critical_gaps) && review.critical_gaps.length > 0 && (
              <Section title="Critical skill gaps">
                <div className="airev-cards">
                  {review.critical_gaps.map((g: any, i: number) => (
                    <div key={i} className="airev-card">
                      <h3>{g.skill || `Gap ${i + 1}`} {g.severity && <span className="airev-sev">{g.severity}</span>}</h3>
                      {g.explanation && <p>{g.explanation}</p>}
                      {g.evidence && <p><strong>Evidence:</strong> {g.evidence}</p>}
                      {g.recommended_action && <p><strong>Action:</strong> {g.recommended_action}</p>}
                    </div>
                  ))}
                </div>
              </Section>
            )}

            {Array.isArray(review.industry_alignment) && review.industry_alignment.length > 0 && (
              <Section title="Industry alignment">
                <table className="airev-table">
                  <thead><tr><th>Skill</th><th>Student</th><th>Industry need</th></tr></thead>
                  <tbody>
                    {review.industry_alignment.map((r: any, i: number) => (
                      <tr key={i}>
                        <td>{r.skill || r.canonical_name || "—"}</td>
                        <td>{r.student ?? r.demonstrated ?? r.level ?? "—"}</td>
                        <td>{r.industry_need ?? r.required ?? r.demand ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Section>
            )}

            {review.dsa_review && Object.keys(review.dsa_review).length > 0 && (
              <Section title="DSA review">
                <pre className="airev-pre">{JSON.stringify(review.dsa_review, null, 2)}</pre>
              </Section>
            )}

            {(review.github_review || review.leetcode_review || review.projects_review ||
              review.resume_review || review.profile_review) && (
              <Section title="Source reviews">
                {[
                  ["GitHub", review.github_review],
                  ["LeetCode", review.leetcode_review],
                  ["Projects", review.projects_review],
                  ["Resume", review.resume_review],
                  ["Profile", review.profile_review],
                ].map(([label, body]: any) => (
                  body && Object.keys(body).length > 0 && (
                    <details key={label} className="airev-details">
                      <summary>{label}</summary>
                      <pre className="airev-pre">{JSON.stringify(body, null, 2)}</pre>
                    </details>
                  )
                ))}
              </Section>
            )}

            {Array.isArray(review.priority_actions) && review.priority_actions.length > 0 && (
              <Section title="Priority actions">
                <ol>{review.priority_actions.map((a: any, i: number) => <li key={i}>{String(a)}</li>)}</ol>
              </Section>
            )}

            {Array.isArray(review.recommendations) && review.recommendations.length > 0 && (
              <Section title="Recommendations">
                <div className="airev-cards">
                  {review.recommendations.map((r: any, i: number) => (
                    <div key={i} className="airev-card">
                      <h3>{r.what || `Recommendation ${i + 1}`} {r.priority && <span className="airev-sev">{r.priority}</span>}</h3>
                      {r.why && <p><strong>Why:</strong> {r.why}</p>}
                      {r.expected_impact && <p><strong>Impact:</strong> {r.expected_impact}</p>}
                      {r.suggested_action && <p><strong>Action:</strong> {r.suggested_action}</p>}
                    </div>
                  ))}
                </div>
              </Section>
            )}

            {Array.isArray(review.roadmap_improvements) && review.roadmap_improvements.length > 0 && (
              <Section title="Roadmap improvements">
                <ul>{review.roadmap_improvements.map((r: any, i: number) => <li key={i}>{String(r)}</li>)}</ul>
              </Section>
            )}

            {Array.isArray(review.warnings) && review.warnings.length > 0 && (
              <Section title="Warnings">
                <ul>{review.warnings.map((w: any, i: number) => <li key={i}>{String(w)}</li>)}</ul>
              </Section>
            )}

            <section className="airev-section">
              <button
                type="button"
                className="airev-raw-toggle"
                onClick={() => setShowRaw((v) => !v)}
              >
                {showRaw ? "Hide raw AI response" : "Show raw AI response"}
              </button>
              {showRaw && (
                <>
                  <p className="airev-meta">
                    Model: {result.meta.model} · Latency: {(result.meta.latency_ms / 1000).toFixed(1)}s ·{" "}
                    {usage && (usage.input_tokens != null || usage.output_tokens != null)
                      ? `Tokens in/out/total: ${usage.input_tokens ?? "?"} / ${usage.output_tokens ?? "?"} / ${usage.total_tokens ?? "?"}`
                      : "Token usage unavailable"}
                  </p>
                  <pre className="airev-pre">{JSON.stringify(review, null, 2)}</pre>
                </>
              )}
            </section>
          </>
        )}
      </main>
    </div>
  );
}
