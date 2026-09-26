import { useState } from "react";
import { updateEmployer, type Employer } from "../../services/employers";
import { useEmployer } from "../../context/EmployerContext";
import "./EmployerComponents.css";

type CompanyModalProps = {
  employer?: Employer | null;
  onClose: () => void;
  onSaved: () => void;
};

export default function CompanyModal({ employer, onClose, onSaved }: CompanyModalProps) {
  const isEditing = !!employer;
  const { createEmployerOrg, refreshEmployers } = useEmployer();

  const [name, setName] = useState(employer?.name || "");
  const [industry, setIndustry] = useState(employer?.industry || "");
  const [location, setLocation] = useState(employer?.location || "");
  const [website, setWebsite] = useState(employer?.website || "");
  const [contactEmail, setContactEmail] = useState(employer?.contact_email || "");
  const [description, setDescription] = useState(employer?.description || "");
  const [status, setStatus] = useState<"active" | "suspended" | "archived">(
    (employer?.status as "active" | "suspended" | "archived") || "active"
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) {
      setError("Company name is required.");
      return;
    }

    setSaving(true);
    setError(null);
    try {
      if (isEditing && employer) {
        await updateEmployer(employer.id, {
          name: name.trim(),
          industry: industry.trim() || null,
          location: location.trim() || null,
          website: website.trim() || null,
          contact_email: contactEmail.trim() || null,
          description: description.trim() || null,
          status,
        });
        await refreshEmployers();
      } else {
        await createEmployerOrg({
          name: name.trim(),
          industry: industry.trim() || null,
          location: location.trim() || null,
          website: website.trim() || null,
          contact_email: contactEmail.trim() || null,
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
            {isEditing ? "Edit Company Profile" : "Register New Company"}
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
              <label className="emp-label">Company Name *</label>
              <input
                className="emp-input"
                type="text"
                placeholder="e.g. Acme Technologies Inc."
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
              />
            </div>

            <div className="emp-field">
              <label className="emp-label">Industry</label>
              <input
                className="emp-input"
                type="text"
                placeholder="e.g. Software & Cloud, Fintech"
                value={industry}
                onChange={(e) => setIndustry(e.target.value)}
              />
            </div>

            <div className="emp-field">
              <label className="emp-label">Location / Headquarters</label>
              <input
                className="emp-input"
                type="text"
                placeholder="e.g. Bengaluru, India"
                value={location}
                onChange={(e) => setLocation(e.target.value)}
              />
            </div>

            <div className="emp-field">
              <label className="emp-label">Website</label>
              <input
                className="emp-input"
                type="url"
                placeholder="https://example.com"
                value={website}
                onChange={(e) => setWebsite(e.target.value)}
              />
            </div>

            <div className="emp-field">
              <label className="emp-label">Hiring Contact Email</label>
              <input
                className="emp-input"
                type="email"
                placeholder="careers@company.com"
                value={contactEmail}
                onChange={(e) => setContactEmail(e.target.value)}
              />
            </div>

            {isEditing && (
              <div className="emp-field">
                <label className="emp-label">Company Status</label>
                <select
                  className="emp-select"
                  value={status}
                  onChange={(e) => setStatus(e.target.value as "active" | "suspended" | "archived")}
                >
                  <option value="active">Active</option>
                  <option value="suspended">Suspended</option>
                  <option value="archived">Archived</option>
                </select>
              </div>
            )}
          </div>

          <div className="emp-field" style={{ marginBottom: "1.25rem" }}>
            <label className="emp-label">Company Description</label>
            <textarea
              className="emp-textarea"
              rows={3}
              placeholder="What does your company build? What is your mission and culture?"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>

          <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.75rem" }}>
            <button type="button" className="emp-btn emp-btn--secondary" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="emp-btn emp-btn--primary" disabled={saving}>
              {saving ? "Saving…" : isEditing ? "Save Profile" : "Register Company"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
