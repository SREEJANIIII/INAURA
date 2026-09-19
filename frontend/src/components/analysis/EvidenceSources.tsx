import { useState } from "react";
import { Link } from "react-router-dom";
import type { Evidence, GithubRepo, Project } from "../../services/evidence";
import { evidenceTypeLabel, sourceUsage } from "./analysisModel";

type Props = {
  evidence: Evidence[];
  projects: Project[];
  repos: GithubRepo[];
  busyId: string | null;
  onToggleEvidence: (id: string, exclude: boolean, type: "evidence" | "project") => void;
  onToggleEvidenceAi: (id: string, ai: boolean, type: "evidence" | "project") => void;
  onToggleRepo: (fullName: string, exclude: boolean) => void;
  onToggleRepoAi: (fullName: string, ai: boolean) => void;
};

type Row = {
  id: string;
  title: string;
  meta: string;
  excluded: boolean;
  ai: boolean;
  onUse: (use: boolean) => void;
  onAi: (ai: boolean) => void;
};

function SourceRow({ row, busy }: { row: Row; busy: boolean }) {
  return (
    <li className={`an-src${row.excluded ? " is-off" : ""}`}>
      <span className="an-src__text">
        <span className="an-src__title">{row.title}</span>
        {row.meta && <span className="an-src__meta">{row.meta}</span>}
      </span>
      <label className="an-src__ai">
        <input type="checkbox" checked={row.ai} disabled={busy} onChange={(e) => row.onAi(e.target.checked)} />
        AI-assisted
      </label>
      <button
        type="button"
        role="switch"
        aria-checked={!row.excluded}
        aria-label={`Use ${row.title} in analysis`}
        className="an-switch"
        disabled={busy}
        onClick={() => row.onUse(row.excluded)}
      >
        <span className="an-switch__knob" />
      </button>
    </li>
  );
}

export default function EvidenceSources(props: Props) {
  const { evidence, projects, repos, busyId } = props;
  const [showRepos, setShowRepos] = useState(false);
  const usage = sourceUsage(evidence, projects, repos);

  if (usage.total === 0) {
    return (
      <p className="an-empty">
        No evidence sources yet. <Link to="/analysis" className="an-link">Add evidence</Link> and run your analysis again.
      </p>
    );
  }

  const profileRows: Row[] = evidence
    .filter((e) => e.evidence_type !== "github")
    .map((e) => ({
      id: e.id,
      title: e.title || evidenceTypeLabel(e.evidence_type),
      meta: [evidenceTypeLabel(e.evidence_type), e.verification_status === "verified" ? "verified" : e.verification_status === "failed" ? "couldn’t be verified" : "not verified"].join(", "),
      excluded: !!e.is_excluded,
      ai: !!e.is_ai_assisted,
      onUse: (use) => props.onToggleEvidence(e.id, !use, "evidence"),
      onAi: (ai) => props.onToggleEvidenceAi(e.id, ai, "evidence"),
    }));

  const projectRows: Row[] = projects.map((p) => ({
    id: p.id,
    title: p.name,
    meta: p.technologies?.length ? p.technologies.slice(0, 5).join(", ") : "Project",
    excluded: !!p.is_excluded,
    ai: !!p.is_ai_assisted,
    onUse: (use) => props.onToggleEvidence(p.id, !use, "project"),
    onAi: (ai) => props.onToggleEvidenceAi(p.id, ai, "project"),
  }));

  const repoRows: Row[] = repos.map((r) => ({
    id: r.full_name,
    title: r.full_name,
    meta: [
      r.fork ? "Fork" : "Original",
      r.status === "inspected" ? "inspected" : r.status === "failed" ? "inspection unavailable" : r.status === "skipped_low_evidence" ? "skipped, low evidence" : "discovered",
      r.archived ? "archived" : "",
      r.pushed_at ? `updated ${new Date(r.pushed_at).toLocaleDateString(undefined, { month: "short", year: "numeric" })}` : "",
    ]
      .filter(Boolean)
      .join(", "),
    excluded: r.is_excluded,
    ai: r.is_ai_assisted,
    onUse: (use) => props.onToggleRepo(r.full_name, !use),
    onAi: (ai) => props.onToggleRepoAi(r.full_name, ai),
  }));

  const reposUsed = repos.filter((r) => !r.is_excluded).length;
  const repoList = showRepos ? repoRows : repoRows.slice(0, 3);

  return (
    <div className="an-sources">
      <div className="an-sources__summary">
        <p>
          Your analysis currently uses <strong className="an-num">{usage.used}</strong> of{" "}
          <span className="an-num">{usage.total}</span> evidence items, across{" "}
          <strong className="an-num">{usage.kinds}</strong> kinds of source.
        </p>
        <p className="an-note">
          Switching a source off removes it from scoring and recalculates your analysis. Your raw evidence is kept. Mark anything built with heavy AI help as AI-assisted so it counts for less.
        </p>
      </div>

      <div className="an-sources__groups">
        {profileRows.length > 0 && (
          <div className="an-sgroup">
            <p className="an-sgroup__title">Profiles and files <span className="an-faint an-num">{profileRows.filter((r) => !r.excluded).length}/{profileRows.length} used</span></p>
            <ul>{profileRows.map((row) => <SourceRow key={row.id} row={row} busy={busyId === row.id} />)}</ul>
          </div>
        )}
        {projectRows.length > 0 && (
          <div className="an-sgroup">
            <p className="an-sgroup__title">Projects <span className="an-faint an-num">{projectRows.filter((r) => !r.excluded).length}/{projectRows.length} used</span></p>
            <ul>{projectRows.map((row) => <SourceRow key={row.id} row={row} busy={busyId === row.id} />)}</ul>
          </div>
        )}
        {repoRows.length > 0 && (
          <div className="an-sgroup an-sgroup--wide">
            <p className="an-sgroup__title">GitHub repositories <span className="an-faint an-num">{reposUsed}/{repoRows.length} used</span></p>
            <ul>{repoList.map((row) => <SourceRow key={row.id} row={row} busy={busyId === row.id} />)}</ul>
            {repoRows.length > 3 && (
              <button type="button" className="an-more" onClick={() => setShowRepos((s) => !s)}>
                {showRepos ? "Show fewer" : `Show all ${repoRows.length} repositories`}
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
