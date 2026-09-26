import { useState } from "react";
import { useEmployer } from "../../context/EmployerContext";
import { addMember, removeMember } from "../../services/employers";
import CompanyModal from "../../components/employer/CompanyModal";
import "../../components/employer/EmployerComponents.css";

export default function EmployerCompany() {
  const {
    employers,
    currentEmployer,
    setCurrentEmployer,
    members,
    isOwner,
    refreshMembers,
    refreshEmployers,
  } = useEmployer();

  const [showCompanyModal, setShowCompanyModal] = useState(false);
  const [modalEmployer, setModalEmployer] = useState<typeof currentEmployer | null>(null);

  // Add member form state
  const [newUserId, setNewUserId] = useState("");
  const [newRole, setNewRole] = useState<"member" | "owner">("member");
  const [addingMember, setAddingMember] = useState(false);
  const [memberError, setMemberError] = useState<string | null>(null);
  const [memberSuccess, setMemberSuccess] = useState<string | null>(null);

  const handleAddMember = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!currentEmployer) return;
    if (!newUserId.trim()) {
      setMemberError("Please enter the user ID of the team member.");
      return;
    }

    setAddingMember(true);
    setMemberError(null);
    setMemberSuccess(null);
    try {
      await addMember(currentEmployer.id, {
        user_id: newUserId.trim(),
        role: newRole,
      });
      setNewUserId("");
      setMemberSuccess("Team member added successfully.");
      await refreshMembers();
    } catch (err) {
      setMemberError(err instanceof Error ? err.message : String(err));
    } finally {
      setAddingMember(false);
    }
  };

  const handleRemoveMember = async (targetUserId: string) => {
    if (!currentEmployer) return;
    if (!window.confirm("Are you sure you want to remove this member from the organization?")) {
      return;
    }

    setMemberError(null);
    setMemberSuccess(null);
    try {
      await removeMember(currentEmployer.id, targetUserId);
      setMemberSuccess("Member removed.");
      await refreshMembers();
    } catch (err) {
      setMemberError(err instanceof Error ? err.message : String(err));
    }
  };

  if (!currentEmployer) {
    return (
      <div>
        <div className="emp-page-header">
          <div>
            <h1>Company Management</h1>
            <p>Register and manage your organization profile.</p>
          </div>
          <button
            type="button"
            className="emp-btn emp-btn--primary"
            onClick={() => {
              setModalEmployer(null);
              setShowCompanyModal(true);
            }}
          >
            + Register Company
          </button>
        </div>

        <div className="emp-card" style={{ textAlign: "center", padding: "3rem" }}>
          <h3>No Company Registered</h3>
          <p style={{ color: "var(--muted)" }}>You do not belong to any employer organization yet.</p>
        </div>

        {showCompanyModal && (
          <CompanyModal
            employer={modalEmployer}
            onClose={() => setShowCompanyModal(false)}
            onSaved={() => void refreshEmployers()}
          />
        )}
      </div>
    );
  }

  return (
    <div>
      <div className="emp-page-header">
        <div>
          <h1>Company &amp; Organization</h1>
          <p>
            Manage profile details, hiring credentials, and team members for <strong>{currentEmployer.name}</strong>.
          </p>
        </div>
        <div className="emp-header-actions">
          {isOwner && (
            <button
              type="button"
              className="emp-btn emp-btn--secondary"
              onClick={() => {
                setModalEmployer(currentEmployer);
                setShowCompanyModal(true);
              }}
            >
              ✎ Edit Profile
            </button>
          )}
          <button
            type="button"
            className="emp-btn emp-btn--primary"
            onClick={() => {
              setModalEmployer(null);
              setShowCompanyModal(true);
            }}
          >
            + New Company
          </button>
        </div>
      </div>

      {/* Switcher if user has multiple companies */}
      {employers.length > 1 && (
        <div className="emp-card" style={{ padding: "0.85rem 1.25rem", marginBottom: "1.25rem" }}>
          <div style={{ fontSize: "0.8rem", fontWeight: 700, textTransform: "uppercase", color: "var(--muted)", marginBottom: "0.5rem" }}>
            Switch Active Organization
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem" }}>
            {employers.map((emp) => (
              <button
                key={emp.id}
                type="button"
                className={`emp-btn ${
                  currentEmployer.id === emp.id ? "emp-btn--primary" : "emp-btn--secondary"
                } emp-btn--sm`}
                onClick={() => setCurrentEmployer(emp)}
              >
                {emp.name} {currentEmployer.id === emp.id ? "(Active)" : ""}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Company Profile Details */}
      <div className="emp-card">
        <div className="emp-card__header">
          <h2 className="emp-card__title">Organization Profile</h2>
          <span className={`emp-badge emp-badge--${currentEmployer.status}`}>
            {currentEmployer.status}
          </span>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: "1.25rem", marginBottom: "1.25rem" }}>
          <div>
            <div style={{ fontSize: "0.75rem", textTransform: "uppercase", fontWeight: 600, color: "var(--muted)" }}>Company Name</div>
            <div style={{ fontSize: "1.1rem", fontWeight: 700, marginTop: "0.2rem" }}>{currentEmployer.name}</div>
          </div>
          <div>
            <div style={{ fontSize: "0.75rem", textTransform: "uppercase", fontWeight: 600, color: "var(--muted)" }}>Industry</div>
            <div style={{ fontSize: "1rem", marginTop: "0.2rem" }}>{currentEmployer.industry || "Not specified"}</div>
          </div>
          <div>
            <div style={{ fontSize: "0.75rem", textTransform: "uppercase", fontWeight: 600, color: "var(--muted)" }}>Headquarters / Location</div>
            <div style={{ fontSize: "1rem", marginTop: "0.2rem" }}>{currentEmployer.location || "Not specified"}</div>
          </div>
          <div>
            <div style={{ fontSize: "0.75rem", textTransform: "uppercase", fontWeight: 600, color: "var(--muted)" }}>Official Website</div>
            <div style={{ fontSize: "1rem", marginTop: "0.2rem" }}>
              {currentEmployer.website ? (
                <a href={currentEmployer.website} target="_blank" rel="noreferrer" style={{ color: "#0d9488", textDecoration: "underline" }}>
                  {currentEmployer.website}
                </a>
              ) : (
                "Not specified"
              )}
            </div>
          </div>
          {currentEmployer.contact_email && (
            <div>
              <div style={{ fontSize: "0.75rem", textTransform: "uppercase", fontWeight: 600, color: "var(--muted)" }}>Hiring Contact Email</div>
              <div style={{ fontSize: "1rem", marginTop: "0.2rem" }}>{currentEmployer.contact_email}</div>
            </div>
          )}
        </div>

        {currentEmployer.description && (
          <div style={{ borderTop: "1px solid var(--line)", paddingTop: "1rem", marginTop: "0.5rem" }}>
            <div style={{ fontSize: "0.75rem", textTransform: "uppercase", fontWeight: 600, color: "var(--muted)", marginBottom: "0.35rem" }}>
              About Organization
            </div>
            <p style={{ margin: 0, fontSize: "0.9rem", color: "var(--ink-700)" }}>{currentEmployer.description}</p>
          </div>
        )}
      </div>

      {/* Team Members Management (Section 9) */}
      <div className="emp-card">
        <div className="emp-card__header">
          <div>
            <h2 className="emp-card__title">Team Members &amp; Access ({members.length})</h2>
            <div style={{ fontSize: "0.85rem", color: "var(--muted)", marginTop: "0.2rem" }}>
              {isOwner ? "You have Owner privileges. You can invite team members and adjust roles." : "You have Member access to this organization."}
            </div>
          </div>
        </div>

        {memberError && (
          <div style={{ background: "#fef2f2", color: "#dc2626", padding: "0.6rem 0.85rem", borderRadius: "8px", marginBottom: "1rem", fontSize: "0.85rem" }}>
            {memberError}
          </div>
        )}

        {memberSuccess && (
          <div style={{ background: "#ecfdf5", color: "#0f766e", padding: "0.6rem 0.85rem", borderRadius: "8px", marginBottom: "1rem", fontSize: "0.85rem" }}>
            {memberSuccess}
          </div>
        )}

        {/* Add Member Form (Owners only) */}
        {isOwner && (
          <form onSubmit={handleAddMember} style={{ background: "var(--paper-2, #f8fafc)", padding: "1rem", borderRadius: "8px", border: "1px solid var(--line)", marginBottom: "1.25rem" }}>
            <div style={{ fontSize: "0.85rem", fontWeight: 700, marginBottom: "0.75rem" }}>
              + Add Organization Member
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem", alignItems: "flex-end" }}>
              <div className="emp-field" style={{ flex: 1, minWidth: 260 }}>
                <label className="emp-label">User ID (Supabase Auth UUID)</label>
                <input
                  className="emp-input"
                  type="text"
                  placeholder="e.g. 550e8400-e29b-41d4-a716-446655440000"
                  value={newUserId}
                  onChange={(e) => setNewUserId(e.target.value)}
                  required
                />
              </div>

              <div className="emp-field" style={{ width: 140 }}>
                <label className="emp-label">Access Role</label>
                <select
                  className="emp-select"
                  value={newRole}
                  onChange={(e) => setNewRole(e.target.value as "member" | "owner")}
                >
                  <option value="member">Member</option>
                  <option value="owner">Owner</option>
                </select>
              </div>

              <button
                type="submit"
                className="emp-btn emp-btn--primary"
                disabled={addingMember}
              >
                {addingMember ? "Adding…" : "Add Member"}
              </button>
            </div>
          </form>
        )}

        {/* Members Table */}
        <div className="emp-table-wrap">
          <table className="emp-table">
            <thead>
              <tr>
                <th>Member User ID</th>
                <th>Role</th>
                <th>Joined</th>
                {isOwner && <th>Action</th>}
              </tr>
            </thead>
            <tbody>
              {members.map((m) => (
                <tr key={m.id}>
                  <td>
                    <code>{m.user_id}</code>
                  </td>
                  <td>
                    <span className={`emp-badge ${m.role === "owner" ? "emp-badge--open" : "emp-badge--applied"}`}>
                      {m.role}
                    </span>
                  </td>
                  <td style={{ fontSize: "0.8rem", color: "var(--muted)" }}>
                    {new Date(m.created_at).toLocaleDateString()}
                  </td>
                  {isOwner && (
                    <td>
                      <button
                        type="button"
                        className="emp-btn emp-btn--danger-ghost emp-btn--sm"
                        onClick={() => handleRemoveMember(m.user_id)}
                      >
                        Remove
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {showCompanyModal && (
        <CompanyModal
          employer={modalEmployer}
          onClose={() => setShowCompanyModal(false)}
          onSaved={() => {
            void refreshEmployers();
          }}
        />
      )}
    </div>
  );
}
