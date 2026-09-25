import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../../context/AuthContext";
import { returnPath } from "../../lib/authRedirect";
import type { ReactNode } from "react";

function Checking() {
  return (
    <div className="session-check" role="status" aria-live="polite">
      <span className="session-check__spin" aria-hidden="true" />
      Checking your session…
    </div>
  );
}

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { user, loading, isConfigured } = useAuth();
  const location = useLocation();

  if (!isConfigured) {
    return (
      <div style={{ padding: "4rem 1.5rem", textAlign: "center", maxWidth: 640, margin: "0 auto" }}>
        <h2 style={{ fontSize: "1.25rem", fontWeight: 700 }}>Supabase not configured</h2>
        <p style={{ color: "var(--muted)", marginTop: 8 }}>
          Set <code>VITE_SUPABASE_URL</code> and <code>VITE_SUPABASE_ANON_KEY</code> in <code>frontend/.env</code>.
          See <code>frontend/.env.example</code>.
        </p>
      </div>
    );
  }

  if (loading) return <Checking />;

  if (!user) {
    // Remember the page, so a link shared to a logged-out student still ends up there
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  return <>{children}</>;
}

export function GuestOnly({ children }: { children: ReactNode }) {
  const { user, loading, isConfigured } = useAuth();
  const location = useLocation();

  if (loading) return <Checking />;

  // If Supabase not configured, allow guest pages to render (show config warning inside)
  if (isConfigured && user) {
    return <Navigate to={returnPath(location.state)} replace />;
  }

  return <>{children}</>;
}
