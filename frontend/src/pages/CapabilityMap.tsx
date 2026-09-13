import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import Button from "../components/ui/Button";
import { getLatestAnalysis } from "../services/analysis";
import {
  getCapabilityMap,
  type MissingCapability,
  type SkillCapability,
} from "../services/capability";
import "./CapabilityMap.css";

const STATUS_LABELS: Record<string, string> = {
  demonstrated: "Demonstrated",
  developing: "Developing",
  evidence_gap: "Evidence gap",
  skill_gap: "Skill gap",
  industry_gap: "Industry gap",
  insufficient_industry_data: "Insufficient industry data",
};

function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}

function depthName(depth: number): string {
  if (depth >= 4) return "substantial implementation";
  if (depth === 3) return "implementation";
  if (depth === 2) return "configuration";
  if (depth === 1) return "mention";
  return "unverified";
}

function SkillCard({
  entry,
  expanded,
  onToggle,
}: {
  entry: SkillCapability;
  expanded: boolean;
  onToggle: () => void;
}) {
  const pct = Math.round(entry.proficiency * 100);
  const topAction = entry.missing_capabilities[0]?.next_actions[0];
  return (
    <div className="capmap__card">
      <button
        type="button"
        className="capmap__card-head"
        onClick={onToggle}
        aria-expanded={expanded}
      >
        <span className="capmap__card-title">{entry.skill}</span>
        <span className="capmap__bar" aria-hidden="true">
          <span
            className="capmap__bar-fill"
            style={{ width: `${Math.max(0, Math.min(100, pct))}%` }}
          />
        </span>
        <span className="capmap__pct">{pct}%</span>
        <span className={`capmap__badge capmap__badge--${entry.status}`}>
          {statusLabel(entry.status)}
        </span>
        <span className="capmap__chevron" aria-hidden="true">
          {expanded ? "▾" : "▸"}
        </span>
      </button>

      {expanded && (
        <div className="capmap__card-body">
          <p className="capmap__explanation">{entry.explanation}</p>

          {entry.industry_expectations.length > 0 && (
            <section className="capmap__section">
              <h4>Industry expects</h4>
              <ul>
                {entry.industry_expectations.map((exp) => (
                  <li key={exp.capability_id}>
                    ✓ {exp.title}
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
                <p className="capmap__muted">
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
            <section className="capmap__section">
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

          {entry.demonstrated_capabilities.length > 0 && (
            <section className="capmap__section">
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
                  </li>
                ))}
              </ul>
            </section>
          )}

          {entry.evidence_sources.length > 0 && (
            <section className="capmap__section">
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
            <section className="capmap__section">
              <h4>Still develop</h4>
              <ul>
                {entry.missing_capabilities.map((cap: MissingCapability) => (
                  <li key={cap.id}>
                    ⚠ <strong>{cap.title}</strong>{" "}
                    <span className="capmap__muted">
                      ({statusLabel(cap.status)} · priority{" "}
                      {Math.round(cap.priority)})
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {topAction && (
            <section className="capmap__section capmap__next">
              <h4>Next action</h4>
              <p>{topAction}</p>
              {entry.missing_capabilities[0]?.resources.slice(0, 2).map((r) => (
                <div key={r.url} className="capmap__muted">
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
      )}
    </div>
  );
}

export default function CapabilityMap() {
  const [roleInput, setRoleInput] = useState("");
  const [role, setRole] = useState<string | null>(null);
  const [skills, setSkills] = useState<SkillCapability[]>([]);
  const [summary, setSummary] = useState<{ total_skills: number } | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
      const first = data.skills[0]?.skill;
      setExpanded(first ? { [first]: true } : {});
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load capability map");
      setSkills([]);
      setSummary(null);
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

        {!loading &&
          !error &&
          skills.map((entry) => (
            <SkillCard
              key={entry.skill}
              entry={entry}
              expanded={!!expanded[entry.skill]}
              onToggle={() =>
                setExpanded((prev) => ({ ...prev, [entry.skill]: !prev[entry.skill] }))
              }
            />
          ))}

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
