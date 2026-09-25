import type { ReactNode } from "react";

type EvidenceSectionProps = {
  /** Also the anchor, so a link like /analysis#projects opens this one */
  id: string;
  title: string;
  /** What this source proves about you — the reason to bother adding it */
  proves: string;
  /** What this section is for, shown once it's open */
  desc?: string;
  /** What's in it already, read at a glance while it's shut */
  status: string;
  done: boolean;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
};

/**
 * One source of proof, on the evidence page.
 *
 * Shut, it says what it would prove about you and what you've put in so far; open, it shows
 * the form. The rule down its left edge is the state, so running an eye down the column tells
 * you the shape of your evidence without reading a word.
 */
export default function EvidenceSection({
  id,
  title,
  proves,
  desc,
  status,
  done,
  open,
  onToggle,
  children,
}: EvidenceSectionProps) {
  const panelId = `${id}-panel`;
  return (
    <section className={`ev${open ? " is-open" : ""}${done ? " is-in" : ""}`} id={id}>
      <h2 className="ev__heading">
        <button type="button" className="ev__toggle" aria-expanded={open} aria-controls={panelId} onClick={onToggle}>
          <span className="ev__text">
            <span className="ev__title">{title}</span>
            <span className="ev__status">{done ? status : proves}</span>
          </span>
          {/* An invitation on the empty ones; a filled row already says what's in it */}
          {!done && <span className="ev__add">Add</span>}
          <svg className="ev__chevron" width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
            <path
              d="M4 6.25 8 10.25l4-4"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </button>
      </h2>
      {/* The wrapper is what grows; the panel inside it is clipped while it does */}
      {open && (
        <div className="ev__grow">
          <div className="ev__panel" id={panelId} role="region" aria-label={title}>
            {desc && <p className="ev__desc">{desc}</p>}
            {children}
          </div>
        </div>
      )}
    </section>
  );
}
