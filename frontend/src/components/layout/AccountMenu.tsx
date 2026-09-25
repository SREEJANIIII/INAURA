import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../../context/AuthContext";
import { analysisStateData, evidencePageData, profileData, resultsPageData, subscribePageData } from "../../lib/pageData";
import { getRoleSync, subscribeRoleSync } from "../../lib/roleSync";
import { dueCount } from "../../lib/revision/store";
import { applyTheme, preferredTheme, setTheme, type Theme } from "../../lib/theme";
import { buildNotices } from "./notices";

type Panel = "none" | "account" | "notifications";

const initials = (name: string) =>
  name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("") || "?";

// Top-right of the app bar: notifications bell + avatar, name and a dropdown with Profile / Log out
export default function AccountMenu() {
  const { user, signOut } = useAuth();
  const nav = useNavigate();
  const profile = useSyncExternalStore(subscribePageData, profileData.peek);
  const [panel, setPanel] = useState<Panel>("none");
  const [theme, setCurrentTheme] = useState<Theme>(() => preferredTheme());
  const rootRef = useRef<HTMLDivElement>(null);

  const name = profile?.full_name || user?.email?.split("@")[0] || "Account";

  // The bell reads the same shared data the pages do, so it's never a separate story
  const results = useSyncExternalStore(subscribePageData, resultsPageData.peek);
  const analysisState = useSyncExternalStore(subscribePageData, analysisStateData.peek);
  const evidence = useSyncExternalStore(subscribePageData, evidencePageData.peek);
  const sync = useSyncExternalStore(subscribeRoleSync, getRoleSync);
  // Read from this browser's revision record when the menu mounts and whenever the bell opens
  const [revisionDue, setRevisionDue] = useState(() => (user ? dueCount(user.id, Date.now()) : 0));
  const notices = useMemo(() => {
    const state = analysisState ?? evidence?.analysisState;
    return buildNotices({
      analysis: results?.analysis,
      targetRole: state?.target_role,
      analysedBefore: state?.status === "completed" || !!results?.analysis,
      evidence: evidence?.evidence,
      projectCount: evidence?.projects.length,
      certCount: evidence?.certs.length,
      sync,
      revisionDue,
    });
  }, [results, analysisState, evidence, sync, revisionDue]);

  // Close when clicking elsewhere or pressing Escape
  useEffect(() => {
    if (panel === "none") return;
    const onClick = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setPanel("none");
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setPanel("none");
    };
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [panel]);

  const toggle = (p: Panel) => {
    if (p === "notifications" && user) setRevisionDue(dueCount(user.id, Date.now()));
    setPanel((cur) => (cur === p ? "none" : p));
  };

  const handleLogout = async () => {
    setPanel("none");
    await signOut();
    nav("/login", { replace: true });
  };

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

  const toggleTheme = () => setTheme(theme === "dark" ? "light" : "dark");

  return (
    <div className="acct" ref={rootRef}>
      <button
        type="button"
        className="acct__bell"
        aria-label={notices.length ? `Notifications, ${notices.length} to look at` : "Notifications"}
        aria-expanded={panel === "notifications"}
        aria-haspopup="true"
        onClick={() => toggle("notifications")}
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
          <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
        </svg>
        {notices.length > 0 && (
          <span className="acct__bell-count" aria-hidden="true">
            {notices.length > 9 ? "9+" : notices.length}
          </span>
        )}
      </button>

      <button
        type="button"
        className="acct__trigger"
        aria-haspopup="menu"
        aria-expanded={panel === "account"}
        onClick={() => toggle("account")}
      >
        <span className="acct__avatar" aria-hidden="true">
          {initials(name)}
        </span>
        <span className="acct__who">
          <span className="acct__name">{name}</span>
          <span className="acct__role">Student</span>
        </span>
        <svg className="acct__chevron" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="m6 9 6 6 6-6" />
        </svg>
      </button>

      {panel === "notifications" && (
        <div className="acct__panel acct__panel--notif">
          <div className="acct__panel-title" id="acct-notif-title">Notifications</div>
          {notices.length === 0 ? (
            <p className="acct__empty">You’re all caught up. Nothing needs your attention right now.</p>
          ) : (
            <ul className="acct__notices" aria-labelledby="acct-notif-title">
              {notices.map((n) => (
                <li key={n.id}>
                  <Link to={n.to} className={`acct__notice acct__notice--${n.tone}`} onClick={() => setPanel("none")}>
                    <span className="acct__notice-mark" aria-hidden="true" />
                    <span className="acct__notice-text">
                      <span className="acct__notice-title">{n.title}</span>
                      {n.detail && <span className="acct__notice-detail">{n.detail}</span>}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}


      {panel === "account" && (
        <div className="acct__panel" role="menu">
          <div className="acct__panel-head">
            <span className="acct__name">{name}</span>
            {user?.email && <span className="acct__email">{user.email}</span>}
          </div>
          <Link to="/profile" className="acct__item" role="menuitem" onClick={() => setPanel("none")}>
            My profile
          </Link>
          <button
            type="button"
            className="acct__item acct__theme"
            role="menuitem"
            aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
            onClick={toggleTheme}
          >
            <span>Appearance</span>
            <span className="acct__theme-value" aria-live="polite">
              {theme === "dark" ? "☾ Dark" : "☀ Light"}
            </span>
          </button>
          <button type="button" className="acct__item acct__item--danger" role="menuitem" onClick={handleLogout}>
            Log out
          </button>
        </div>
      )}
    </div>
  );
}
