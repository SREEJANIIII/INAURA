import type { ResumeContent } from "../../../services/resumeBuilder";
import type { ResumeDocEditing } from "../ResumeDocument";
import { EditableSummary } from "../EditableText";
import { TemplateBullets } from "./TemplateBullets";
import { asText, getContactParts } from "./shared";

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
 * Academic CV template — presentation only.
 *
 * LaTeX/CV-inspired: serif type, dense setting, small-caps hierarchy with
 * education first. Renders the same ResumeData as every template — sections
 * appear only when data exists (no research section is invented; the
 * summary is presented as Profile). No generation, filtering, or mutation.
 */
export function AcademicCV({ content, targetRole, editing }: Props) {
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
      <header className="acv-header">
        <h1 className="acv-name">{header.name || "Your Name"}</h1>
        {targetRole && <p className="acv-role">{targetRole}</p>}
        {contact.length > 0 && (
          <p className="acv-contact">
            {contact.map((part, i) => (
              <span key={`${part.label}-${i}`}>
                {i > 0 && (
                  <span className="acv-sep" aria-hidden="true">
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
        <section className="acv-section" aria-label="Profile">
          <h2 className="acv-heading">Profile</h2>
          {editing ? (
            <EditableSummary
              value={content.summary}
              ariaLabel="Resume profile. Activate to edit."
              onCommit={editing.onSummaryChange}
            />
          ) : (
            <p className="acv-text">{content.summary}</p>
          )}
        </section>
      )}

      {education.length > 0 && (
        <section className="acv-section" aria-label="Education">
          <h2 className="acv-heading">Education</h2>
          {education.map((entry, i) => {
            const degreeLine = [entry?.degree, entry?.branch].filter(Boolean).join(", ");
            const yearLine = [entry?.graduation_year, entry?.current_year].filter(Boolean).join(" · ");
            return (
              <div className="acv-edu" key={i}>
                <p className="acv-edu-line">
                  <strong>{entry?.school || degreeLine || "Education"}</strong>
                  {degreeLine && entry?.school && <span> — {degreeLine}</span>}
                  {yearLine && <span className="acv-right">{String(yearLine)}</span>}
                </p>
              </div>
            );
          })}
        </section>
      )}

      {experience.length > 0 && (
        <section className="acv-section" aria-label="Experience">
          <h2 className="acv-heading">Experience</h2>
          <ul className="rdoc-list">
            {experience.map((item: TextEntry | string, i: number) => (
              <li key={i}>{asText(typeof item === "string" ? item : item?.text)}</li>
            ))}
          </ul>
        </section>
      )}

      {projects.length > 0 && (
        <section className="acv-section" aria-label="Projects">
          <h2 className="acv-heading">Projects</h2>
          {projects.map((project, pi) => (
            <div className="acv-project" key={`${project.name}-${pi}`}>
              <p className="acv-project-line">
                <strong>{project.name}</strong>
                {(project.links ?? []).length > 0 && (
                  <span className="acv-links">
                    {(project.links ?? []).map((url, li) => (
                      <span key={url}>
                        {li > 0 && " "}
                        <a href={url} target="_blank" rel="noreferrer">
                          [link]
                        </a>
                      </span>
                    ))}
                  </span>
                )}
              </p>
              {(project.technologies?.length ?? 0) > 0 && (
                <p className="acv-techline">
                  <em>{(project.technologies ?? []).join(", ")}</em>
                </p>
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

      {(skillGroups.length > 0 || skillsFlat.length > 0) && (
        <section className="acv-section" aria-label="Technical skills">
          <div className="rdoc-sec-head">
            <h2 className="acv-heading">Technical Skills</h2>
            {editing?.onEditSkills && (
              <button type="button" className="rdoc-edit-btn no-print" onClick={editing.onEditSkills}>
                Edit
              </button>
            )}
          </div>
          {skillGroups.length > 0 ? (
            skillGroups.map(([group, skills]) => (
              <p className="acv-text acv-skillrow" key={group}>
                <strong>{group}: </strong>
                <span>{skills.join(", ")}</span>
              </p>
            ))
          ) : (
            <p className="acv-text">{skillsFlat.join(", ")}</p>
          )}
        </section>
      )}

      {certifications.length > 0 && (
        <section className="acv-section" aria-label="Certifications">
          <h2 className="acv-heading">Certifications</h2>
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
        <section className="acv-section" aria-label="Achievements">
          <h2 className="acv-heading">Achievements</h2>
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
