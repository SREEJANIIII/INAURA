import { useState } from "react";
import { Link } from "react-router-dom";
import {
  runAiReview,
  type AIComparison,
  type AIReviewResult,
} from "../services/aiReview";
import Button from "../components/ui/app-button";
import "./AIReviewTest.css";

const CATEGORY_LABELS: Record<string, string> = {
  agreement: "Agreement",
  partial_agreement: "Partial",
  disagreement: "Disagreement",
  gemini_only: "AI only",
  engine_only: "Engine only",
};

function fmtPct(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value)
    ? `${Math.round(value)}%`
    : "—";
}

function ComparisonSection({ comparison }: { comparison: AIComparison }) {
  const rows = Array.isArray(comparison.rows) ? comparison.rows : [];
  return (
    <>
      <Section title="INAURA vs Gemini">
        <p className="airev-compare-note">
          Deterministic engine estimates on the left, Gemini interpretation on
          the right. Neither side overwrites the other, and Gemini is never
          treated as ground truth.
        </p>
        {rows.length === 0 ? (
          <p className="airev-empty">
            No overlapping skills to compare — one side returned no skill data.
          </p>
        ) : (
          <table className="airev-table">
            <thead>
              <tr>
                <th>Skill</th>
                <th>INAURA</th>
                <th>Gemini</th>
                <th>Comparison</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={i}>
                  <td>{row.skill}</td>
                  <td>
                    {row.deterministic === null
                      ? "—"
                      : row.deterministic.evidence_count === 0 &&
                          row.deterministic.direction === "gap"
                        ? "Evidence gap"
                        : fmtPct(row.deterministic.level_pct)}
                  </td>
                  <td>
                    {row.gemini === null
                      ? "—"
                      : row.gemini.verdict ||
                        fmtPct(row.gemini.level_pct)}
                  </td>
                  <td>
                    <span
                      className={`airev-sev airev-sev--${row.category.replace(/_/g, "-")}`}
                    >
                      {CATEGORY_LABELS[row.category] ?? row.category}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      {comparison.agreements.length > 0 && (
        <Section title="Agreements">
          <ul>
            {comparison.agreements.map((skill, i) => (
              <li key={i}>
                Both systems identify the same outcome for <strong>{skill}</strong>.
              </li>
            ))}
          </ul>
        </Section>
      )}

      {comparison.differences.length > 0 && (
        <Section title="Differences">
          <div className="airev-cards">
            {comparison.differences.map((d, i) => (
              <div key={i} className="airev-card">
                <h3>
                  {d.skill}{" "}
                  <span
                    className={`airev-sev airev-sev--${d.category.replace(/_/g, "-")}`}
                  >
                    {CATEGORY_LABELS[d.category] ?? d.category}
                  </span>
                </h3>
                <p>{d.detail}</p>
              </div>
            ))}
          </div>
        </Section>
      )}

      {comparison.ai_only_insights.length > 0 && (
        <Section title="AI-only insights">
          <ul>
            {comparison.ai_only_insights.map((insight, i) => (
              <li key={i}>
                [{insight.kind}] {insight.text}
              </li>
            ))}
          </ul>
          <p className="airev-compare-note">
            Suggestions not represented in deterministic analysis — review
            before acting on them.
          </p>
        </Section>
      )}

      {comparison.engine_only_insights.length > 0 && (
        <Section title="Engine-only insights">
          <ul>
            {comparison.engine_only_insights.map((insight, i) => (
              <li key={i}>
                <strong>{insight.skill}</strong> — {insight.reason}
                {typeof insight.gap_pct === "number"
                  ? ` (gap ${Math.round(insight.gap_pct)}%)`
                  : ""}
              </li>
            ))}
          </ul>
          <p className="airev-compare-note">
            Evidence-driven findings Gemini did not mention.
          </p>
        </Section>
      )}

      {comparison.warnings.length > 0 && (
        <Section title="Comparison warnings">
          <ul>
            {comparison.warnings.map((warning, i) => (
              <li key={i}>
                <strong>{warning.skill}:</strong> {warning.detail}
              </li>
            ))}
          </ul>
        </Section>
      )}
    </>
  );
}

type Review = Record<string, unknown>;

function isRec(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function field(obj: unknown, key: string): unknown {
  return isRec(obj) ? obj[key] : undefined;
}

function txt(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}

function fmt(value: unknown): string {
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  if (typeof value === "string") return value;
  return "—";
}

function nonEmptyRec(value: unknown): value is Record<string, unknown> {
  return isRec(value) && Object.keys(value).length > 0;
}

function asList(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

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

function StringList({ items }: { items: unknown }) {
  const list = asList(items);
  if (list.length === 0) return null;
  return (
    <ul>
      {list.map((s: unknown, i: number) => (
        <li key={i}>{String(s)}</li>
      ))}
    </ul>
  );
}

function GapCards({ items, fallbackWord }: { items: unknown; fallbackWord: string }) {
  const list = asList(items);
  if (list.length === 0) return null;
  return (
    <div className="airev-cards">
      {list.map((g: unknown, i: number) => {
        const severity = txt(field(g, "severity"));
        return (
          <div key={i} className="airev-card">
            <h3>
              {txt(field(g, "skill")) ?? `${fallbackWord} ${i + 1}`}{" "}
              {severity && <span className="airev-sev">{severity}</span>}
            </h3>
            {txt(field(g, "explanation")) && <p>{txt(field(g, "explanation"))}</p>}
            {txt(field(g, "evidence")) && (
              <p>
                <strong>Evidence:</strong> {txt(field(g, "evidence"))}
              </p>
            )}
            {txt(field(g, "recommended_action")) && (
              <p>
                <strong>Action:</strong> {txt(field(g, "recommended_action"))}
              </p>
            )}
          </div>
        );
      })}
    </div>
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
  const ratings: Review = (isRec(review.ratings) ? review.ratings : {}) as Review;
  const usage = result?.meta.usage;
  const executiveSummary = txt(review.executive_summary);
  const reasoning = txt(ratings.reasoning);

  const sourceSections: Array<{ label: string; body: unknown }> = [
    { label: "GitHub", body: review.github_review },
    { label: "LeetCode", body: review.leetcode_review },
    { label: "Projects", body: review.project_review ?? review.projects_review },
    { label: "Resume", body: review.resume_review },
    { label: "Profile", body: review.profile_review },
    { label: "Resume + Profile", body: review.resume_profile_review },
  ];

  return (
    <div className="airev">
      <header className="airev-header">
        <div className="container">
          <Link to="/career-track" className="airev-back">← Back to Career Track</Link>
          <div className="airev-badge">EXPERIMENTAL — ONE LLM CALL</div>
          <h1 className="airev-title">AI Career Intelligence</h1>
          <p className="airev-subtitle">
            Experimental AI Review — does not affect INAURA&apos;s official score.
            All INAURA data is combined into a single context and analyzed by
            Gemini in exactly one LLM invocation.
          </p>
          <Button variant="secondary" size="sm" onClick={handleRun} disabled={running}>
            {running ? "Running AI review…" : result ? "Re-run AI Career Review" : "Run AI Career Review"}
          </Button>
        </div>
      </header>

      <div className="container airev-main">
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
              {reasoning && <p className="airev-reasoning">{reasoning}</p>}
            </section>

            {executiveSummary && (
              <Section title="Executive summary"><p>{executiveSummary}</p></Section>
            )}

            {result.comparison && <ComparisonSection comparison={result.comparison} />}

            {asList(review.strengths).length > 0 && (
              <Section title="Strengths">
                <StringList items={review.strengths} />
              </Section>
            )}

            {asList(review.weaknesses).length > 0 && (
              <Section title="Weaknesses">
                <StringList items={review.weaknesses} />
              </Section>
            )}

            {asList(review.critical_gaps).length > 0 && (
              <Section title="Critical skill gaps">
                <GapCards items={review.critical_gaps} fallbackWord="Gap" />
              </Section>
            )}

            {asList(review.skill_reviews).length > 0 && (
              <Section title="Skill reviews">
                <div className="airev-cards">
                  {asList(review.skill_reviews).map((r: unknown, i: number) => {
                    const verdict = txt(field(r, "verdict"));
                    return (
                      <div key={i} className="airev-card">
                        <h3>
                          {txt(field(r, "skill")) ?? `Skill ${i + 1}`}{" "}
                          {verdict && <span className="airev-sev">{verdict}</span>}
                        </h3>
                        <p>
                          <strong>Demonstrated:</strong> {fmt(field(r, "demonstrated_level"))}
                          {" · "}<strong>Required:</strong> {fmt(field(r, "required_level"))}
                        </p>
                        {txt(field(r, "explanation")) && <p>{txt(field(r, "explanation"))}</p>}
                      </div>
                    );
                  })}
                </div>
              </Section>
            )}

            {asList(review.evidence_gaps).length > 0 && (
              <Section title="Evidence gaps">
                <GapCards items={review.evidence_gaps} fallbackWord="Gap" />
              </Section>
            )}

            {asList(review.coverage_gaps).length > 0 && (
              <Section title="Coverage gaps">
                <GapCards items={review.coverage_gaps} fallbackWord="Gap" />
              </Section>
            )}

            {asList(review.industry_alignment).length > 0 && (
              <Section title="Industry alignment">
                <table className="airev-table">
                  <thead><tr><th>Skill</th><th>Student</th><th>Industry need</th></tr></thead>
                  <tbody>
                    {asList(review.industry_alignment).map((r: unknown, i: number) => (
                      <tr key={i}>
                        <td>{txt(field(r, "skill")) ?? txt(field(r, "canonical_name")) ?? "—"}</td>
                        <td>{fmt(field(r, "student") ?? field(r, "demonstrated") ?? field(r, "level"))}</td>
                        <td>{fmt(field(r, "industry_need") ?? field(r, "required") ?? field(r, "demand"))}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Section>
            )}

            {nonEmptyRec(review.dsa_review) && (
              <Section title="DSA review">
                <pre className="airev-pre">{JSON.stringify(review.dsa_review, null, 2)}</pre>
              </Section>
            )}

            {sourceSections.some(({ body }) => nonEmptyRec(body)) && (
              <Section title="Source reviews">
                {sourceSections.map(({ label, body }) => (
                  nonEmptyRec(body) && (
                    <details key={label} className="airev-details">
                      <summary>{label}</summary>
                      <pre className="airev-pre">{JSON.stringify(body, null, 2)}</pre>
                    </details>
                  )
                ))}
              </Section>
            )}

            {asList(review.priority_actions).length > 0 && (
              <Section title="Priority actions">
                <ol>{asList(review.priority_actions).map((a: unknown, i: number) => <li key={i}>{String(a)}</li>)}</ol>
              </Section>
            )}

            {asList(review.recommendations).length > 0 && (
              <Section title="Recommendations">
                <div className="airev-cards">
                  {asList(review.recommendations).map((r: unknown, i: number) => (
                    <div key={i} className="airev-card">
                      <h3>
                        {txt(field(r, "what")) ?? `Recommendation ${i + 1}`}{" "}
                        {txt(field(r, "priority")) && (
                          <span className="airev-sev">{txt(field(r, "priority"))}</span>
                        )}
                      </h3>
                      {txt(field(r, "why")) && (
                        <p><strong>Why:</strong> {txt(field(r, "why"))}</p>
                      )}
                      {txt(field(r, "expected_impact")) && (
                        <p><strong>Impact:</strong> {txt(field(r, "expected_impact"))}</p>
                      )}
                      {txt(field(r, "suggested_action")) && (
                        <p><strong>Action:</strong> {txt(field(r, "suggested_action"))}</p>
                      )}
                    </div>
                  ))}
                </div>
              </Section>
            )}

            {asList(review.roadmap_improvements).length > 0 && (
              <Section title="Roadmap improvements">
                <StringList items={review.roadmap_improvements} />
              </Section>
            )}

            {asList(review.warnings).length > 0 && (
              <Section title="Warnings">
                <StringList items={review.warnings} />
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
      </div>
    </div>
  );
}
