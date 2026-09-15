/**
 * SkillEvidenceCard — explainable per-skill evidence summary.
 *
 * Answers "Why did INAURA give me this score?" from the skill's own
 * evidence payload: proficiency, confidence, evidence strength, status,
 * sources, implementation depth, and relevant repositories/files.
 *
 * Honesty rules (enforced by construction):
 * - every bullet comes from fields present in the payload (see lib/evidenceCard);
 * - absence of evidence is stated explicitly, never as inability;
 * - only repository/file paths and labels are shown, never raw source code.
 */
import type { EvidenceSource, SkillGap } from "../../services/analysis";
import {
  buildWhyBullets,
  classifyEvidenceStrength,
  confidenceLabel,
  depthName,
  usageStatusLabel,
} from "../../lib/evidenceCard";
import "./SkillEvidenceCard.css";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function detailRepos(source: EvidenceSource): Record<string, unknown>[] {
  const details = isRecord(source.details) ? source.details : {};
  const repos = details["repositories"];
  if (!Array.isArray(repos)) return [];
  return repos.filter(isRecord);
}

function detailFiles(source: EvidenceSource): string[] {
  const details = isRecord(source.details) ? source.details : {};
  const files = details["relevant_files"];
  if (!Array.isArray(files)) return [];
  return files.filter((f): f is string => typeof f === "string");
}

function sourceScoreLine(source: EvidenceSource): string | null {
  if (source.source_type !== "assessment") return null;
  const details = isRecord(source.details) ? source.details : {};
  const score = details["score"];
  const assessmentScore = details["assessment_score"];
  const value =
    typeof score === "number" && Number.isFinite(score)
      ? score
      : typeof assessmentScore === "number" && Number.isFinite(assessmentScore)
        ? assessmentScore
        : null;
  if (value === null) return null;
  return `${Math.round(value <= 1 ? value * 100 : value)}%`;
}

const STATUS_DEPTH: Record<string, number> = {
  mentioned: 1,
  declared: 2,
  imported: 3,
  used: 3,
  substantial: 4,
};

function statusDepth(status: unknown): number | null {
  if (typeof status !== "string") return null;
  const d = STATUS_DEPTH[status.toLowerCase()];
  return typeof d === "number" ? d : null;
}

function coerceUsageForDepth(status: unknown, depth: unknown): string {
  const raw = typeof status === "string" ? status.toLowerCase() : "";
  const sDepth = statusDepth(raw);
  const d = typeof depth === "number" ? depth : null;
  if (sDepth === null || d === null) return raw;
  if (sDepth <= d) return raw;
  if (d <= 1) return "mentioned";
  if (d === 2) return "declared";
  if (d === 3) return "used";
  return "substantial";
}

function GithubSourceBlock({ source }: { source: EvidenceSource }) {
  const repos = detailRepos(source);
  const files = detailFiles(source);
  const details = isRecord(source.details) ? source.details : {};
  const sourceDepth = details["evidence_depth"];
  const sourceUsageRaw = details["usage_status"];
  // Coerce source-level usage to not outrank source depth (defensive)
  const sourceUsageCoerced = coerceUsageForDepth(sourceUsageRaw, sourceDepth);
  const sourceUsage = usageStatusLabel(sourceUsageCoerced);
  const sourceDepthLabel = typeof sourceDepth === "number" ? depthName(sourceDepth) : null;

  const repoCount = typeof details["repo_count"] === "number" ? (details["repo_count"] as number) : repos.length;
  const ownedCount = typeof details["owned_count"] === "number" ? (details["owned_count"] as number) : null;
  const forkCount = typeof details["fork_count"] === "number" ? (details["fork_count"] as number) : null;

  return (
    <div className="evcard__source">
      <div className="evcard__source-head">
        <strong>{source.source_label || `GitHub · ${repoCount} ${repoCount === 1 ? "repository" : "repositories"}`}</strong>
        <span className="evcard__source-type">{source.source_type}</span>
        {source.is_ai_assisted && (
          <span className="evcard__badge evcard__badge--ai">AI-assisted</span>
        )}
      </div>

      {/* Overall evidence – source-level accepted signal */}
      <div className="evcard__source-meta">
        <span>Overall evidence: Strength {Math.round(source.strength * 100)}%</span>
        <span aria-hidden="true">·</span>
        <span>Reliability {Math.round(source.reliability * 100)}%</span>
        {sourceDepthLabel && (
          <>
            <span aria-hidden="true">·</span>
            <span>{sourceDepthLabel} evidence</span>
          </>
        )}
      </div>
      {(ownedCount !== null || forkCount !== null) && (
        <div className="evcard__source-meta" style={{ fontSize: "0.85em", opacity: 0.8 }}>
          {ownedCount !== null && <span>{ownedCount} owned</span>}
          {forkCount !== null && forkCount > 0 && (
            <>
              {ownedCount !== null && <span aria-hidden="true"> · </span>}
              <span>{forkCount} forked</span>
            </>
          )}
        </div>
      )}
      {source.explanation && (
        <div className="evcard__explanation">{source.explanation}</div>
      )}

      {/* Repository details – per-repository accepted evidence, never flattened */}
      {repos.length > 0 ? (
        <>
          <div className="evcard__repo-section-label" style={{ marginTop: "0.75rem", fontWeight: 600, fontSize: "0.9em" }}>
            Repository details:
          </div>
          <ul className="evcard__repos">
            {repos.slice(0, 6).map((repo, idx) => {
              const name =
                typeof repo["full_name"] === "string"
                  ? repo["full_name"]
                  : typeof repo["name"] === "string"
                    ? repo["name"]
                    : "repository";
              const url = typeof repo["url"] === "string" ? repo["url"] : null;
              const repoFiles = Array.isArray(repo["files"])
                ? repo["files"].filter((f): f is string => typeof f === "string")
                : [];
              const shown = repoFiles.slice(0, 3);
              const extra = repoFiles.length - shown.length;
              const repoDepth = repo["depth"];
              const repoDepthLabel = typeof repoDepth === "number" ? depthName(repoDepth) : null;
              // Per-repo usage must not outrank its own depth
              const repoUsageRaw = repo["usage_status"];
              const repoUsageCoerced = coerceUsageForDepth(repoUsageRaw, repoDepth);
              const repoUsageLabel = usageStatusLabel(repoUsageCoerced);
              const isFork = repo["fork"] === true;
              const isArchived = repo["archived"] === true;
              return (
                <li key={idx} className="evcard__repo">
                  <div className="evcard__repo-name">
                    →{" "}
                    {url ? (
                      <a href={url} target="_blank" rel="noreferrer">
                        {name}
                      </a>
                    ) : (
                      <strong>{name}</strong>
                    )}
                    {isFork && <span style={{ marginLeft: "0.4em", fontSize: "0.8em", opacity: 0.7 }}>(forked)</span>}
                    {isArchived && <span style={{ marginLeft: "0.4em", fontSize: "0.8em", opacity: 0.7 }}>(archived)</span>}
                  </div>
                  {repoDepthLabel && (
                    <div className="evcard__repo-meta">
                      <span>
                        {repoDepthLabel} evidence
                        {typeof repoUsageCoerced === "string" && repoUsageCoerced ? ` · ${repoUsageCoerced}` : ""}
                      </span>
                    </div>
                  )}
                  {shown.length > 0 && (
                    <div className="evcard__repo-files">
                      {shown.join(", ")}
                      {extra > 0 ? ` (+${extra} more)` : ""}
                    </div>
                  )}
                  {/* Show capped usage only when supported by repo depth */}
                  {repoUsageLabel && typeof repoDepth === "number" && statusDepth(repoUsageCoerced) !== null && (statusDepth(repoUsageCoerced) as number) <= (repoDepth as number) && (
                    <div className="evcard__repo-usage" style={{ fontSize: "0.85em", opacity: 0.85 }}>
                      {repoUsageLabel}
                    </div>
                  )}
                  {!repoDepthLabel && repoUsageLabel && (
                    <div className="evcard__repo-usage" style={{ fontSize: "0.85em", opacity: 0.85 }}>
                      {repoUsageLabel}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
          {/* Fallback for source-level files when no per-repo files shown – only when source depth supports */}
          {files.length > 0 && repos.every((r) => !Array.isArray(r["files"]) || (r["files"] as unknown[]).length === 0) && (
            <div className="evcard__repo-files" style={{ marginTop: "0.5rem" }}>
              → {files.slice(0, 3).join(", ")}
              {files.length > 3 ? ` (+${files.length - 3} more)` : ""}
            </div>
          )}
        </>
      ) : (
        files.length > 0 && (
          <div className="evcard__repo-files">
            → {files.slice(0, 3).join(", ")}
            {files.length > 3 ? ` (+${files.length - 3} more)` : ""}
          </div>
        )
      )}

      {/* Source-level observed usage – only when supported by final accepted depth */}
      {sourceUsage && typeof sourceDepth === "number" && statusDepth(sourceUsageCoerced) !== null && (statusDepth(sourceUsageCoerced) as number) <= (sourceDepth as number) && (
        <div className="evcard__usage">Observed usage: {sourceUsage}</div>
      )}
      {/* If source-level usage was coerced away due to contradiction, do not render a stronger claim */}
    </div>
  );
}

export default function SkillEvidenceCard({ gap }: { gap: SkillGap }) {
  const displayName =
    gap.skills?.display_name ||
    gap.skills?.canonical_name ||
    gap.canonical_name ||
    gap.skill ||
    "Unknown";
  const sources: EvidenceSource[] = gap.evidence_sources || [];
  const maxStrength = sources.reduce(
    (best, s) => Math.max(best, typeof s.strength === "number" ? s.strength : 0),
    0,
  );
  const strength = classifyEvidenceStrength({
    evidenceCount: sources.length,
    evidenceState: gap.evidence_state,
    gapType: gap.gap_type,
    maxSourceStrength: maxStrength,
  });
  const confidence = confidenceLabel(gap.confidence);
  const bullets = buildWhyBullets(displayName, sources);
  const knowsTone =
    strength.key === "strong" || strength.key === "moderate";

  return (
    <section className="evcard" aria-label={`Evidence for ${displayName}`}>
      <div className="evcard__header">
        <div>
          <div className="evcard__eyebrow">Skill Evidence Card</div>
          <h3 className="evcard__title">{displayName}</h3>
          {gap.skills?.category && (
            <div className="evcard__category">{gap.skills.category}</div>
          )}
        </div>
        <span
          className={`evcard__badge evcard__badge--${strength.key}`}
          title={strength.description}
        >
          {strength.label}
        </span>
      </div>

      <div className="evcard__stats">
        <div className="evcard__stat evcard__stat--primary">
          <span className="evcard__stat-label">Proficiency</span>
          <strong className="evcard__stat-value">
            {Math.round(gap.current_proficiency * 100)}%
          </strong>
        </div>
        <div className="evcard__stat">
          <span className="evcard__stat-label">Confidence</span>
          <strong>
            {Math.round(gap.confidence * 100)}% · {confidence}
          </strong>
        </div>
        <div className="evcard__stat">
          <span className="evcard__stat-label">Evidence strength</span>
          <strong>{strength.label}</strong>
        </div>
        <div className="evcard__stat">
          <span className="evcard__stat-label">Evidence status</span>
          <strong>{gap.evidence_state_label || gap.evidence_state || "—"}</strong>
        </div>
      </div>

      {gap.is_overridden && (
        <div className="evcard__note" role="note">
          You marked this skill as not known — it is held at 0%. Your evidence
          history is preserved below.
        </div>
      )}

      <div className="evcard__why">
        <h4>
          {knowsTone
            ? `Why INAURA thinks you know ${displayName}:`
            : `What INAURA found for ${displayName}:`}
        </h4>
        {bullets.length > 0 ? (
          <ul>
            {bullets.map((bullet, idx) => (
              <li key={idx}>{bullet}</li>
            ))}
          </ul>
        ) : (
          <p className="evcard__empty">
            No evidence found. INAURA has no evidence demonstrating this skill.
            This indicates absence of submitted evidence, not confirmed
            inability. Submit a GitHub project, coding profile, coursework,
            certification, or complete an INAURA assessment to demonstrate it.
          </p>
        )}
      </div>

      <div className="evcard__evidence">
        <h4>Evidence ({sources.length})</h4>
        {sources.length === 0 ? (
          <p className="evcard__empty">
            No evidence sources recorded for this skill yet.
          </p>
        ) : (
          sources.map((source, idx) => {
            if (source.source_type === "github") {
              return <GithubSourceBlock key={idx} source={source} />;
            }
            if (source.source_type === "assessment") {
              const scoreLine = sourceScoreLine(source);
              return (
                <div
                  key={idx}
                  className="evcard__source evcard__source--assessment"
                >
                  <div className="evcard__source-head">
                    <strong>{source.source_label || "INAURA Assessment"}</strong>
                    <span className="evcard__badge">Validated</span>
                  </div>
                  {scoreLine && <div>Score: {scoreLine}</div>}
                  <div className="evcard__note evcard__note--subtle">
                    Assessment is a separate, stronger evidence source. GitHub
                    reliability is unchanged (supporting evidence).
                  </div>
                </div>
              );
            }
            return (
              <div key={idx} className="evcard__source">
                <div className="evcard__source-head">
                  <strong>
                    {source.source_label || source.source_type || "Evidence"}
                  </strong>
                  <span className="evcard__source-type">
                    {source.source_type}
                  </span>
                  {source.is_ai_assisted && (
                    <span className="evcard__badge evcard__badge--ai">
                      AI-assisted
                    </span>
                  )}
                </div>
                <div className="evcard__source-meta">
                  <span>
                    Strength: {Math.round(source.strength * 100)}%
                  </span>
                  <span aria-hidden="true">·</span>
                  <span>
                    Reliability: {Math.round(source.reliability * 100)}%
                  </span>
                </div>
                {source.explanation && (
                  <div className="evcard__explanation">
                    {source.explanation}
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>

      <p className="evcard__honesty">
        Repository evidence shows you worked with a technology; only a passed
        assessment shows validated understanding.
      </p>
    </section>
  );
}
