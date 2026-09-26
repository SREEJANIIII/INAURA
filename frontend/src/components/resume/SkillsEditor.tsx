type Props = {
  groups: Record<string, string[]>;
  available: Record<string, string[]>;
  onToggle: (name: string, group: string, include: boolean) => void;
  onClose: () => void;
};

/**
 * Resume-skills editor: include/exclude verified skills per recommended
 * group. Edits only the resume representation (local content state, saved
 * via the existing Save action) — the canonical INAURA skill profile is
 * never touched.
 */
export default function SkillsEditor({ groups, available, onToggle, onClose }: Props) {
  const selectedCount = Object.values(groups).reduce((n, v) => n + v.length, 0);
  const renderGroup = (label: string, names: string[], included: boolean) => (
    <div className="rskills-group" key={`${included ? "in" : "out"}-${label}`}>
      <p className="rskills-group-label">{label}</p>
      {names.map((name) => (
        <label className="rskills-row" key={`${label}-${name}`}>
          <input
            type="checkbox"
            checked={included}
            onChange={() => onToggle(name, label, !included)}
          />
          <span>{name}</span>
        </label>
      ))}
    </div>
  );
  return (
    <div
      className="rskills-overlay no-print"
      role="dialog"
      aria-modal="true"
      aria-label="Edit resume skills"
      onClick={onClose}
    >
      <div className="rskills-modal" onClick={(e) => e.stopPropagation()}>
        <div className="rskills-head">
          <div>
            <h3>Resume Skills</h3>
            <p>
              {selectedCount} selected. Unchecked skills stay verified in your INAURA profile —
              they are only hidden from this resume. Press Save to keep changes.
            </p>
          </div>
          <button type="button" className="resume-secondary" onClick={onClose}>
            Done
          </button>
        </div>
        <div className="rskills-cols">
          <div>
            <p className="rskills-col-label">On this resume</p>
            {Object.entries(groups).map(([label, names]) => renderGroup(label, names, true))}
            {Object.keys(groups).length === 0 && <p className="muted">No skills selected.</p>}
          </div>
          <div>
            <p className="rskills-col-label">Available (verified, hidden)</p>
            {Object.entries(available).map(([label, names]) => renderGroup(label, names, false))}
            {Object.keys(available).length === 0 && <p className="muted">Everything is on the resume.</p>}
          </div>
        </div>
      </div>
    </div>
  );
}
