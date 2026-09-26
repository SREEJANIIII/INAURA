import type { ResumeContent } from "../../../services/resumeBuilder";
import type { ResumeDocEditing } from "../ResumeDocument";
import { EditableSummary } from "../EditableText";
import { TemplateBullets } from "./TemplateBullets";
import { asText, getContactParts, hostLabel } from "./shared";

type Props = {
  content: ResumeContent;
  targetRole: string;
  editing?: ResumeDocEditing;
};

type EduEntry = {
  school?: string;
  degree?: string;
  branch?: string;
  current_year?: string | number;
  graduation_year?: string | number;
};
type TextEntry = { text?: string };
type CertEntry = { name?: string; issuing_org?: string; completion_year?: string | number };

/**
 * Modern Engineering template — presentation only.
 * Same ResumeData as every template: left-aligned header with a restrained
 * indigo accent, stronger project titles, two-column skill grid on wide
 * screens. No generation, filtering, or data mutation.
 */
export function ModernEngineering({ content, targetRole, editing }: Props) {
  const header = content.header ?? {};
  const contact = getContactParts(header);
  const education = (content.education ?? []) as EduEntry[];
  const skillGroups: Array<[string, string[]]> = Object.entries(content.skill_groups ?? {});
  const skillsFlat = content.skills ?? [];
  const experience = content.experience ?? [];
  const projects = content.projects ?? [];
  const certifications = (content.certifications ?? []) as CertEntry[];
  const achievements = content.achievements ?? [];

  return (
    <>
      <header className="meng-header">
        <h1 className="meng-name">{header.name || "Your Name"}</h1>
        {targetRole && <p className="meng-role">{targetRole}</p>}
        {contact.length > 0 && (
          <p className="meng-contact">
            {contact.map((part, i) => (
              <span key={`${part.label}-${i}`}>
                {i > 0 && (
                  <span className="meng-sep" aria-hidden="true">
                    {" · "}
                  </span>
                )}
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
        <section className="meng-section" aria-label="Summary">
          <h2 className="meng-heading">Summary</h2>
          {editing ? (
            <EditableSummary
              value={content.summary}
              ariaLabel="Resume summary. Activate to edit."
              onCommit={editing.onSummaryChange}
            />
          ) : (
            <p className="meng-text">{content.summary}</p>
          )}
        </section>
      )}

      {education.length > 0 && (
        <section className="meng-section" aria-label="Education">
          <h2 className="meng-heading">Education</h2>
          {education.map((entry, i) => {
            const degreeLine = [entry?.degree, entry?.branch].filter(Boolean).join(", ");
            const yearLine = [entry?.graduation_year, entry?.current_year].filter(Boolean).join(" · ");
            return (
              <div className="meng-edu" key={i}>
                <p className="meng-edu-school">{entry?.school || degreeLine || "Education"}</p>
                {degreeLine && entry?.school && <p className="meng-muted">{degreeLine}</p>}
                {yearLine && <p className="meng-muted">{String(yearLine)}</p>}
              </div>
            );
          })}
        </section>
      )}

      {(skillGroups.length > 0 || skillsFlat.length > 0) && (
        <section className="meng-section" aria-label="Technical skills">
          <div className="rdoc-sec-head">
            <h2 className="meng-heading">Technical Skills</h2>
            {editing?.onEditSkills && (
              <button type="button" className="rdoc-edit-btn no-print" onClick={editing.onEditSkills}>
                Edit
              </button>
            )}
          </div>
          {skillGroups.length > 0 ? (
            <div className="meng-skills">
              {skillGroups.map(([group, skills]) => (
                <p className="meng-text meng-skillrow" key={group}>
                  <strong>{group}: </strong>
                  <span>{skills.join(", ")}</span>
                </p>
              ))}
            </div>
          ) : (
            <p className="meng-text">{skillsFlat.join(", ")}</p>
          )}
        </section>
      )}

      {experience.length > 0 && (
        <section className="meng-section" aria-label="Experience">
          <h2 className="meng-heading">Experience</h2>
          <ul className="rdoc-list">
            {experience.map((item: TextEntry | string, i: number) => (
              <li key={i}>{asText(typeof item === "string" ? item : item?.text)}</li>
            ))}
          </ul>
        </section>
      )}

      {projects.length > 0 && (
        <section className="meng-section" aria-label="Projects">
          <h2 className="meng-heading">Projects</h2>
          {projects.map((project, pi) => (
            <div className="meng-project" key={`${project.name}-${pi}`}>
              <div className="meng-project-head">
                <p className="meng-project-name">{project.name}</p>
                {(project.links ?? []).length > 0 && (
                  <p className="meng-project-links">
                    {(project.links ?? []).map((url) => (
                      <a key={url} href={url} target="_blank" rel="noreferrer">
                        {hostLabel(url, "Code")}
                      </a>
                    ))}
                  </p>
                )}
              </div>
              {(project.technologies?.length ?? 0) > 0 && (
                <p className="meng-techline">{(project.technologies ?? []).join("  ·  ")}</p>
              )}
              <TemplateBullets
                bullets={project.bullets ?? []}
                projectName={project.name}
                editing={
                  editing
                    ? { onBulletChange: (bi, value) => editing.onBulletChange(pi, bi, value) }
                    : undefined
                }
              />
            </div>
          ))}
        </section>
      )}

      {certifications.length > 0 && (
        <section className="meng-section" aria-label="Certifications">
          <h2 className="meng-heading">Certifications</h2>
          <ul className="rdoc-list">
            {certifications.map((cert, i) => (
              <li key={i}>
                {[cert?.name, cert?.issuing_org].filter(Boolean).join(" — ")}
                {cert?.completion_year ? ` (${cert.completion_year})` : ""}
              </li>
            ))}
          </ul>
        </section>
      )}

      {achievements.length > 0 && (
        <section className="meng-section" aria-label="Achievements">
          <h2 className="meng-heading">Achievements</h2>
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
