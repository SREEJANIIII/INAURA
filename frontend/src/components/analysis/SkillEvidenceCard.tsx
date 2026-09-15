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
import { useId } from "react";
import type { EvidenceSource, SkillGap } from "../../services/analysis";
import {
  buildWhyBullets,
  classifyEvidenceStrength,
  confidenceLabel,
  depthName,
  formatFileName,
  getEvidenceCategory,
  getEvidenceCategoryLabel,
  getEvidenceLabel,
  getFilesSummaryLine,
  getObservedChecks,
  getOwnershipLabel,
  getUsageDescription,
  getWhyCountsText,
  shortRepoName,
  summarizeRepoEvidence,
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

type RepoRecord = Record<string, unknown>;

function categoryDot(category: string): string {
  if (category === "strong") return "🟢";
  if (category === "supporting") return "🟡";
  if (category === "limited") return "⚪";
  return "⚪";
}

function RepoCard({
  repo,
  idPrefix,
  index,
}: {
  repo: RepoRecord;
  idPrefix: string;
  index: number;
}) {
  const fullName =
    typeof repo["full_name"] === "string"
      ? repo["full_name"]
      : typeof repo["name"] === "string"
        ? repo["name"]
        : "Repository";
  const url = typeof repo["url"] === "string" ? repo["url"] : null;
  const repoFiles = Array.isArray(repo["files"])
    ? repo["files"].filter((f): f is string => typeof f === "string")
    : [];
  const repoDepth = repo["depth"];
  // Per-repo usage must not outrank its own depth (defensive, preserves honesty)
  const repoUsageRaw = repo["usage_status"];
  const repoUsageCoerced = coerceUsageForDepth(repoUsageRaw, repoDepth);
  const category = getEvidenceCategory(repoDepth);
  const categoryLabel = getEvidenceCategoryLabel(category);
  const evidenceLabel = getEvidenceLabel(repoDepth);
  const usageLine = getUsageDescription(repoUsageCoerced || repoUsageRaw, repoDepth, repoFiles.length);
  const filesLine = getFilesSummaryLine(repoFiles.length);
  const isFork = repo["fork"] === true;
  const isArchived = repo["archived"] === true;
  const ownership = getOwnershipLabel(repo["fork"]);
  const whyCounts = getWhyCountsText(repoDepth, isFork, repoFiles.length);
  const observed = getObservedChecks(repoUsageCoerced || repoUsageRaw, repoDepth, repoFiles.length);

  // Primary view: concise filenames only; full paths live in <details>.
  const primaryShown = repoFiles.slice(0, 3).map((f) => formatFileName(f));
  const primaryExtra = repoFiles.length - primaryShown.length;

  // Technical provenance (preserved verbatim in expandable details).
  const repoDepthLabel = typeof repoDepth === "number" ? depthName(repoDepth) : null;
  const repoUsageTechnical = usageStatusLabel(repoUsageCoerced);
  const signalStrength =
    typeof repo["signal_strength"] === "number" ? (repo["signal_strength"] as number) : null;
  const classification = typeof repo["classification"] === "string" ? (repo["classification"] as string) : null;
  const fileImportance =
    typeof repo["file_importance"] === "string" ? (repo["file_importance"] as string) : null;
  const reason = typeof repo["reason"] === "string" ? (repo["reason"] as string) : null;
  const detailsId = `${idPrefix}-repo-${index}`;

  return (
    <li className={`evcard__repocard evcard__repocard--${category}`} data-testid={`repo-card-${category}`}>
      <div className="evcard__repocard-head">
        <span aria-hidden="true" className="evcard__repocard-dot">
          {categoryDot(category)}
        </span>
        <span className="evcard__repocard-name" title={fullName}>
          {url ? (
            <a href={url} target="_blank" rel="noreferrer">
              {shortRepoName(fullName, fullName)}
            </a>
          ) : (
            <strong>{shortRepoName(fullName, fullName)}</strong>
          )}
        </span>
        {ownership && (
          <span className={`evcard__badge evcard__badge--own ${isFork ? "evcard__badge--fork" : ""}`}>
            {ownership}
          </span>
        )}
        {isArchived && <span className="evcard__badge">Archived</span>}
      </div>

      <div className="evcard__repocard-strength">
        <strong>
          {categoryDot(category)} {categoryLabel}
        </strong>
        <span aria-hidden="true"> · </span>
        <span>{evidenceLabel}</span>
      </div>
      <div className="evcard__repocard-usage">{usageLine}</div>
      {filesLine && <div className="evcard__repocard-files-line">{filesLine}</div>}

      {primaryShown.length > 0 && (
        <div className="evcard__repocard-files" aria-label={`Files in ${shortRepoName(fullName, fullName)}`}>
          {primaryShown.join(" · ")}
          {primaryExtra > 0 ? ` +${primaryExtra} more` : ""}
        </div>
      )}

      <details className="evcard__details" id={detailsId}>
        <summary aria-label={`View details for ${shortRepoName(fullName, fullName)}`}>View details ▾</summary>
        <div className="evcard__details-body">
          <h5>Where INAURA found it</h5>
          <dl className="evcard__facts">
            <div>
              <dt>Repository</dt>
              <dd className="evcard__fact-path">{fullName}</dd>
            </div>
            {ownership && (
              <div>
                <dt>Ownership</dt>
                <dd>{ownership}</dd>
              </div>
            )}
            <div>
              <dt>Evidence</dt>
              <dd>
                {evidenceLabel}
                {repoDepthLabel ? ` (Evidence level: ${repoDepthLabel})` : ""}
              </dd>
            </div>
            {repoFiles.length > 0 && (
              <div>
                <dt>Files analyzed</dt>
                <dd>
                  <ul className="evcard__filelist">
                    {repoFiles.map((f, i) => (
                      <li key={i} className="evcard__fact-path">
                        • {f}
                      </li>
                    ))}
                  </ul>
                </dd>
              </div>
            )}
          </dl>

          <h5>What INAURA observed</h5>
          <ul className="evcard__observed">
            {observed.map((o, i) => (
              <li key={i}>✓ {o}</li>
            ))}
          </ul>

          <h5>Why this counts</h5>
          <p className="evcard__why-counts">{whyCounts}</p>

          {/* Full technical provenance — preserved, never removed */}
          <h5 className="evcard__tech-head">Technical provenance</h5>
          <dl className="evcard__facts evcard__facts--tech">
            {typeof repoDepth === "number" && (
              <div>
                <dt>evidence_depth</dt>
                <dd>
                  {String(repoDepth)} ({repoDepthLabel})
                </dd>
              </div>
            )}
            {(typeof repoUsageCoerced === "string" && repoUsageCoerced) || repoUsageTechnical ? (
              <div>
                <dt>usage_status</dt>
                <dd>{typeof repoUsageCoerced === "string" && repoUsageCoerced ? repoUsageCoerced : repoUsageTechnical}</dd>
              </div>
            ) : null}
            {signalStrength !== null && (
              <div>
                <dt>signal_strength</dt>
                <dd>{Math.round(signalStrength * 100)}%</dd>
              </div>
            )}
            {classification && (
              <div>
                <dt>classification</dt>
                <dd>{classification}</dd>
              </div>
            )}
            {fileImportance && (
              <div>
                <dt>file_importance</dt>
                <dd>{fileImportance}</dd>
              </div>
            )}
            {reason && (
              <div>
                <dt>reason</dt>
                <dd>{reason}</dd>
              </div>
            )}
          </dl>

          {url && (
            <a className="evcard__repo-link" href={url} target="_blank" rel="noreferrer">
              View repository on GitHub →
            </a>
          )}
        </div>
      </details>
    </li>
  );
}

function GithubSourceBlock({ source }: { source: EvidenceSource }) {
  const repos = detailRepos(source);
  const files = detailFiles(source);
  const details = isRecord(source.details) ? source.details : {};
  const sourceDepth = details["evidence_depth"];
  const sourceUsageRaw = details["usage_status"];
  // Coerce source-level usage to not outrank source depth (defensive).
  // Source aggregates are shown only at the source level, never per-repo.
  const sourceUsageCoerced = coerceUsageForDepth(sourceUsageRaw, sourceDepth);
  const sourceUsageTechnical = usageStatusLabel(sourceUsageCoerced);
  const sourceDepthLabel = typeof sourceDepth === "number" ? depthName(sourceDepth) : null;
  // Only show source-level usage when it is supported by the accepted depth.
  const sourceUsageSupported =
    sourceUsageTechnical !== "" &&
    typeof sourceDepth === "number" &&
    statusDepth(sourceUsageCoerced) !== null &&
    (statusDepth(sourceUsageCoerced) as number) <= (sourceDepth as number);

  const declaredRepoCount =
    typeof details["repo_count"] === "number" ? (details["repo_count"] as number) : repos.length;
  const summary = summarizeRepoEvidence(repos.map((r) => r["depth"]));
  const totalRepos = summary.total > 0 ? summary.total : declaredRepoCount;

  const detectedPatterns = Array.isArray(details["detected_usage_patterns"])
    ? (details["detected_usage_patterns"] as unknown[]).filter(
        (p): p is string => typeof p === "string",
      )
    : [];
  const fileImportance =
    typeof details["file_importance"] === "string" ? (details["file_importance"] as string) : null;
  const evidenceCount =
    typeof details["evidence_count"] === "number" ? (details["evidence_count"] as number) : null;
  const inspection = details["inspection"];
  const blockId = useId();

  // Group by each repository's OWN depth — never the source aggregate.
  const strongRepos = repos.filter((r) => getEvidenceCategory(r["depth"]) === "strong");
  const supportingRepos = repos.filter((r) => getEvidenceCategory(r["depth"]) === "supporting");
  const limitedRepos = repos.filter((r) => getEvidenceCategory(r["depth"]) === "limited");
  const unknownRepos = repos.filter((r) => getEvidenceCategory(r["depth"]) === "unknown");

  const breakdown: string[] = [];
  if (summary.strong > 0)
    breakdown.push(`${summary.strong} show implementation evidence`);
  if (summary.supporting > 0)
    breakdown.push(`${summary.supporting} ${summary.supporting === 1 ? "provides" : "provide"} supporting evidence`);
  if (summary.limited > 0)
    breakdown.push(`${summary.limited} ${summary.limited === 1 ? "has" : "have"} limited evidence`);

  const renderGroup = (title: string, list: RepoRecord[], startIndex: number) => {
    if (list.length === 0) return null;
    return (
      <div className="evcard__repogroup">
        <h5 className="evcard__repogroup-title">{title}</h5>
        <ul className="evcard__repocards">
          {list.map((repo, i) => (
            <RepoCard key={`${title}-${i}`} repo={repo} idPrefix={blockId} index={startIndex + i} />
          ))}
        </ul>
      </div>
    );
  };

  return (
    <div className="evcard__source evcard__source--github">
      <div className="evcard__source-head">
        <strong>GitHub Evidence</strong>
        {source.is_ai_assisted && (
          <span className="evcard__badge evcard__badge--ai">AI-assisted</span>
        )}
      </div>

      {/* Student-friendly summary — counts derived from repo-level depths */}
      <p className="evcard__github-summary">
        INAURA found evidence of this skill in {totalRepos}{" "}
        {totalRepos === 1 ? "repository" : "repositories"}.
      </p>
      {breakdown.length > 0 && <p className="evcard__github-breakdown">{breakdown.join(" · ")}</p>}

      <details className="evcard__legend">
        <summary>How INAURA reads your GitHub</summary>
        <ul>
          <li>🟢 Strong evidence — Skill found being used in your code</li>
          <li>🟡 Supporting evidence — Skill found configured or referenced in a project</li>
          <li>⚪ Limited evidence — Skill found mainly through mentions or metadata</li>
        </ul>
      </details>

      {source.explanation && <div className="evcard__explanation">{source.explanation}</div>}

      {/* Repository cards — per-repository accepted provenance, never flattened */}
      {repos.length > 0 ? (
        <div className="evcard__repogroups">
          {renderGroup("Strong evidence", strongRepos, 0)}
          {renderGroup("Supporting evidence", supportingRepos, strongRepos.length)}
          {renderGroup("Limited evidence", limitedRepos, strongRepos.length + supportingRepos.length)}
          {renderGroup(
            "Other references",
            unknownRepos,
            strongRepos.length + supportingRepos.length + limitedRepos.length,
          )}
        </div>
      ) : (
        files.length > 0 && (
          <div className="evcard__repo-files">
            {files
              .slice(0, 3)
              .map((f) => formatFileName(f))
              .join(" · ")}
            {files.length > 3 ? ` +${files.length - 3} more` : ""}
          </div>
        )
      )}

      {/* Source-level provenance — aggregate only, kept separate from repo cards */}
      <details className="evcard__details evcard__details--source">
        <summary>About this GitHub evidence</summary>
        <div className="evcard__details-body">
          <dl className="evcard__facts evcard__facts--tech">
            <div>
              <dt>Source confidence</dt>
              <dd>{Math.round(source.reliability * 100)}%</dd>
            </div>
            <div>
              <dt>Source strength</dt>
              <dd>{Math.round(source.strength * 100)}%</dd>
            </div>
            {sourceDepthLabel && (
              <div>
                <dt>Evidence level (aggregate)</dt>
                <dd>
                  {sourceDepthLabel} ({String(sourceDepth)})
                </dd>
              </div>
            )}
            {sourceUsageSupported && (
              <div>
                <dt>usage_status (aggregate)</dt>
                <dd>{sourceUsageTechnical}</dd>
              </div>
            )}
            {evidenceCount !== null && (
              <div>
                <dt>evidence_count</dt>
                <dd>{evidenceCount}</dd>
              </div>
            )}
            {fileImportance && (
              <div>
                <dt>file_importance (aggregate)</dt>
                <dd>{fileImportance}</dd>
              </div>
            )}
            {detectedPatterns.length > 0 && (
              <div>
                <dt>detected_usage_patterns</dt>
                <dd>{detectedPatterns.join(", ")}</dd>
              </div>
            )}
            {typeof details["source_url"] === "string" && details["source_url"] ? (
              <div>
                <dt>source_url</dt>
                <dd className="evcard__fact-path">{String(details["source_url"])}</dd>
              </div>
            ) : null}
            {typeof inspection !== "undefined" && inspection !== null ? (
              <div>
                <dt>inspection</dt>
                <dd className="evcard__fact-path">{JSON.stringify(inspection).slice(0, 500)}</dd>
              </div>
            ) : null}
          </dl>
          <p className="evcard__aggregate-note">
            Aggregate values describe the overall GitHub source. Each repository card above uses that
            repository&apos;s own evidence.
          </p>
        </div>
      </details>
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
