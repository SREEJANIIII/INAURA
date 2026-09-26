import { Suspense, useEffect, useState, useRef } from "react";
import { Link, Outlet, useNavigate } from "react-router-dom";
import InauraLogo from "../layout/InauraLogo";
import EmployerSidebar from "./EmployerSidebar";
import { useAuth } from "../../context/AuthContext";
import { useEmployer } from "../../context/EmployerContext";
import { applyTheme, preferredTheme, setTheme, type Theme } from "../../lib/theme";
import "./EmployerLayout.css";

const SMALL = "(max-width: 860px)";
const isSmallScreen = () => window.matchMedia(SMALL).matches;

function PageLoading() {
  return (
    <div className="app__loading" aria-busy="true">
      <div className="app__loading-line app__loading-line--title" />
      <div className="app__loading-line" />
      <div className="app__loading-block" />
      <span className="sr-only">Loading employer workspace…</span>
    </div>
  );
}

export default function EmployerLayout() {
  const [open, setOpen] = useState(() => !isSmallScreen());
  const [orgDropdownOpen, setOrgDropdownOpen] = useState(false);
  const [theme, setCurrentTheme] = useState<Theme>(() => preferredTheme());
  const orgRef = useRef<HTMLDivElement>(null);

  const { user, signOut } = useAuth();
  const { employers, currentEmployer, setCurrentEmployer } = useEmployer();
  const navigate = useNavigate();

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  useEffect(() => {
    const onThemeChange = (event: Event) => {
      const value = (event as CustomEvent<Theme>).detail;
      if (value === "light" || value === "dark") setCurrentTheme(value);
    };
    window.addEventListener("inaura-theme-change", onThemeChange);
    return () => window.removeEventListener("inaura-theme-change", onThemeChange);
  }, []);

  // Screen resize watcher
  useEffect(() => {
    const query = window.matchMedia(SMALL);
    const onChange = () => setOpen(!query.matches);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  // Escape key watcher for mobile drawer
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isSmallScreen() && !e.defaultPrevented) setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  // Click outside to close org dropdown
  useEffect(() => {
    if (!orgDropdownOpen) return;
    const handleClick = (e: MouseEvent) => {
      if (!orgRef.current?.contains(e.target as Node)) {
        setOrgDropdownOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [orgDropdownOpen]);

  const toggleTheme = () => setTheme(theme === "dark" ? "light" : "dark");

  const handleLogout = async () => {
    await signOut();
    navigate("/login", { replace: true });
  };

  return (
    <div className="emp-app">
      <a href="#main-content" className="skip-link">Skip to employer content</a>
      <header className="emp-bar">
        <div className="emp-bar__lead">
          <button
            type="button"
            className="emp-bar__menu"
            aria-label={open ? "Close menu" : "Open menu"}
            aria-expanded={open}
            onClick={() => setOpen((o) => !o)}
          >
            <span />
            <span />
            <span />
          </button>
          <Link to="/employer/dashboard" className="emp-bar__brand-wrap" aria-label="INAURA Employer Home">
            <InauraLogo alt="INAURA" width={115} height={28} />
            <span className="emp-bar__portal-pill">Employer Portal</span>
          </Link>
        </div>

        <div className="emp-bar__center">
          {/* Active Company Selector */}
          <div className="emp-org-selector" ref={orgRef}>
            <button
              type="button"
              className="emp-org-btn"
              onClick={() => setOrgDropdownOpen((prev) => !prev)}
              aria-haspopup="listbox"
              aria-expanded={orgDropdownOpen}
              title="Switch Active Company"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M3 21h18" />
                <path d="M5 21V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16" />
              </svg>
              <span>{currentEmployer ? currentEmployer.name : "Select Company"}</span>
              <svg width="12" height="12" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                <path d="M3.5 5.25 7 8.75l3.5-3.5" />
              </svg>
            </button>

            {orgDropdownOpen && (
              <div className="emp-org-dropdown" role="listbox">
                <div style={{ fontSize: "0.75rem", fontWeight: 600, color: "var(--muted)", padding: "0.25rem 0.5rem 0.5rem" }}>
                  Your Companies
                </div>
                {employers.map((emp) => (
                  <button
                    key={emp.id}
                    type="button"
                    className={`emp-org-item${currentEmployer?.id === emp.id ? " is-selected" : ""}`}
                    onClick={() => {
                      setCurrentEmployer(emp);
                      setOrgDropdownOpen(false);
                    }}
                  >
                    <span>{emp.name}</span>
                    {currentEmployer?.id === emp.id && <span>✓</span>}
                  </button>
                ))}
                {employers.length === 0 && (
                  <div style={{ padding: "0.5rem", fontSize: "0.8rem", color: "var(--muted)" }}>
                    No companies registered yet.
                  </div>
                )}
                <div style={{ borderTop: "1px solid var(--line)", marginTop: "0.35rem", paddingTop: "0.35rem" }}>
                  <Link
                    to="/employer/company"
                    className="emp-org-item"
                    style={{ color: "#0d9488", fontWeight: 600 }}
                    onClick={() => setOrgDropdownOpen(false)}
                  >
                    + Manage Companies
                  </Link>
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="emp-bar__actions">
          {/* Quick link back to Student Portal */}
          <Link
            to="/career-track"
            className="emp-switch-portal-btn"
            title="Switch to Student Dashboard"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M22 10v6M2 10l10-5 10 5-10 5z" />
              <path d="M6 12v5c3 3 9 3 12 0v-5" />
            </svg>
            <span>Student Portal</span>
          </Link>

          {/* Theme button */}
          <button
            type="button"
            className="emp-btn emp-btn--secondary emp-btn--sm"
            onClick={toggleTheme}
            aria-label="Toggle theme appearance"
            title={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
          >
            {theme === "dark" ? "☾" : "☀"}
          </button>

          {/* User initials & logout */}
          <button
            type="button"
            className="emp-btn emp-btn--secondary emp-btn--sm"
            onClick={handleLogout}
            title={user?.email ? `Signed in as ${user.email} - Log out` : "Log out"}
          >
            Sign out
          </button>
        </div>
      </header>

      <div className="emp-body">
        {open && <div className="emp-backdrop" onClick={() => setOpen(false)} aria-hidden="true" />}
        <EmployerSidebar
          open={open}
          onNavigate={() => {
            if (isSmallScreen()) setOpen(false);
          }}
        />
        <main id="main-content" className="emp-content" tabIndex={-1}>
          <Suspense fallback={<PageLoading />}>
            <Outlet />
          </Suspense>
        </main>
      </div>
    </div>
  );
}
