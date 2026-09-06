import { Navigate } from "react-router-dom";
import { useAuth } from "../../context/AuthContext";
import type { ReactNode } from "react";

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { user, loading, isConfigured } = useAuth();

  if (!isConfigured) {
    return (
      <div style={{ padding: "4rem 1.5rem", textAlign: "center", maxWidth: 640, margin: "0 auto" }}>
        <h2 style={{ fontSize: "1.25rem", fontWeight: 700 }}>Supabase not configured</h2>
        <p style={{ color: "#475569", marginTop: 8 }}>
          Set <code>VITE_SUPABASE_URL</code> and <code>VITE_SUPABASE_ANON_KEY</code> in <code>frontend/.env</code>.
          See <code>frontend/.env.example</code>.
        </p>
      </div>
    );
  }

  if (loading) {
    return (
      <div style={{ padding: "4rem 1.5rem", textAlign: "center", color: "#64748b" }}>
        Checking session…
      </div>
    );
  }

  if (!user) {
    return <Navigate to="/login" replace />;
  }

  return <>{children}</>;
}

export function GuestOnly({ children }: { children: ReactNode }) {
  const { user, loading, isConfigured } = useAuth();

  if (loading) {
    return (
      <div style={{ padding: "4rem 1.5rem", textAlign: "center", color: "#64748b" }}>
        Checking session…
      </div>
    );
  }

  // If Supabase not configured, allow guest pages to render (show config warning inside)
  if (isConfigured && user) {
    return <Navigate to="/dashboard" replace />;
  }

  return <>{children}</>;
}
