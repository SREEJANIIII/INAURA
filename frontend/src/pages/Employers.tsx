import { useEffect, useState } from "react";
import "./Person2.css";
import {
  createEmployer,
  updateEmployer,
  deleteEmployer,
  listEmployers,
  listMembers,
  addMember,
  removeMember,
  createRequirement,
  updateRequirement,
  deleteRequirement,
  listRequirements,
  listRequirementSkills,
  setRequirementSkills,
  listCanonicalSkills,
  type Employer,
  type Member,
  type Requirement,
  type RequirementSkill,
  type CanonicalSkill,
} from "../services/employers";

const messageOf = (e: unknown) => (e instanceof Error ? e.message : String(e));

export default function Employers() {
  const [employers, setEmployers] = useState<Employer[]>([]);
  const [selected, setSelected] = useState<Employer | null>(null);
  const [members, setMembers] = useState<Member[]>([]);
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [selectedReq, setSelectedReq] = useState<Requirement | null>(null);
  const [reqSkills, setReqSkills] = useState<RequirementSkill[]>([]);
  const [catalog, setCatalog] = useState<CanonicalSkill[]>([]);

  // Employer creation form
  const [empName, setEmpName] = useState("");
  const [empIndustry, setEmpIndustry] = useState("");
  const [empLocation, setEmpLocation] = useState("");
  const [empWebsite, setEmpWebsite] = useState("");
  const [empContactEmail, setEmpContactEmail] = useState("");

  // Employer editing form
  const [editingEmp, setEditingEmp] = useState(false);
  const [editEmpName, setEditEmpName] = useState("");
  const [editEmpIndustry, setEditEmpIndustry] = useState("");
  const [editEmpLocation, setEditEmpLocation] = useState("");
  const [editEmpWebsite, setEditEmpWebsite] = useState("");
  const [editEmpContactEmail, setEditEmpContactEmail] = useState("");
  const [editEmpStatus, setEditEmpStatus] = useState<"active" | "suspended" | "archived">("active");

  // Member management form
  const [newMemberUserId, setNewMemberUserId] = useState("");
  const [newMemberRole, setNewMemberRole] = useState<"member" | "owner">("member");

  // Requirement creation form
  const [reqTitle, setReqTitle] = useState("");
  const [reqRoleKey, setReqRoleKey] = useState("");
  const [reqLocation, setReqLocation] = useState("");
  const [reqEmploymentType, setReqEmploymentType] = useState<string>("");
  const [reqMinYears, setReqMinYears] = useState<string>("");
  const [reqDescription, setReqDescription] = useState("");
  const [reqQualification, setReqQualification] = useState("");

  // Requirement editing form
  const [editingReq, setEditingReq] = useState(false);
  const [editReqTitle, setEditReqTitle] = useState("");
  const [editReqRoleKey, setEditReqRoleKey] = useState("");
  const [editReqLocation, setEditReqLocation] = useState("");
  const [editReqEmploymentType, setEditReqEmploymentType] = useState<string>("");
  const [editReqMinYears, setEditReqMinYears] = useState<string>("");
  const [editReqStatus, setEditReqStatus] = useState<"draft" | "open" | "paused" | "closed">("open");
  const [editReqDescription, setEditReqDescription] = useState("");
  const [editReqQualification, setEditReqQualification] = useState("");

  // Skill management form
  const [selectedSkillId, setSelectedSkillId] = useState("");
  const [skillImportance, setSkillImportance] = useState<"required" | "preferred">("required");
  const [skillLevel, setSkillLevel] = useState("0.7");
  const [skillNote, setSkillNote] = useState("");

  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // Initial load
  const refreshEmployers = () =>
    listEmployers()
      .then((rows) => {
        setEmployers(rows);
        if (selected) {
          const still = rows.find((r) => r.id === selected.id) ?? null;
          setSelected(still);
        }
      })
      .catch((e) => setError(messageOf(e)));

  useEffect(() => {
    void refreshEmployers();
    listCanonicalSkills()
      .then(setCatalog)
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // When selected employer changes: load members & requirements
  useEffect(() => {
    if (!selected) {
      setMembers([]);
      setRequirements([]);
      setSelectedReq(null);
      setEditingEmp(false);
      return;
    }
    setError(null);
    setEditingEmp(false);
    setSelectedReq(null);

    listMembers(selected.id)
      .then(setMembers)
      .catch((e) => setError(messageOf(e)));

    listRequirements(selected.id)
      .then(setRequirements)
      .catch((e) => setError(messageOf(e)));
  }, [selected]);

  // When selected requirement changes: load requirement skills
  useEffect(() => {
    if (!selectedReq) {
      setReqSkills([]);
      setEditingReq(false);
      return;
    }
    setError(null);
    setEditingReq(false);
    listRequirementSkills(selectedReq.id)
      .then(setReqSkills)
      .catch((e) => setError(messageOf(e)));
  }, [selectedReq]);

  // Employer Actions
  const handleAddEmployer = async () => {
    if (!empName.trim()) {
      setError("Company name is required");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const created = await createEmployer({
        name: empName.trim(),
        industry: empIndustry.trim() || null,
        location: empLocation.trim() || null,
        website: empWebsite.trim() || null,
        contact_email: empContactEmail.trim() || null,
      });
      setEmpName("");
      setEmpIndustry("");
      setEmpLocation("");
      setEmpWebsite("");
      setEmpContactEmail("");
      const rows = await listEmployers();
      setEmployers(rows);
      setSelected(rows.find((r) => r.id === created.id) ?? created);
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setSaving(false);
    }
  };

  const startEditEmployer = () => {
    if (!selected) return;
    setEditEmpName(selected.name);
    setEditEmpIndustry(selected.industry || "");
    setEditEmpLocation(selected.location || "");
    setEditEmpWebsite(selected.website || "");
    setEditEmpContactEmail(selected.contact_email || "");
    setEditEmpStatus((selected.status as "active" | "suspended" | "archived") || "active");
    setEditingEmp(true);
  };

  const handleUpdateEmployer = async () => {
    if (!selected || !editEmpName.trim()) {
      setError("Company name is required");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const updated = await updateEmployer(selected.id, {
        name: editEmpName.trim(),
        industry: editEmpIndustry.trim() || null,
        location: editEmpLocation.trim() || null,
        website: editEmpWebsite.trim() || null,
        contact_email: editEmpContactEmail.trim() || null,
        status: editEmpStatus,
      });
      const rows = await listEmployers();
      setEmployers(rows);
      setSelected(updated);
      setEditingEmp(false);
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteEmployer = async () => {
    if (!selected) return;
    if (!window.confirm(`Delete ${selected.name}? This will remove all requirements and memberships.`)) return;
    setSaving(true);
    setError(null);
    try {
      await deleteEmployer(selected.id);
      setSelected(null);
      await refreshEmployers();
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setSaving(false);
    }
  };

  // Member Actions
  const handleAddMember = async () => {
    if (!selected || !newMemberUserId.trim()) {
      setError("User ID is required to add a team member");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await addMember(selected.id, {
        user_id: newMemberUserId.trim(),
        role: newMemberRole,
      });
      setNewMemberUserId("");
      setMembers(await listMembers(selected.id));
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setSaving(false);
    }
  };

  const handleRemoveMember = async (targetUserId: string) => {
    if (!selected) return;
    setSaving(true);
    setError(null);
    try {
      await removeMember(selected.id, targetUserId);
      setMembers(await listMembers(selected.id));
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setSaving(false);
    }
  };

  // Requirement Actions
  const handleAddRequirement = async () => {
    if (!selected || !reqTitle.trim()) {
      setError("Pick an employer and enter a role title");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const created = await createRequirement(selected.id, {
        title: reqTitle.trim(),
        role_key: reqRoleKey.trim() || null,
        location: reqLocation.trim() || null,
        employment_type: reqEmploymentType || null,
        experience_min_years: reqMinYears ? parseFloat(reqMinYears) : null,
        description: reqDescription.trim() || null,
        qualification_text: reqQualification.trim() || null,
      });
      setReqTitle("");
      setReqRoleKey("");
      setReqLocation("");
      setReqEmploymentType("");
      setReqMinYears("");
      setReqDescription("");
      setReqQualification("");
      const updatedReqs = await listRequirements(selected.id);
      setRequirements(updatedReqs);
      setSelectedReq(updatedReqs.find((r) => r.id === created.id) ?? created);
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setSaving(false);
    }
  };

  const startEditRequirement = () => {
    if (!selectedReq) return;
    setEditReqTitle(selectedReq.title);
    setEditReqRoleKey(selectedReq.role_key || "");
    setEditReqLocation(selectedReq.location || "");
    setEditReqEmploymentType(selectedReq.employment_type || "");
    setEditReqMinYears(selectedReq.experience_min_years != null ? String(selectedReq.experience_min_years) : "");
    setEditReqStatus((selectedReq.status as "draft" | "open" | "paused" | "closed") || "open");
    setEditReqDescription(selectedReq.description || "");
    setEditReqQualification(selectedReq.qualification_text || "");
    setEditingReq(true);
  };

  const handleUpdateRequirement = async () => {
    if (!selected || !selectedReq || !editReqTitle.trim()) {
      setError("Role title is required");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const updated = await updateRequirement(selectedReq.id, {
        title: editReqTitle.trim(),
        role_key: editReqRoleKey.trim() || null,
        location: editReqLocation.trim() || null,
        employment_type: editReqEmploymentType || null,
        experience_min_years: editReqMinYears ? parseFloat(editReqMinYears) : null,
        status: editReqStatus,
        description: editReqDescription.trim() || null,
        qualification_text: editReqQualification.trim() || null,
      });
      const updatedReqs = await listRequirements(selected.id);
      setRequirements(updatedReqs);
      setSelectedReq(updated);
      setEditingReq(false);
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteRequirement = async () => {
    if (!selected || !selectedReq) return;
    if (!window.confirm(`Delete ${selectedReq.title}?`)) return;
    setSaving(true);
    setError(null);
    try {
      await deleteRequirement(selectedReq.id);
      setSelectedReq(null);
      setRequirements(await listRequirements(selected.id));
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setSaving(false);
    }
  };

  // Skill Actions
  const handleAddSkill = async () => {
    if (!selectedReq || !selectedSkillId) {
      setError("Choose a skill from the catalog");
      return;
    }
    const levelNum = parseFloat(skillLevel);
    if (isNaN(levelNum) || levelNum < 0 || levelNum > 1) {
      setError("Proficiency level must be between 0.0 and 1.0");
      return;
    }
    // Check if already in skills list
    const existingIndex = reqSkills.findIndex((s) => s.skill_id === selectedSkillId);
    let nextSkills = [...reqSkills];
    if (existingIndex >= 0) {
      nextSkills[existingIndex] = {
        ...nextSkills[existingIndex],
        importance: skillImportance,
        required_level: levelNum,
        note: skillNote.trim() || null,
      };
    } else {
      nextSkills.push({
        id: "",
        hiring_requirement_id: selectedReq.id,
        skill_id: selectedSkillId,
        importance: skillImportance,
        required_level: levelNum,
        note: skillNote.trim() || null,
        created_at: "",
      });
    }

    setSaving(true);
    setError(null);
    try {
      const payload = nextSkills.map((s) => ({
        skill_id: s.skill_id,
        importance: s.importance,
        required_level: s.required_level,
        note: s.note,
      }));
      const updated = await setRequirementSkills(selectedReq.id, payload);
      setReqSkills(updated);
      setSelectedSkillId("");
      setSkillNote("");
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setSaving(false);
    }
  };

  const handleRemoveSkill = async (skillId: string) => {
    if (!selectedReq) return;
    const remaining = reqSkills.filter((s) => s.skill_id !== skillId);
    setSaving(true);
    setError(null);
    try {
      const payload = remaining.map((s) => ({
        skill_id: s.skill_id,
        importance: s.importance,
        required_level: s.required_level,
        note: s.note,
      }));
      const updated = await setRequirementSkills(selectedReq.id, payload);
      setReqSkills(updated);
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <main className="p2">
      <header className="p2__head">
        <h1>Employer Foundation</h1>
        <p>Manage company profiles, authorized team members, hiring requirements, and required skill proficiencies.</p>
      </header>

      {error && <p className="p2__error">{error}</p>}

      <div className="p2__cols">
        {/* Column 1: Employers & Members */}
        <section>
          <h2>Your Employers</h2>
          <ul className="p2__list">
            {employers.map((e) => (
              <li key={e.id}>
                <button
                  type="button"
                  className={`p2__pick${selected?.id === e.id ? " is-active" : ""}`}
                  onClick={() => setSelected(e)}
                >
                  <strong>{e.name}</strong>
                  {e.industry && <span> · {e.industry}</span>}
                  {e.location && <span> · {e.location}</span>}
                  <span className={`p2__badge p2__badge--${e.status}`} style={{ marginLeft: "0.5rem" }}>
                    {e.status}
                  </span>
                </button>
              </li>
            ))}
            {employers.length === 0 && <li>No employers found — register your company below.</li>}
          </ul>

          {/* Selected Employer Details */}
          {selected && (
            <div className="p2__detail">
              <div className="p2__detail-header">
                <h3>{selected.name}</h3>
                <div className="p2__row" style={{ marginTop: 0 }}>
                  <button type="button" className="p2__btn p2__btn--ghost" onClick={startEditEmployer}>
                    Edit Profile
                  </button>
                  <button type="button" className="p2__btn p2__btn--danger-ghost" onClick={handleDeleteEmployer}>
                    Delete
                  </button>
                </div>
              </div>

              {!editingEmp ? (
                <div className="p2__meta">
                  {selected.industry && <span><strong>Industry:</strong> {selected.industry}</span>}
                  {selected.location && <span><strong>Location:</strong> {selected.location}</span>}
                  {selected.website && (
                    <span>
                      <strong>Website:</strong>{" "}
                      <a href={selected.website} target="_blank" rel="noreferrer">
                        {selected.website}
                      </a>
                    </span>
                  )}
                  {selected.contact_email && (
                    <span><strong>Contact Email (Owner only):</strong> {selected.contact_email}</span>
                  )}
                  <span><strong>Status:</strong> {selected.status}</span>
                </div>
              ) : (
                <div className="p2__form">
                  <input
                    aria-label="Edit name"
                    placeholder="Company name"
                    value={editEmpName}
                    onChange={(e) => setEditEmpName(e.target.value)}
                  />
                  <input
                    aria-label="Edit industry"
                    placeholder="Industry"
                    value={editEmpIndustry}
                    onChange={(e) => setEditEmpIndustry(e.target.value)}
                  />
                  <input
                    aria-label="Edit location"
                    placeholder="Location"
                    value={editEmpLocation}
                    onChange={(e) => setEditEmpLocation(e.target.value)}
                  />
                  <input
                    aria-label="Edit website"
                    placeholder="Website URL"
                    value={editEmpWebsite}
                    onChange={(e) => setEditEmpWebsite(e.target.value)}
                  />
                  <input
                    aria-label="Edit contact email"
                    placeholder="Contact email (owner only)"
                    value={editEmpContactEmail}
                    onChange={(e) => setEditEmpContactEmail(e.target.value)}
                  />
                  <select
                    className="p2__select"
                    value={editEmpStatus}
                    onChange={(e) => setEditEmpStatus(e.target.value as "active" | "suspended" | "archived")}
                  >
                    <option value="active">Active</option>
                    <option value="suspended">Suspended</option>
                    <option value="archived">Archived</option>
                  </select>
                  <div className="p2__row">
                    <button type="button" className="p2__btn" onClick={handleUpdateEmployer} disabled={saving}>
                      Save Changes
                    </button>
                    <button type="button" className="p2__btn p2__btn--ghost" onClick={() => setEditingEmp(false)}>
                      Cancel
                    </button>
                  </div>
                </div>
              )}

              {/* Members Section */}
              <div style={{ marginTop: "1rem" }}>
                <h4>Team Members ({members.length})</h4>
                <ul className="p2__list">
                  {members.map((m) => (
                    <li key={m.id} className="p2__skill-row">
                      <div>
                        <code>{m.user_id}</code>
                        <span className={`p2__badge p2__badge--${m.role}`} style={{ marginLeft: "0.5rem" }}>
                          {m.role}
                        </span>
                      </div>
                      <button
                        type="button"
                        className="p2__btn p2__btn--danger-ghost"
                        style={{ padding: "0.2rem 0.5rem", fontSize: "0.75rem" }}
                        onClick={() => handleRemoveMember(m.user_id)}
                        disabled={saving}
                      >
                        Remove
                      </button>
                    </li>
                  ))}
                  {members.length === 0 && <li className="p2__hint">No team members loaded.</li>}
                </ul>

                <div className="p2__form" style={{ marginTop: "0.5rem" }}>
                  <div style={{ display: "flex", gap: "0.5rem" }}>
                    <input
                      style={{ flex: 1 }}
                      placeholder="Add member User ID (UUID)"
                      value={newMemberUserId}
                      onChange={(e) => setNewMemberUserId(e.target.value)}
                    />
                    <select
                      className="p2__select"
                      value={newMemberRole}
                      onChange={(e) => setNewMemberRole(e.target.value as "member" | "owner")}
                    >
                      <option value="member">Member</option>
                      <option value="owner">Owner</option>
                    </select>
                    <button type="button" className="p2__btn" onClick={handleAddMember} disabled={saving}>
                      Add
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* New Employer Form */}
          <div className="p2__form" style={{ marginTop: "1.5rem" }}>
            <h3>Register New Employer</h3>
            <input
              aria-label="Company name"
              placeholder="Company name *"
              value={empName}
              onChange={(e) => setEmpName(e.target.value)}
            />
            <input
              aria-label="Industry"
              placeholder="Industry (e.g. Technology, Finance)"
              value={empIndustry}
              onChange={(e) => setEmpIndustry(e.target.value)}
            />
            <input
              aria-label="Location"
              placeholder="Headquarters location (e.g. Bengaluru, IN)"
              value={empLocation}
              onChange={(e) => setEmpLocation(e.target.value)}
            />
            <input
              aria-label="Website"
              placeholder="Website URL (optional)"
              value={empWebsite}
              onChange={(e) => setEmpWebsite(e.target.value)}
            />
            <input
              aria-label="Contact email"
              placeholder="Contact email (owner only)"
              value={empContactEmail}
              onChange={(e) => setEmpContactEmail(e.target.value)}
            />
            <button type="button" className="p2__btn" onClick={handleAddEmployer} disabled={saving}>
              {saving ? "Saving…" : "Create Employer"}
            </button>
          </div>
        </section>

        {/* Column 2: Hiring Requirements & Required Skills */}
        <section>
          <h2>Hiring Requirements</h2>
          {!selected ? (
            <p className="p2__hint">Select an employer on the left to inspect and manage open roles.</p>
          ) : (
            <>
              <ul className="p2__list">
                {requirements.map((r) => (
                  <li key={r.id}>
                    <button
                      type="button"
                      className={`p2__pick${selectedReq?.id === r.id ? " is-active" : ""}`}
                      onClick={() => setSelectedReq(r)}
                    >
                      <strong>{r.title}</strong>
                      {r.role_key && <span> · {r.role_key}</span>}
                      {r.location && <span> · {r.location}</span>}
                      <span className={`p2__badge p2__badge--${r.status}`} style={{ marginLeft: "0.5rem" }}>
                        {r.status}
                      </span>
                    </button>
                  </li>
                ))}
                {requirements.length === 0 && <li className="p2__hint">No hiring requirements yet for {selected.name}.</li>}
              </ul>

              {/* Selected Requirement Detail & Skills Manager */}
              {selectedReq && (
                <div className="p2__detail">
                  <div className="p2__detail-header">
                    <h3>{selectedReq.title}</h3>
                    <div className="p2__row" style={{ marginTop: 0 }}>
                      <button type="button" className="p2__btn p2__btn--ghost" onClick={startEditRequirement}>
                        Edit Role
                      </button>
                      <button type="button" className="p2__btn p2__btn--danger-ghost" onClick={handleDeleteRequirement}>
                        Delete
                      </button>
                    </div>
                  </div>

                  {!editingReq ? (
                    <div className="p2__meta">
                      {selectedReq.role_key && <span><strong>Role Key:</strong> {selectedReq.role_key}</span>}
                      {selectedReq.location && <span><strong>Location:</strong> {selectedReq.location}</span>}
                      {selectedReq.employment_type && (
                        <span><strong>Type:</strong> {selectedReq.employment_type.replace("_", " ")}</span>
                      )}
                      {selectedReq.experience_min_years != null && (
                        <span><strong>Min Experience:</strong> {selectedReq.experience_min_years} yrs</span>
                      )}
                      <span><strong>Status:</strong> {selectedReq.status}</span>
                      {selectedReq.description && (
                        <p style={{ width: "100%", margin: "0.4rem 0" }}>{selectedReq.description}</p>
                      )}
                      {selectedReq.qualification_text && (
                        <p style={{ width: "100%", margin: "0.2rem 0", fontStyle: "italic", opacity: 0.85 }}>
                          <strong>Qualifications:</strong> {selectedReq.qualification_text}
                        </p>
                      )}
                    </div>
                  ) : (
                    <div className="p2__form">
                      <input
                        placeholder="Role title *"
                        value={editReqTitle}
                        onChange={(e) => setEditReqTitle(e.target.value)}
                      />
                      <input
                        placeholder="Industry role key (e.g. software_engineer)"
                        value={editReqRoleKey}
                        onChange={(e) => setEditReqRoleKey(e.target.value)}
                      />
                      <input
                        placeholder="Location"
                        value={editReqLocation}
                        onChange={(e) => setEditReqLocation(e.target.value)}
                      />
                      <select
                        className="p2__select"
                        value={editReqEmploymentType}
                        onChange={(e) => setEditReqEmploymentType(e.target.value)}
                      >
                        <option value="">-- Employment Type --</option>
                        <option value="full_time">Full Time</option>
                        <option value="part_time">Part Time</option>
                        <option value="internship">Internship</option>
                        <option value="contract">Contract</option>
                        <option value="apprenticeship">Apprenticeship</option>
                      </select>
                      <input
                        type="number"
                        step="0.5"
                        min="0"
                        placeholder="Min Experience (years)"
                        value={editReqMinYears}
                        onChange={(e) => setEditReqMinYears(e.target.value)}
                      />
                      <select
                        className="p2__select"
                        value={editReqStatus}
                        onChange={(e) => setEditReqStatus(e.target.value as "draft" | "open" | "paused" | "closed")}
                      >
                        <option value="open">Open</option>
                        <option value="draft">Draft</option>
                        <option value="paused">Paused</option>
                        <option value="closed">Closed</option>
                      </select>
                      <textarea
                        className="p2__textarea"
                        placeholder="Description"
                        value={editReqDescription}
                        onChange={(e) => setEditReqDescription(e.target.value)}
                      />
                      <input
                        placeholder="Qualification text"
                        value={editReqQualification}
                        onChange={(e) => setEditReqQualification(e.target.value)}
                      />
                      <div className="p2__row">
                        <button type="button" className="p2__btn" onClick={handleUpdateRequirement} disabled={saving}>
                          Save Role
                        </button>
                        <button type="button" className="p2__btn p2__btn--ghost" onClick={() => setEditingReq(false)}>
                          Cancel
                        </button>
                      </div>
                    </div>
                  )}

                  {/* Required Skills Management */}
                  <div style={{ marginTop: "1rem" }}>
                    <h4>Required Skills ({reqSkills.length})</h4>
                    <ul className="p2__list">
                      {reqSkills.map((s) => (
                        <li key={s.skill_id} className="p2__skill-row">
                          <div>
                            <strong>{s.skill_name || s.skill_id}</strong>
                            {s.skill_category && <span className="p2__hint"> ({s.skill_category})</span>}
                            <span className={`p2__badge p2__badge--${s.importance}`} style={{ marginLeft: "0.5rem" }}>
                              {s.importance}
                            </span>
                            {s.required_level != null && (
                              <span className="p2__hint" style={{ marginLeft: "0.5rem" }}>
                                Level: {(s.required_level * 100).toFixed(0)}%
                              </span>
                            )}
                            {s.note && <div className="p2__hint">{s.note}</div>}
                          </div>
                          <button
                            type="button"
                            className="p2__btn p2__btn--danger-ghost"
                            style={{ padding: "0.2rem 0.5rem", fontSize: "0.75rem" }}
                            onClick={() => handleRemoveSkill(s.skill_id)}
                            disabled={saving}
                          >
                            Remove
                          </button>
                        </li>
                      ))}
                      {reqSkills.length === 0 && (
                        <li className="p2__hint">No required skills attached to this requirement yet.</li>
                      )}
                    </ul>

                    {/* Add Skill to Requirement Form */}
                    <div className="p2__form" style={{ marginTop: "0.75rem" }}>
                      <h5>Attach Canonical Skill</h5>
                      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.5rem" }}>
                        <select
                          className="p2__select"
                          value={selectedSkillId}
                          onChange={(e) => setSelectedSkillId(e.target.value)}
                        >
                          <option value="">-- Select Canonical Skill --</option>
                          {catalog.map((c) => (
                            <option key={c.id} value={c.id}>
                              {c.display_name} ({c.canonical_name})
                            </option>
                          ))}
                        </select>
                        <select
                          className="p2__select"
                          value={skillImportance}
                          onChange={(e) => setSkillImportance(e.target.value as "required" | "preferred")}
                        >
                          <option value="required">Required</option>
                          <option value="preferred">Preferred</option>
                        </select>
                      </div>
                      <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
                        <label style={{ fontSize: "0.85rem", whiteSpace: "nowrap" }}>
                          Proficiency: {(parseFloat(skillLevel || "0") * 100).toFixed(0)}%
                        </label>
                        <input
                          type="range"
                          min="0"
                          max="1"
                          step="0.05"
                          value={skillLevel}
                          onChange={(e) => setSkillLevel(e.target.value)}
                          style={{ flex: 1 }}
                        />
                      </div>
                      <input
                        placeholder="Note or context (e.g. minimum 2 years production experience)"
                        value={skillNote}
                        onChange={(e) => setSkillNote(e.target.value)}
                      />
                      <button type="button" className="p2__btn" onClick={handleAddSkill} disabled={saving || !selectedSkillId}>
                        Add / Update Skill
                      </button>
                    </div>
                  </div>
                </div>
              )}

              {/* Create Requirement Form */}
              <div className="p2__form" style={{ marginTop: "1.5rem" }}>
                <h3>Post New Hiring Requirement</h3>
                <input
                  aria-label="Role title"
                  placeholder="Role title (e.g. Backend Intern) *"
                  value={reqTitle}
                  onChange={(e) => setReqTitle(e.target.value)}
                />
                <input
                  aria-label="Industry role key"
                  placeholder="Industry role key (e.g. software_engineer)"
                  value={reqRoleKey}
                  onChange={(e) => setReqRoleKey(e.target.value)}
                />
                <input
                  aria-label="Location"
                  placeholder="Location (e.g. Bengaluru / Hybrid)"
                  value={reqLocation}
                  onChange={(e) => setReqLocation(e.target.value)}
                />
                <select
                  className="p2__select"
                  value={reqEmploymentType}
                  onChange={(e) => setReqEmploymentType(e.target.value)}
                >
                  <option value="">-- Employment Type (optional) --</option>
                  <option value="full_time">Full Time</option>
                  <option value="part_time">Part Time</option>
                  <option value="internship">Internship</option>
                  <option value="contract">Contract</option>
                  <option value="apprenticeship">Apprenticeship</option>
                </select>
                <input
                  type="number"
                  step="0.5"
                  min="0"
                  placeholder="Minimum experience (years, optional)"
                  value={reqMinYears}
                  onChange={(e) => setReqMinYears(e.target.value)}
                />
                <textarea
                  className="p2__textarea"
                  placeholder="Role description (optional)"
                  value={reqDescription}
                  onChange={(e) => setReqDescription(e.target.value)}
                />
                <input
                  placeholder="Qualification text (e.g. B.Tech / BE in CS)"
                  value={reqQualification}
                  onChange={(e) => setReqQualification(e.target.value)}
                />
                <button type="button" className="p2__btn" onClick={handleAddRequirement} disabled={saving}>
                  {saving ? "Saving…" : "Post Requirement"}
                </button>
              </div>
            </>
          )}
        </section>
      </div>
    </main>
  );
}
