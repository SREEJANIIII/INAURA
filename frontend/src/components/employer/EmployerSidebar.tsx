import { type ReactNode, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../../context/AuthContext";
import "./EmployerLayout.css";

type EmployerSidebarProps = {
  open: boolean;
  onNavigate: () => void;
};

const Icon = ({ children }: { children: ReactNode }) => (
  <svg
    className="emp-sidebar__icon"
    width="18"
    height="18"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.8"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    {children}
  </svg>
);

export default function EmployerSidebar({ open, onNavigate }: EmployerSidebarProps) {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const { signOut } = useAuth();
  const [loggingOut, setLoggingOut] = useState(false);

  const handleLogout = async () => {
    setLoggingOut(true);
    onNavigate();
    try {
      await signOut();
    } finally {
      navigate("/login", { replace: true });
    }
  };

  const isActive = (to: string) => {
    if (to === "/employer/dashboard" || to === "/employer") {
      return pathname === "/employer" || pathname === "/employer/dashboard";
    }
    return pathname.startsWith(to);
  };

  return (
    <aside
      id="employer-sidebar"
      className={`emp-sidebar${open ? " is-open" : ""}`}
      aria-label="Employer Portal Navigation"
      aria-hidden={!open}
    >
      <div className="emp-sidebar__nav">
        <div className="emp-sidebar__section">Overview</div>
        <Link
          to="/employer/dashboard"
          className={`emp-sidebar__link${isActive("/employer/dashboard") ? " is-active" : ""}`}
          onClick={onNavigate}
        >
          <Icon>
            <rect x="3" y="3" width="7" height="7" rx="1" />
            <rect x="14" y="3" width="7" height="7" rx="1" />
            <rect x="14" y="14" width="7" height="7" rx="1" />
            <rect x="3" y="14" width="7" height="7" rx="1" />
          </Icon>
          <span>Employer Dashboard</span>
        </Link>

        <div className="emp-sidebar__section">Organization</div>
        <Link
          to="/employer/company"
          className={`emp-sidebar__link${isActive("/employer/company") ? " is-active" : ""}`}
          onClick={onNavigate}
        >
          <Icon>
            <path d="M3 21h18" />
            <path d="M9 8h1" />
            <path d="M9 12h1" />
            <path d="M9 16h1" />
            <path d="M14 8h1" />
            <path d="M14 12h1" />
            <path d="M14 16h1" />
            <path d="M5 21V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16" />
          </Icon>
          <span>Company</span>
        </Link>

        <div className="emp-sidebar__section">Talent &amp; Hiring</div>
        <Link
          to="/employer/requirements"
          className={`emp-sidebar__link${isActive("/employer/requirements") ? " is-active" : ""}`}
          onClick={onNavigate}
        >
          <Icon>
            <path d="M16 20V4a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16" />
            <rect x="2" y="6" width="20" height="14" rx="2" />
          </Icon>
          <span>Hiring Requirements</span>
        </Link>

        <Link
          to="/employer/candidates"
          className={`emp-sidebar__link${isActive("/employer/candidates") ? " is-active" : ""}`}
          onClick={onNavigate}
        >
          <Icon>
            <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
            <circle cx="9" cy="7" r="4" />
            <path d="M22 21v-2a4 4 0 0 0-3-3.87" />
            <path d="M16 3.13a4 4 0 0 1 0 7.75" />
          </Icon>
          <span>Candidates</span>
        </Link>

        <Link
          to="/employer/applications"
          className={`emp-sidebar__link${isActive("/employer/applications") ? " is-active" : ""}`}
          onClick={onNavigate}
        >
          <Icon>
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
            <line x1="16" y1="13" x2="8" y2="13" />
            <line x1="16" y1="17" x2="8" y2="17" />
            <polyline points="10 9 9 9 8 9" />
          </Icon>
          <span>Applications</span>
        </Link>

        <div className="emp-sidebar__section">Outcomes</div>
        <Link
          to="/employer/placements"
          className={`emp-sidebar__link${isActive("/employer/placements") ? " is-active" : ""}`}
          onClick={onNavigate}
        >
          <Icon>
            <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
            <polyline points="22 4 12 14.01 9 11.01" />
          </Icon>
          <span>Placements</span>
        </Link>

        <Link
          to="/employer/analytics"
          className={`emp-sidebar__link${isActive("/employer/analytics") ? " is-active" : ""}`}
          onClick={onNavigate}
        >
          <Icon>
            <path d="M3 3v18h18" />
            <path d="m19 9-5 5-4-4-3 3" />
          </Icon>
          <span>Analytics</span>
        </Link>

        <div className="emp-sidebar__section">Account</div>
        <Link
          to="/employer/account"
          className={`emp-sidebar__link${isActive("/employer/account") ? " is-active" : ""}`}
          onClick={onNavigate}
        >
          <Icon>
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
          </Icon>
          <span>Account</span>
        </Link>
      </div>

      <div className="emp-sidebar__foot">
        <button
          type="button"
          className="emp-sidebar__link emp-sidebar__link--logout"
          onClick={handleLogout}
          disabled={loggingOut}
        >
          <Icon>
            <path d="M15.5 8.5V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h7.5a2 2 0 0 0 2-2v-2.5" />
            <path d="M10 12h10" />
            <path d="m17.5 8.5 3.5 3.5-3.5 3.5" />
          </Icon>
          <span>{loggingOut ? "Logging out…" : "Logout"}</span>
        </button>
      </div>
    </aside>
  );
}
