import { useState } from "react";
import {
  createRequirement,
  updateRequirement,
  type Requirement,
} from "../../services/employers";
import "./EmployerComponents.css";

type RequirementModalProps = {
  employerId: string;
  requirement?: Requirement | null;
  onClose: () => void;
  onSaved: () => void;
};

export default function RequirementModal({
  employerId,
  requirement,
  onClose,
  onSaved,
}: RequirementModalProps) {
  const isEditing = !!requirement;

  const [title, setTitle] = useState(requirement?.title || "");
  const [roleKey, setRoleKey] = useState(requirement?.role_key || "");
  const [location, setLocation] = useState(requirement?.location || "");
  const [employmentType, setEmploymentType] = useState(requirement?.employment_type || "full_time");
  const [minYears, setMinYears] = useState(requirement?.experience_min_years?.toString() || "");
  const [qualification, setQualification] = useState(requirement?.qualification_text || "");
  const [description, setDescription] = useState(requirement?.description || "");
  const [status, setStatus] = useState<"draft" | "open" | "paused" | "closed">(
    (requirement?.status as "draft" | "open" | "paused" | "closed") || "open"
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) {
      setError("Role / requirement title is required.");
      return;
    }

    setSaving(true);
    setError(null);
    try {
      if (isEditing && requirement) {
        await updateRequirement(requirement.id, {
          title: title.trim(),
          role_key: roleKey.trim() || null,
          location: location.trim() || null,
          employment_type: employmentType || null,
          experience_min_years: minYears ? Number(minYears) : null,
          qualification_text: qualification.trim() || null,
          description: description.trim() || null,
          status,
        });
      } else {
        await createRequirement(employerId, {
          title: title.trim(),
          role_key: roleKey.trim() || null,
          location: location.trim() || null,
          employment_type: employmentType || null,
          experience_min_years: minYears ? Number(minYears) : null,
          qualification_text: qualification.trim() || null,
          description: description.trim() || null,
        });
      }
      onSaved();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="emp-modal-overlay" onClick={onClose} role="dialog" aria-modal="true">
      <div className="emp-modal" onClick={(e) => e.stopPropagation()}>
        <div className="emp-modal__header">
          <h2 style={{ fontSize: "1.2rem", fontWeight: 700, margin: 0 }}>
            {isEditing ? "Edit Hiring Requirement" : "Create Hiring Requirement"}
          </h2>
          <button type="button" className="emp-modal__close" onClick={onClose} aria-label="Close modal">
            ✕
          </button>
        </div>

        {error && (
          <div style={{ background: "#fef2f2", color: "#dc2626", padding: "0.6rem 0.85rem", borderRadius: "8px", marginBottom: "1rem", fontSize: "0.85rem" }}>
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <div className="emp-form-grid">
            <div className="emp-field" style={{ gridColumn: "1 / -1" }}>
              <label className="emp-label">Job Title / Role *</label>
              <input
                className="emp-input"
                type="text"
                placeholder="e.g. Senior Frontend Engineer"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                required
              />
            </div>

            <div className="emp-field">
              <label className="emp-label">Role Key (Taxonomy Key)</label>
              <input
                className="emp-input"
                type="text"
                placeholder="e.g. software_engineer, data_analyst"
                value={roleKey}
                onChange={(e) => setRoleKey(e.target.value)}
              />
            </div>

            <div className="emp-field">
              <label className="emp-label">Location</label>
              <input
                className="emp-input"
                type="text"
                placeholder="e.g. Bangalore, Remote, Hybrid"
                value={location}
                onChange={(e) => setLocation(e.target.value)}
              />
            </div>

            <div className="emp-field">
              <label className="emp-label">Employment Type</label>
              <select
                className="emp-select"
                value={employmentType}
                onChange={(e) => setEmploymentType(e.target.value)}
              >
                <option value="full_time">Full-time</option>
                <option value="part_time">Part-time</option>
                <option value="internship">Internship</option>
                <option value="contract">Contract</option>
                <option value="apprenticeship">Apprenticeship</option>
              </select>
            </div>

            <div className="emp-field">
              <label className="emp-label">Minimum Experience (Years)</label>
              <input
                className="emp-input"
                type="number"
                min="0"
                step="0.5"
                placeholder="e.g. 0 for new grads, 2"
                value={minYears}
                onChange={(e) => setMinYears(e.target.value)}
              />
            </div>

            {isEditing && (
              <div className="emp-field">
                <label className="emp-label">Requirement Status</label>
                <select
                  className="emp-select"
                  value={status}
                  onChange={(e) => setStatus(e.target.value as "draft" | "open" | "paused" | "closed")}
                >
                  <option value="open">Open (Accepting Candidates)</option>
                  <option value="paused">Paused</option>
                  <option value="closed">Closed</option>
                  <option value="draft">Draft</option>
                </select>
              </div>
            )}
          </div>

          <div className="emp-field" style={{ marginBottom: "1rem" }}>
            <label className="emp-label">Education / Qualification Requirements</label>
            <input
              className="emp-input"
              type="text"
              placeholder="e.g. B.Tech / B.E. in Computer Science or equivalent"
              value={qualification}
              onChange={(e) => setQualification(e.target.value)}
            />
          </div>

          <div className="emp-field" style={{ marginBottom: "1.25rem" }}>
            <label className="emp-label">Role Description &amp; Responsibilities</label>
            <textarea
              className="emp-textarea"
              rows={4}
              placeholder="Outline role objectives, day-to-day responsibilities, tech stack…"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>

          <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.75rem" }}>
            <button type="button" className="emp-btn emp-btn--secondary" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="emp-btn emp-btn--primary" disabled={saving}>
              {saving ? "Saving…" : isEditing ? "Save Changes" : "Create Requirement"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
