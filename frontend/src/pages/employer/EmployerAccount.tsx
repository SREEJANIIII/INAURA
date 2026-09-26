import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../../context/AuthContext";
import { useEmployer } from "../../context/EmployerContext";
import "../../components/employer/EmployerComponents.css";

export default function EmployerAccount() {
  const { user, signOut } = useAuth();
  const { currentEmployer, employers, isOwner } = useEmployer();
  const navigate = useNavigate();

  const handleLogout = async () => {
    await signOut();
    navigate("/login", { replace: true });
  };

  return (
    <div>
      <div className="emp-page-header">
        <div>
          <h1>Employer Account</h1>
          <p>Manage your employer profile, credentials, and organization access.</p>
        </div>
      </div>

      <div className="emp-card" style={{ maxWidth: 720 }}>
        <h2 className="emp-card__title" style={{ marginBottom: "1rem" }}>
          User Credentials
        </h2>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "1rem", marginBottom: "1.25rem" }}>
          <div>
            <div style={{ fontSize: "0.75rem", textTransform: "uppercase", fontWeight: 600, color: "var(--muted)" }}>Email</div>
            <div style={{ fontSize: "1rem", fontWeight: 600, marginTop: "0.2rem" }}>{user?.email || "—"}</div>
          </div>
          <div>
            <div style={{ fontSize: "0.75rem", textTransform: "uppercase", fontWeight: 600, color: "var(--muted)" }}>User ID</div>
            <div style={{ fontSize: "0.85rem", marginTop: "0.2rem" }}><code>{user?.id}</code></div>
          </div>
          <div>
            <div style={{ fontSize: "0.75rem", textTransform: "uppercase", fontWeight: 600, color: "var(--muted)" }}>Organization Role</div>
            <div style={{ marginTop: "0.2rem" }}>
              <span className={`emp-badge ${isOwner ? "emp-badge--open" : "emp-badge--applied"}`}>
                {isOwner ? "Owner" : "Member"}
              </span>
            </div>
          </div>
        </div>

        <div style={{ borderTop: "1px solid var(--line)", paddingTop: "1rem", marginTop: "1rem" }}>
          <h3 style={{ fontSize: "0.95rem", fontWeight: 700, margin: "0 0 0.5rem" }}>
            Associated Organizations ({employers.length})
          </h3>
          <ul style={{ listStyle: "none", padding: 0, margin: "0 0 1.25rem 0", display: "flex", flexDirection: "column", gap: "0.5rem" }}>
            {employers.map((emp) => (
              <li
                key={emp.id}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  padding: "0.6rem 0.85rem",
                  background: "var(--paper-2, #f8fafc)",
                  borderRadius: "8px",
                  border: "1px solid var(--line)",
                  fontSize: "0.875rem",
                }}
              >
                <div>
                  <strong>{emp.name}</strong>
                  <div style={{ fontSize: "0.75rem", color: "var(--muted)" }}>{emp.industry || "General"} • {emp.location || "Location not specified"}</div>
                </div>
                {currentEmployer?.id === emp.id && (
                  <span className="emp-badge emp-badge--open">Active Workplace</span>
                )}
              </li>
            ))}
          </ul>
        </div>

        <div style={{ borderTop: "1px solid var(--line)", paddingTop: "1rem", display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "0.75rem" }}>
          <Link to="/career-track" className="emp-btn emp-btn--secondary">
            Switch to Student Portal
          </Link>
          <button
            type="button"
            className="emp-btn emp-btn--danger"
            onClick={handleLogout}
          >
            Log Out of INAURA
          </button>
        </div>
      </div>
    </div>
  );
}
