import { useEffect, useRef } from "react";
import type { RoleSummary } from "../../services/industry";
import { roleId } from "./careerTrackModel";

type Props = {
  roles: RoleSummary[];
  currentId: string | null;
  targetTitle: string | null;
  busyId: string | null;
  onSelect: (role: RoleSummary) => void;
  onClose: () => void;
};

/** A panel of every role INAURA has industry benchmarks for, grouped by field */
export default function CareerSwitcher({ roles, currentId, targetTitle, busyId, onSelect, onClose }: Props) {
  const panelRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);

  useEffect(() => {
    closeRef.current = onClose;
  });

  // Focus the current career once, when the panel opens; Escape closes it
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeRef.current();
    };
    document.addEventListener("keydown", onKey);
    const panel = panelRef.current;
    (panel?.querySelector<HTMLButtonElement>("button.is-current") ?? panel?.querySelector<HTMLButtonElement>(".ct-role"))?.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const groups = Array.from(new Set(roles.map((r) => r.category))).map((category) => ({
    category,
    roles: roles.filter((r) => r.category === category),
  }));

  return (
    <div className="ct-switch" role="dialog" aria-modal="true" aria-labelledby="ct-switch-title" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="ct-switch__panel" ref={panelRef}>
        <div className="ct-switch__head">
          <div>
            <h2 id="ct-switch-title" className="ct-switch__title">Choose your career</h2>
            <p className="ct-muted">This becomes your target role across INAURA, including your next analysis.</p>
          </div>
          <button type="button" className="ct-icon-btn" onClick={onClose} aria-label="Close">
            <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
              <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
            </svg>
          </button>
        </div>
        <div className="ct-switch__groups">
          {groups.map((g) => (
            <section key={g.category} className="ct-switch__group">
              <h3 className="ct-switch__cat">{g.category}</h3>
              <ul>
                {g.roles.map((r) => {
                  const id = roleId(r);
                  const current = id === currentId;
                  const target = targetTitle?.toLowerCase() === r.title.toLowerCase();
                  return (
                    <li key={id}>
                      <button
                        type="button"
                        className={`ct-role${current ? " is-current" : ""}`}
                        onClick={() => onSelect(r)}
                        disabled={!!busyId}
                        aria-current={current ? "true" : undefined}
                      >
                        <span className="ct-role__title">
                          {r.title}
                          {target && <span className="ct-role__tag">Target role</span>}
                        </span>
                        <span className="ct-role__desc">{r.description}</span>
                        {busyId === id && <span className="ct-role__busy">Switching…</span>}
                      </button>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}
        </div>
      </div>
    </div>
  );
}
