import type { ResumeContent } from "../../../services/resumeBuilder";
import type { ResumeDocEditing } from "../ResumeDocument";
import { EditableBullet, EditableSummary } from "../EditableText";

type Props = {
  content: ResumeContent;
  targetRole: string;
  editing?: ResumeDocEditing;
};

function cleanLabel(url: string, fallback: string): string {
  try {
    const host = new URL(url).hostname.replace(/^www\./, "");
    if (host.includes("github")) return fallback && fallback !== "Link" ? fallback : "GitHub";
    if (host.includes("linkedin")) return "LinkedIn";
    return fallback && fallback !== "Link" ? fallback : host;
  } catch {
    return fallback || url;
  }
}

type EduEntry = {
  school?: string;
  degree?: string;
  branch?: string;
  current_year?: string | number;
  graduation_year?: string | number;
};
type TextEntry = { text?: string };
type CertEntry = { name?: string; issuing_org?: string; completion_year?: string | number; url?: string };

function asText(value: unknown): string {
  return typeof value === "string" ? value : "";
}

export function ClassicATS({ content, targetRole, editing }: Props) {
  const header = content.header ?? {};
  const links = (header.links ?? []).filter((l) => l?.url);
  const contactParts: { label: string; url?: string }[] = [];
  if (header.email) contactParts.push({ label: header.email, url: `mailto:${header.email}` });
  if (header.phone) contactParts.push({ label: header.phone });
  for (const link of links) {
    if (link.url) contactParts.push({ label: link.label || cleanLabel(link.url, "Link"), url: link.url });
  }

  const education = content.education ?? [];
  const skillGroups: Array<[string, string[]]> = Object.entries(content.skill_groups ?? {});
  const skillsFlat = content.skills ?? [];
  const experience = content.experience ?? [];
  const projects = content.projects ?? [];
  const certifications = content.certifications ?? [];
  const achievements = content.achievements ?? [];

  return (
    <>
      <header className="rdoc-header">
        <h1 className="rdoc-name">{header.name || "Your Name"}</h1>
        {targetRole && <p className="rdoc-subtitle">{targetRole}</p>}
        {contactParts.length > 0 && (
          <p className="rdoc-contact">
            {contactParts.map((part, i) => (
              <span key={`${part.label}-${i}`}>
                {i > 0 && <span className="rdoc-sep" aria-hidden="true"> | </span>}
                {part.url ? (
                  <a href={part.url} target="_blank" rel="noreferrer">
                    {part.label}
                  </a>
                ) : (
                  <span>{part.label}</span>
                )}
              </span>
            ))}
          </p>
        )}
      </header>

      {content.summary && (
        <section className="rdoc-section" aria-label="Summary">
          <h2 className="rdoc-heading">Summary</h2>
          {editing ? (
            <EditableSummary
              value={content.summary}
              ariaLabel="Resume summary. Activate to edit."
              onCommit={editing.onSummaryChange}
            />
          ) : (
            <p className="rdoc-text">{content.summary}</p>
          )}
        </section>
      )}

      {education.length > 0 && (
        <section className="rdoc-section" aria-label="Education">
          <h2 className="rdoc-heading">Education</h2>
          {education.map((entry: EduEntry, i: number) => {
            const degreeLine = [entry?.degree, entry?.branch].filter(Boolean).join(", ");
            const yearLine = [entry?.graduation_year, entry?.current_year].filter(Boolean).join(" · ");
            return (
              <div className="rdoc-edu" key={i}>
                <p className="rdoc-edu-line">
                  <strong>{entry?.school || degreeLine || "Education"}</strong>
                  {degreeLine && entry?.school && <span className="rdoc-muted"> — {degreeLine}</span>}
                </p>
                {yearLine && <p className="rdoc-muted">{String(yearLine)}</p>}
              </div>
            );
          })}
        </section>
      )}

      {(skillGroups.length > 0 || skillsFlat.length > 0) && (
        <section className="rdoc-section" aria-label="Technical skills">
          <h2 className="rdoc-heading">Technical Skills</h2>
          {skillGroups.length > 0 ? (
            <div className="rdoc-skills">
              {skillGroups.map(([group, skills]) => (
                <p className="rdoc-text rdoc-skillrow" key={group}>
                  <strong>{group}: </strong>
                  <span>{skills.join(", ")}</span>
                </p>
              ))}
            </div>
          ) : (
            <p className="rdoc-text">{skillsFlat.join(", ")}</p>
          )}
        </section>
      )}

      {experience.length > 0 && (
        <section className="rdoc-section" aria-label="Experience">
          <h2 className="rdoc-heading">Experience</h2>
          <ul className="rdoc-list">
            {experience.map((item: TextEntry | string, i: number) => (
              <li key={i}>{asText(typeof item === "string" ? item : item?.text)}</li>
            ))}
          </ul>
        </section>
      )}

      {projects.length > 0 && (
        <section className="rdoc-section" aria-label="Projects">
          <h2 className="rdoc-heading">Projects</h2>
          {projects.map((project, pi) => (
            <div className="rdoc-project" key={`${project.name}-${pi}`}>
              <div className="rdoc-project-head">
                <p className="rdoc-project-name">{project.name}</p>
                {(project.links ?? []).length > 0 && (
                  <p className="rdoc-project-links">
                    {(project.links ?? []).map((url) => (
                      <a key={url} href={url} target="_blank" rel="noreferrer">
                        {cleanLabel(url, "Link")}
                      </a>
                    ))}
                  </p>
                )}
              </div>
              {(project.technologies?.length ?? 0) > 0 && (
                <p className="rdoc-techline">{(project.technologies ?? []).join(" · ")}</p>
              )}
              <ul className="rdoc-list">
                {(project.bullets ?? []).map((bullet, bi) => (
                  <li key={bi}>
                    {editing ? (
                      <EditableBullet
                        value={bullet}
                        ariaLabel={`Bullet ${bi + 1} for ${project.name}. Activate to edit.`}
                        onCommit={(value) => editing.onBulletChange(pi, bi, value)}
                      />
                    ) : (
                      bullet
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </section>
      )}

      {certifications.length > 0 && (
        <section className="rdoc-section" aria-label="Certifications">
          <h2 className="rdoc-heading">Certifications</h2>
          <ul className="rdoc-list">
            {certifications.map((cert: CertEntry, i: number) => (
              <li key={i}>
                {[cert?.name, cert?.issuing_org].filter(Boolean).join(" — ")}
                {cert?.completion_year ? ` (${cert.completion_year})` : ""}
              </li>
            ))}
          </ul>
        </section>
      )}

      {achievements.length > 0 && (
        <section className="rdoc-section" aria-label="Achievements">
          <h2 className="rdoc-heading">Achievements</h2>
          <ul className="rdoc-list">
            {achievements.map((item: TextEntry | string, i: number) => (
              <li key={i}>{asText(typeof item === "string" ? item : item?.text)}</li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}
