import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../../context/AuthContext";
import { profileData, subscribePageData } from "../../lib/pageData";

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
  const rootRef = useRef<HTMLDivElement>(null);

  const name = profile?.full_name || user?.email?.split("@")[0] || "Account";

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

  const toggle = (p: Panel) => setPanel((cur) => (cur === p ? "none" : p));

  const handleLogout = async () => {
    setPanel("none");
    await signOut();
    nav("/login", { replace: true });
  };

  return (
    <div className="acct" ref={rootRef}>
      <button
        type="button"
        className="acct__bell"
        aria-label="Notifications"
        aria-expanded={panel === "notifications"}
        onClick={() => toggle("notifications")}
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
          <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
        </svg>
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
        <div className="acct__panel acct__panel--notif" role="status">
          <div className="acct__panel-title">Notifications</div>
          <p className="acct__empty">You’re all caught up.</p>
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
          <button type="button" className="acct__item acct__item--danger" role="menuitem" onClick={handleLogout}>
            Log out
          </button>
        </div>
      )}
    </div>
  );
}
