import type { ResumeContent } from "../../services/resumeBuilder";
import { ClassicATS } from "./templates/ClassicATS";
import { ModernEngineering } from "./templates/ModernEngineering";
import { AcademicCV } from "./templates/AcademicCV";
import { isResumeTemplateId, type ResumeTemplateId } from "./templates";

export type ResumeDocEditing = {
  onSummaryChange: (value: string) => void;
  onBulletChange: (projectIndex: number, bulletIndex: number, value: string) => void;
  /** Opens the resume-skills editor. Presence renders Edit affordances. */
  onEditSkills?: () => void;
};

type Props = {
  content: ResumeContent;
  targetRole: string;
  /** Visual template id (see templates.ts registry). Defaults to Classic ATS. */
  template?: ResumeTemplateId | string;
  /** When provided, summary/bullets render as inline editable fields. */
  editing?: ResumeDocEditing;
};

/**
 * Presentation-only A4 resume renderer.
 *
 * Consumes the canonical ResumeData (backend output) and displays it through
 * the selected template. No generation, parsing, filtering, or data-model
 * logic lives here; ResumeData and edit state are shared across templates.
 */
export default function ResumeDocument({ content, targetRole, template, editing }: Props) {
  const id: ResumeTemplateId = isResumeTemplateId(template) ? template : "classic-ats";
  return (
    <div className="rdoc-scroll">
      <article
        className={`rdoc-sheet tpl-${id}`}
        aria-label={`Resume for ${content.header?.name || "candidate"}`}
      >
        {id === "modern-engineering" ? (
          <ModernEngineering content={content} targetRole={targetRole} editing={editing} />
        ) : id === "academic-cv" ? (
          <AcademicCV content={content} targetRole={targetRole} editing={editing} />
        ) : (
          <ClassicATS content={content} targetRole={targetRole} editing={editing} />
        )}
      </article>
    </div>
  );
}
