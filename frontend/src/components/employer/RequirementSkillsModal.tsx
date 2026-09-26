import { useState, useEffect } from "react";
import {
  listRequirementSkills,
  setRequirementSkills,
  listCanonicalSkills,
  type Requirement,
  type RequirementSkill,
  type CanonicalSkill,
} from "../../services/employers";
import "./EmployerComponents.css";

type RequirementSkillsModalProps = {
  requirement: Requirement;
  onClose: () => void;
  onSaved: () => void;
};

export default function RequirementSkillsModal({
  requirement,
  onClose,
  onSaved,
}: RequirementSkillsModalProps) {
  const [skills, setSkills] = useState<RequirementSkill[]>([]);
  const [catalog, setCatalog] = useState<CanonicalSkill[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // New skill addition state
  const [selectedSkillId, setSelectedSkillId] = useState("");
  const [importance, setImportance] = useState<"required" | "preferred">("required");
  const [requiredLevel, setRequiredLevel] = useState("0.75");
  const [note, setNote] = useState("");

  useEffect(() => {
    let active = true;
    setLoading(true);
    Promise.all([listRequirementSkills(requirement.id), listCanonicalSkills()])
      .then(([reqSkills, cat]) => {
        if (!active) return;
        setSkills(reqSkills);
        setCatalog(cat);
        if (cat.length > 0) setSelectedSkillId(cat[0].id);
      })
      .catch((err) => {
        if (!active) return;
        setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [requirement.id]);

  const handleAddSkill = () => {
    if (!selectedSkillId) return;
    if (skills.some((s) => s.skill_id === selectedSkillId)) {
      setError("This skill is already attached to this requirement.");
      return;
    }

    const catItem = catalog.find((c) => c.id === selectedSkillId);
    const newSkill: RequirementSkill = {
      id: `temp-${Date.now()}`,
      hiring_requirement_id: requirement.id,
      skill_id: selectedSkillId,
      importance,
      required_level: Number(requiredLevel),
      note: note.trim() || null,
      created_at: new Date().toISOString(),
      skill_name: catItem?.display_name || selectedSkillId,
      skill_category: catItem?.category || null,
    };

    setSkills([...skills, newSkill]);
    setNote("");
    setError(null);
  };

  const handleRemoveSkill = (skillId: string) => {
    setSkills(skills.filter((s) => s.skill_id !== skillId));
  };

  const handleSaveAll = async () => {
    setSaving(true);
    setError(null);
    try {
      await setRequirementSkills(
        requirement.id,
        skills.map((s) => ({
          skill_id: s.skill_id,
          importance: s.importance,
          required_level: s.required_level,
          note: s.note,
        }))
      );
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
      <div className="emp-modal" style={{ maxWidth: 740 }} onClick={(e) => e.stopPropagation()}>
        <div className="emp-modal__header">
          <div>
            <h2 style={{ fontSize: "1.2rem", fontWeight: 700, margin: 0 }}>
              Manage Skills: {requirement.title}
            </h2>
            <p style={{ margin: "0.25rem 0 0", fontSize: "0.85rem", color: "var(--muted)" }}>
              Define expected competencies and target proficiency for candidate evaluation.
            </p>
          </div>
          <button type="button" className="emp-modal__close" onClick={onClose} aria-label="Close modal">
            ✕
          </button>
        </div>

        {error && (
          <div style={{ background: "#fef2f2", color: "#dc2626", padding: "0.6rem 0.85rem", borderRadius: "8px", marginBottom: "1rem", fontSize: "0.85rem" }}>
            {error}
          </div>
        )}

        {loading ? (
          <div style={{ padding: "2rem", textAlign: "center", color: "var(--muted)" }}>
            Loading skills catalog…
          </div>
        ) : (
          <div>
            {/* Add Skill Form */}
            <div style={{ background: "var(--paper-2, #f8fafc)", padding: "1rem", borderRadius: "10px", border: "1px solid var(--line)", marginBottom: "1.25rem" }}>
              <div style={{ fontSize: "0.85rem", fontWeight: 700, marginBottom: "0.75rem", color: "var(--ink)" }}>
                + Add Skill from Canonical Catalog
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: "0.75rem", marginBottom: "0.75rem" }}>
                <div className="emp-field">
                  <label className="emp-label">Skill</label>
                  <select
                    className="emp-select"
                    value={selectedSkillId}
                    onChange={(e) => setSelectedSkillId(e.target.value)}
                  >
                    {catalog.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.display_name} ({c.category || "General"})
                      </option>
                    ))}
                  </select>
                </div>

                <div className="emp-field">
                  <label className="emp-label">Importance</label>
                  <select
                    className="emp-select"
                    value={importance}
                    onChange={(e) => setImportance(e.target.value as "required" | "preferred")}
                  >
                    <option value="required">Required (Core)</option>
                    <option value="preferred">Preferred (Nice-to-have)</option>
                  </select>
                </div>

                <div className="emp-field">
                  <label className="emp-label">Target Level</label>
                  <select
                    className="emp-select"
                    value={requiredLevel}
                    onChange={(e) => setRequiredLevel(e.target.value)}
                  >
                    <option value="0.5">Foundational (50%)</option>
                    <option value="0.75">Proficient (75%)</option>
                    <option value="0.9">Advanced / Lead (90%)</option>
                  </select>
                </div>
              </div>

              <div style={{ display: "flex", gap: "0.75rem", alignItems: "center" }}>
                <input
                  className="emp-input"
                  style={{ flex: 1 }}
                  placeholder="Optional expectations or framework note (e.g. React 19, FastAPI, PostgreSQL)"
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                />
                <button
                  type="button"
                  className="emp-btn emp-btn--secondary"
                  onClick={handleAddSkill}
                >
                  Add Skill
                </button>
              </div>
            </div>

            {/* Current Skills List */}
            <div style={{ marginBottom: "1.5rem" }}>
              <div style={{ fontSize: "0.85rem", fontWeight: 700, marginBottom: "0.5rem" }}>
                Configured Skills ({skills.length})
              </div>
              {skills.length === 0 ? (
                <p style={{ fontSize: "0.85rem", color: "var(--muted)", fontStyle: "italic" }}>
                  No skills defined for this requirement yet.
                </p>
              ) : (
                <div className="emp-table-wrap">
                  <table className="emp-table">
                    <thead>
                      <tr>
                        <th>Skill Name</th>
                        <th>Importance</th>
                        <th>Target Level</th>
                        <th>Notes</th>
                        <th>Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {skills.map((s) => (
                        <tr key={s.skill_id}>
                          <td>
                            <strong>{s.skill_name || s.skill_id}</strong>
                          </td>
                          <td>
                            <span
                              className={`emp-badge ${
                                s.importance === "required" ? "emp-badge--rejected" : "emp-badge--applied"
                              }`}
                            >
                              {s.importance}
                            </span>
                          </td>
                          <td>
                            {s.required_level != null ? `${Math.round(s.required_level * 100)}%` : "Not set"}
                          </td>
                          <td style={{ fontSize: "0.8rem", color: "var(--muted)" }}>
                            {s.note || "—"}
                          </td>
                          <td>
                            <button
                              type="button"
                              className="emp-btn emp-btn--danger-ghost emp-btn--sm"
                              onClick={() => handleRemoveSkill(s.skill_id)}
                            >
                              Remove
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.75rem" }}>
              <button type="button" className="emp-btn emp-btn--secondary" onClick={onClose}>
                Cancel
              </button>
              <button
                type="button"
                className="emp-btn emp-btn--primary"
                disabled={saving}
                onClick={handleSaveAll}
              >
                {saving ? "Saving Skills…" : "Save Skill Configuration"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
