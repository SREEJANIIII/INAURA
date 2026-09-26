import { TEMPLATES, type ResumeTemplateId } from "./templates";

type Props = {
  selected: ResumeTemplateId;
  onSelect: (id: ResumeTemplateId) => void;
};

/**
 * Template picker — presentation state only.
 *
 * Selecting a template switches the document renderer client-side. It never
 * regenerates the resume, calls the backend, or touches ResumeData or edits.
 */
export default function TemplatePicker({ selected, onSelect }: Props) {
  return (
    <div className="rtpl-picker no-print" role="radiogroup" aria-label="Resume template">
      <p className="rtpl-label">Resume Template</p>
      <div className="rtpl-options">
        {TEMPLATES.map((t) => {
          const active = t.id === selected;
          return (
            <button
              key={t.id}
              type="button"
              role="radio"
              aria-checked={active}
              className={`rtpl-card${active ? " is-active" : ""}`}
              onClick={() => onSelect(t.id)}
            >
              <span className={`rtpl-thumb rtpl-thumb-${t.id}`} aria-hidden="true">
                <span className="rtpl-bar rtpl-bar-name" />
                <span className="rtpl-bar rtpl-bar-line" />
                <span className="rtpl-bar rtpl-bar-rule" />
                <span className="rtpl-bar rtpl-bar-line rtpl-bar-short" />
                <span className="rtpl-bar rtpl-bar-line" />
              </span>
              <span className="rtpl-name">{t.name}</span>
              <span className="rtpl-desc">{t.description}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
