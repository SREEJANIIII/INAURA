import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../../context/AuthContext";
import { useEmployer } from "../../context/EmployerContext";
import type { ReactNode } from "react";

function CheckingEmployer() {
  return (
    <div className="session-check" role="status" aria-live="polite">
      <span className="session-check__spin" aria-hidden="true" />
      Verifying employer credentials…
    </div>
  );
}

export function EmployerRoute({ children }: { children: ReactNode }) {
  const { user, loading: authLoading, isConfigured } = useAuth();
  const { loading: empLoading } = useEmployer();
  const location = useLocation();

  if (!isConfigured) {
    return (
      <div style={{ padding: "4rem 1.5rem", textAlign: "center", maxWidth: 640, margin: "0 auto" }}>
        <h2 style={{ fontSize: "1.25rem", fontWeight: 700 }}>Supabase not configured</h2>
        <p style={{ color: "var(--muted)", marginTop: 8 }}>
          Set <code>VITE_SUPABASE_URL</code> and <code>VITE_SUPABASE_ANON_KEY</code> in <code>frontend/.env</code>.
        </p>
      </div>
    );
  }

  if (authLoading || empLoading) {
    return <CheckingEmployer />;
  }

  if (!user) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  return <>{children}</>;
}
