import type { ResumeContent } from "../../services/resumeBuilder";
import { ClassicATS } from "./templates/ClassicATS";

export type ResumeDocEditing = {
  onSummaryChange: (value: string) => void;
  onBulletChange: (projectIndex: number, bulletIndex: number, value: string) => void;
};

type Props = {
  content: ResumeContent;
  targetRole: string;
  /** Backend template id. Phase 1 renders Classic ATS for all values. */
  template?: string;
  /** When provided, summary/bullets render as inline editable fields. */
  editing?: ResumeDocEditing;
};

/**
 * Presentation-only A4 resume renderer.
 *
 * Consumes the canonical ResumeData (backend output) and displays it.
 * No generation, parsing, filtering, or data-model logic lives here.
 * Future templates plug in beside ClassicATS behind the `template` prop.
 */
export default function ResumeDocument({ content, targetRole, template, editing }: Props) {
  void template;
  return (
    <div className="rdoc-scroll">
      <article className="rdoc-sheet" aria-label={`Resume for ${content.header?.name || "candidate"}`}>
        <ClassicATS content={content} targetRole={targetRole} editing={editing} />
      </article>
    </div>
  );
}
