import { forwardRef, useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import Button from "../components/ui/Button";
import { getLatestAnalysis } from "../services/analysis";
import {
  getCapabilityMap,
  type CapabilityExplanation,
  type MissingCapability,
  type SkillCapability,
} from "../services/capability";
import "./CapabilityMap.css";

const STATUS_LABELS: Record<string, string> = {
  demonstrated: "Demonstrated",
  developing: "Developing",
  unverified: "Unverified",
  confirmed_gap: "Confirmed gap",
  evidence_gap: "Evidence gap",
  skill_gap: "Skill gap",
  industry_gap: "Industry gap",
  insufficient_industry_data: "Insufficient industry data",
};

function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}

const STRENGTH_LABELS: Record<string, string> = {
  strong: "Strong",
  moderate: "Moderate",
  weak: "Weak",
  insufficient: "Insufficient",
};

function strengthLabel(strength: string): string {
  return STRENGTH_LABELS[strength] ?? strength;
}

function WhyDetails({ explanation }: { explanation: CapabilityExplanation }) {
  const matched = explanation.matched_signals ?? [];
  const missing = explanation.missing_signals ?? [];
  return (
    <details className="capmap__explain">
      <summary>Why INAURA thinks this</summary>
      {explanation.status_reason && <p>{explanation.status_reason}</p>}
      {explanation.evidence_strength && (
        <p className="capmap__muted">
          Evidence strength: <strong>{strengthLabel(explanation.evidence_strength)}</strong>
        </p>
      )}
      {matched.length > 0 && (
        <>
          <p className="capmap__muted">
            <strong>Observed</strong>
          </p>
          <ul>
            {matched.map((sig, i) => (
              <li key={`${sig.signal}-${i}`}>
                • {sig.statement}
                {sig.source_type && (
                  <span className="capmap__muted"> — {sig.source_type}</span>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
      {missing.length > 0 && (
        <>
          <p className="capmap__muted">
            <strong>Still needs evidence for</strong>
          </p>
          <ul>
            {missing.map((sig, i) => (
              <li key={`${sig.signal}-${i}`}>• {sig.statement}</li>
            ))}
          </ul>
        </>
      )}
      {matched.length === 0 && (
        <p className="capmap__muted">No supporting evidence was found yet.</p>
      )}
    </details>
  );
}

function depthName(depth: number): string {
  if (depth >= 4) return "substantial implementation";
  if (depth === 3) return "implementation";
  if (depth === 2) return "configuration";
  if (depth === 1) return "mention";
  return "unverified";
}

interface BigSkillCardProps {
  entry: SkillCapability;
  onClose: () => void;
}

const BigSkillCard = forwardRef<HTMLDivElement, BigSkillCardProps>(
  function BigSkillCard({ entry, onClose }, ref) {
    const pct = Math.round(entry.proficiency * 100);
    const topAction = entry.missing_capabilities[0]?.next_actions[0];
    const explainById = Object.fromEntries(
      (entry.capabilities ?? [])
        .filter((c) => c.capability_explanation)
        .map((c) => [c.id, c.capability_explanation as CapabilityExplanation]),
    );

    return (
      <div
        ref={ref}
        className="capmap__big-card"
        role="region"
        aria-label={`Detailed capability card for ${entry.skill}`}
      >
        <div className="capmap__big-card-header">
          <div className="capmap__big-card-title-group">
            <div className="capmap__big-card-tag-row">
              <span className={`capmap__badge capmap__badge--${entry.status}`}>
                {statusLabel(entry.status)}
              </span>
              <span className="capmap__pct-badge">{pct}% Proficiency</span>
            </div>
            <h2 className="capmap__big-card-title">{entry.skill}</h2>
          </div>

          <div className="capmap__big-card-actions">
            <div className="capmap__big-card-bar-wrap" title={`${pct}% proficiency`}>
              <div className="capmap__bar" aria-hidden="true">
                <span
                  className="capmap__bar-fill"
                  style={{ width: `${Math.max(0, Math.min(100, pct))}%` }}
                />
              </div>
            </div>
            <button
              type="button"
              className="capmap__big-card-close"
              onClick={onClose}
              aria-label="Close skill card"
              title="Close details"
            >
              <span aria-hidden="true">✕</span>
              <span className="capmap__big-card-close-text">Close</span>
            </button>
          </div>
        </div>

        <div className="capmap__big-card-body">
          {entry.explanation && (
            <div className="capmap__big-card-lead">
              <p className="capmap__explanation">{entry.explanation}</p>
            </div>
          )}

          <div className="capmap__big-card-grid">
            <div className="capmap__big-card-col">
              {entry.industry_expectations.length > 0 && (
                <section className="capmap__section capmap__section--card">
                  <h4>Industry expects</h4>
                  <ul>
                    {entry.industry_expectations.map((exp) => (
                      <li key={exp.capability_id}>
                        ✓ <strong>{exp.title}</strong>
                        {exp.relevance.length > 0 && (
                          <span className="capmap__muted">
                            {" "}
                            — {exp.relevance.join("; ")}
                          </span>
                        )}
                      </li>
                    ))}
                  </ul>
                  {(entry.requirement.source || entry.requirement.evidence_strength) && (
                    <p className="capmap__muted capmap__source-meta">
                      Basis: {entry.requirement.source}
                      {entry.requirement.evidence_strength
                        ? ` (${entry.requirement.evidence_strength} evidence)`
                        : ""}
                      {entry.requirement.source_url ? (
                        <>
                          {" · "}
                          <a
                            href={entry.requirement.source_url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            source
                          </a>
                        </>
                      ) : null}
                    </p>
                  )}
                </section>
              )}

              {entry.capabilities.length > 0 && (
                <section className="capmap__section capmap__section--card">
                  <h4>What you should be able to do</h4>
                  <ul>
                    {Array.from(
                      new Set(
                        entry.capabilities.flatMap((c) => c.observable_abilities),
                      ),
                    ).map((ability) => (
                      <li key={ability}>{ability}</li>
                    ))}
                  </ul>
                </section>
              )}

              {entry.what_inaura_knows && (
                <section className="capmap__section capmap__section--card">
                  <h4>What INAURA knows</h4>
                  {entry.what_inaura_knows.summary && (
                    <p className="capmap__explanation">
                      {entry.what_inaura_knows.summary}
                    </p>
                  )}
                  {entry.what_inaura_knows.demonstrated_areas.length > 0 && (
                    <div className="capmap__subgroup">
                      <p className="capmap__muted capmap__subgroup-title">
                        <strong>Demonstrated</strong>
                      </p>
                      <ul>
                        {entry.what_inaura_knows.demonstrated_areas.map((area) => (
                          <li key={area.capability_id}>
                            ✓ {area.capability_title}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {entry.what_inaura_knows.developing_areas.length > 0 && (
                    <div className="capmap__subgroup">
                      <p className="capmap__muted capmap__subgroup-title">
                        <strong>Developing</strong>
                      </p>
                      <ul>
                        {entry.what_inaura_knows.developing_areas.map((area) => (
                          <li key={area.capability_id}>
                            ◐ {area.capability_title}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {entry.what_inaura_knows.unverified_areas.length > 0 && (
                    <div className="capmap__subgroup">
                      <p className="capmap__muted capmap__subgroup-title">
                        <strong>Unverified</strong>
                      </p>
                      <ul>
                        {entry.what_inaura_knows.unverified_areas.map((area) => (
                          <li key={area.capability_id}>
                            ? {area.capability_title}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </section>
              )}
            </div>

            <div className="capmap__big-card-col">
              {entry.demonstrated_capabilities.length > 0 && (
                <section className="capmap__section capmap__section--card">
                  <h4>What INAURA found</h4>
                  <ul>
                    {entry.demonstrated_capabilities.map((cap) => (
                      <li key={cap.id}>
                        ✓ <strong>{cap.title}</strong>
                        {cap.evidence.slice(0, 2).map((ev, i) => (
                          <span key={i} className="capmap__muted">
                            {" "}
                            — {ev.provider}
                            {ev.repository ? ` · ${ev.repository}` : ""}
                            {ev.depth >= 3 ? ` (${depthName(ev.depth)})` : ""}
                          </span>
                        ))}
                        {explainById[cap.id] && (
                          <WhyDetails explanation={explainById[cap.id]} />
                        )}
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              {entry.evidence_sources.length > 0 && (
                <section className="capmap__section capmap__section--card">
                  <h4>Evidence</h4>
                  <ul className="capmap__evidence">
                    {entry.evidence_sources.slice(0, 6).map((ev, i) => (
                      <li key={i}>
                        <strong>{ev.provider || "evidence"}</strong>
                        {ev.repository ? (
                          <>
                            {" → "}
                            {ev.repository}
                          </>
                        ) : null}
                        {ev.files.slice(0, 3).map((f) => (
                          <span key={f} className="capmap__file">
                            {" → "}
                            {f}
                          </span>
                        ))}
                        {ev.files.length > 3 ? (
                          <span className="capmap__muted">
                            {" "}
                            (+{ev.files.length - 3} more)
                          </span>
                        ) : null}
                        <span className="capmap__muted">
                          {" "}
                          · {depthName(ev.depth)} evidence
                        </span>
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              {entry.missing_capabilities.length > 0 && (
                <section className="capmap__section capmap__section--card">
                  <h4>Still develop</h4>
                  <ul>
                    {entry.missing_capabilities.map((cap: MissingCapability) => (
                      <li key={cap.id}>
                        ⚠ <strong>{cap.title}</strong>{" "}
                        <span className="capmap__muted">
                          ({statusLabel(cap.status)} · priority{" "}
                          {Math.round(cap.priority)})
                        </span>
                        {explainById[cap.id] && (
                          <WhyDetails explanation={explainById[cap.id]} />
                        )}
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              {topAction && (
                <section className="capmap__section capmap__next">
                  <h4>Next action</h4>
                  <p>{topAction}</p>
                  {entry.missing_capabilities[0]?.resources.slice(0, 3).map((r) => (
                    <div key={r.url} className="capmap__next-resource">
                      <a href={r.url} target="_blank" rel="noreferrer">
                        {r.title}
                      </a>
                      {r.provider ? ` — ${r.provider}` : ""}
                    </div>
                  ))}
                </section>
              )}

              {entry.status === "insufficient_industry_data" && (
                <p className="capmap__empty">
                  INAURA does not have enough industry evidence to define
                  capabilities for this skill, so none are invented here.
                </p>
              )}
            </div>
          </div>
        </div>
      </div>
    );
  },
);

export default function CapabilityMap() {
  const [roleInput, setRoleInput] = useState("");
  const [role, setRole] = useState<string | null>(null);
  const [skills, setSkills] = useState<SkillCapability[]>([]);
  const [summary, setSummary] = useState<{ total_skills: number } | null>(null);
  const [selectedSkill, setSelectedSkill] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cardRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async (targetRole: string) => {
    const trimmed = targetRole.trim();
    if (!trimmed) {
      setError("Enter a target role to load its capability map.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const data = await getCapabilityMap({ target_role: trimmed });
      setRole(data.role);
      setSkills(data.skills);
      setSummary(data.summary);
      setSelectedSkill(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load capability map");
      setSkills([]);
      setSummary(null);
      setSelectedSkill(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    getLatestAnalysis()
      .then((analysis) => {
        if (!active) return;
        const preset = analysis.target_role || "";
        setRoleInput(preset);
        if (preset) void load(preset);
      })
      .catch(() => {
        // No prior analysis: user enters a role manually (empty state below).
      });
    return () => {
      active = false;
    };
  }, [load]);

  useEffect(() => {
    if (selectedSkill && cardRef.current) {
      cardRef.current.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [selectedSkill]);

  const selectedEntry =
    skills.find((item) => item.skill === selectedSkill) ?? null;

  return (
    <div className="results">
      <header className="results__header">
        <div className="container">
          <Link to="/analysis/results" className="results__back">
            ← Back to Results
          </Link>
          <div className="eyebrow" style={{ marginTop: 12 }}>
            INAURA Skill Capability Map
          </div>
          <h1 className="results__title">
            {role ? `${role}` : "Capability Map"}
          </h1>
          <div className="results__meta">
            <span>
              What the industry expects, what you can already do, what proves
              it, and what to learn next — per skill.
            </span>
          </div>
          <form
            className="capmap__controls"
            onSubmit={(e) => {
              e.preventDefault();
              void load(roleInput);
            }}
          >
            <input
              className="capmap__input"
              value={roleInput}
              onChange={(e) => setRoleInput(e.target.value)}
              placeholder="Target role, e.g. Backend Developer"
              aria-label="Target role"
            />
            <Button variant="primary" size="md" type="submit">
              {loading ? "Loading…" : "Load map"}
            </Button>
          </form>
        </div>
      </header>

      <main className="container results__main">
        {loading && (
          <div style={{ padding: "2rem 0", textAlign: "center", color: "#64748b" }}>
            Loading capability map…
          </div>
        )}

        {!loading && error && (
          <div className="results__error" role="alert">
            <h2>Couldn&apos;t load the capability map</h2>
            <p>{error}</p>
          </div>
        )}

        {!loading && !error && skills.length === 0 && (
          <div className="results__error">
            <h2>No capability data yet</h2>
            <p>
              Enter a target role above to build its capability map. Skills
              without industry evidence are marked insufficient rather than
              invented.
            </p>
          </div>
        )}

        {!loading && !error && skills.length > 0 && (
          <>
            <div className="capmap__selector-wrap">
              <div className="capmap__selector-header">
                <span className="capmap__selector-label">
                  Skills ({skills.length})
                </span>
                <span className="capmap__selector-hint">
                  {selectedSkill
                    ? "Click the active skill or close button to collapse"
                    : "Click any skill to view full details"}
                </span>
              </div>
              <div
                className="capmap__skill-list"
                role="tablist"
                aria-label="Skills in capability map"
              >
                {skills.map((entry) => {
                  const isSelected = selectedSkill === entry.skill;
                  return (
                    <button
                      key={entry.skill}
                      type="button"
                      role="tab"
                      aria-selected={isSelected}
                      className={`capmap__skill-pill ${
                        isSelected ? "capmap__skill-pill--active" : ""
                      }`}
                      onClick={() =>
                        setSelectedSkill((prev) =>
                          prev === entry.skill ? null : entry.skill,
                        )
                      }
                    >
                      <span className="capmap__skill-pill-name">
                        {entry.skill}
                      </span>
                      <span
                        className={`capmap__skill-pill-dot capmap__dot--${entry.status}`}
                        title={statusLabel(entry.status)}
                        aria-hidden="true"
                      />
                    </button>
                  );
                })}
              </div>
            </div>

            {selectedEntry ? (
              <BigSkillCard
                ref={cardRef}
                entry={selectedEntry}
                onClose={() => setSelectedSkill(null)}
              />
            ) : (
              <div className="capmap__empty-prompt">
                <div className="capmap__empty-prompt-icon" aria-hidden="true">
                  🗺️
                </div>
                <h3>Select a skill to view details</h3>
                <p>
                  Click any skill name above to open its capability
                  breakdown, industry expectations, verified evidence, and next
                  actions.
                </p>
              </div>
            )}
          </>
        )}

        {!loading && !error && summary && (
          <p style={{ color: "#64748b", fontSize: "0.85rem" }}>
            {summary.total_skills} skills in map · proficiency and readiness
            unchanged — this map explains, it does not rescore.
          </p>
        )}
      </main>
    </div>
  );
}
