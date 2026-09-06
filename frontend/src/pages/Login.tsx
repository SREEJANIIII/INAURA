import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { getProfile } from "../services/profile";
import Button from "../components/ui/Button";
import "./Auth.css";

function validateEmail(v: string) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v);
}

export default function Login() {
  const { signIn, resetPassword, isConfigured } = useAuth();
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [showForgot, setShowForgot] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setInfo(null);

    if (!isConfigured) {
      setError("Supabase is not configured. Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY in frontend/.env");
      return;
    }
    if (!validateEmail(email)) {
      setError("Please enter a valid email address.");
      return;
    }
    if (!password) {
      setError("Please enter your password.");
      return;
    }

    setLoading(true);
    try {
      const { error: authErr } = await signIn(email.trim(), password);
      if (authErr) {
        // Map common Supabase errors to friendly messages
        const msg = authErr.toLowerCase();
        if (msg.includes("invalid login credentials") || msg.includes("invalid email or password")) {
          setError("Incorrect email or password. Please try again.");
        } else if (msg.includes("email not confirmed")) {
          setError("Please confirm your email before logging in. Check your inbox.");
        } else {
          setError(authErr);
        }
        return;
      }

      // Check profile — handle each status explicitly
      try {
        await getProfile();
        nav("/dashboard", { replace: true });
      } catch (err) {
        const m = err instanceof Error ? err.message : "";
        const lower = m.toLowerCase();
        if (m.includes("404") || lower.includes("not found")) {
          nav("/profile/setup", { replace: true });
        } else if (m.includes("401") || lower.includes("not authenticated") || lower.includes("invalid token")) {
          setError("Session expired. Please log in again.");
        } else if (m.includes("503") || lower.includes("supabase not configured") || lower.includes("permission denied")) {
          setError("Database not configured. Please contact support or check backend Supabase settings.");
        } else {
          // For 500 or network errors, show message instead of silent redirect
          setError("Could not verify your profile. Please try again.");
        }
      }
    } catch {
      setError("Network error. Please check your connection and try again.");
    } finally {
      setLoading(false);
    }
  };

  const handleForgot = async () => {
    if (!validateEmail(email)) {
      setError("Enter your email above to reset your password.");
      return;
    }
    setError(null);
    setInfo(null);
    const { error: e } = await resetPassword(email.trim());
    if (e) setError(e);
    else {
      setInfo("Password reset email sent. Check your inbox.");
      setShowForgot(false);
    }
  };

  return (
    <div className="auth">
      <div className="auth__card">
        <div className="auth__header">
          <img src="/logo.png" alt="INAURA" className="auth__logo" width={140} height={36} decoding="async" />
          <h1 className="auth__title">Welcome back</h1>
          <p className="auth__subtitle">Log in to continue your INAURA journey.</p>
        </div>

        {!isConfigured && (
          <div className="auth__error" role="alert">
            Supabase not configured. Add <code>VITE_SUPABASE_URL</code> and <code>VITE_SUPABASE_ANON_KEY</code> to <code>frontend/.env</code> (see <code>.env.example</code>).
          </div>
        )}

        <form className="auth__form" onSubmit={handleSubmit} noValidate>
          {error && (
            <div className="auth__error" role="alert">
              {error}
            </div>
          )}
          {info && <div className="auth__success" role="status">{info}</div>}

          <div className="auth__field">
            <label className="auth__label" htmlFor="email">
              Email
            </label>
            <input
              id="email"
              type="email"
              autoComplete="email"
              placeholder="you@college.edu"
              className="auth__input"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>

          <div className="auth__field">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <label className="auth__label" htmlFor="password">
                Password
              </label>
              <button
                type="button"
                onClick={() => setShowForgot((v) => !v)}
                style={{
                  background: "none",
                  border: 0,
                  color: "#4f46e5",
                  fontWeight: 600,
                  fontSize: "0.82rem",
                  cursor: "pointer",
                }}
              >
                Forgot password?
              </button>
            </div>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              placeholder="••••••••"
              className="auth__input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>

          {showForgot && (
            <div className="auth__success">
              <div style={{ fontWeight: 600, marginBottom: 6 }}>Reset password</div>
              <p style={{ margin: 0, fontSize: "0.86rem" }}>We’ll send a reset link to the email above.</p>
              <div style={{ marginTop: 10 }}>
                <Button type="button" variant="secondary" size="sm" onClick={handleForgot}>
                  Send reset link
                </Button>
              </div>
            </div>
          )}

          <div className="auth__actions">
            <Button type="submit" variant="primary" size="lg" disabled={loading}>
              {loading ? "Logging in…" : "Log in"}
            </Button>
          </div>
        </form>

        <div className="auth__divider">or</div>

        <div className="auth__footer">
          Don’t have an account?{" "}
          <Link to="/signup" className="auth__link">
            Sign up
          </Link>
        </div>

        <div className="auth__muted">
          <Link to="/" className="auth__link" style={{ fontWeight: 500 }}>
            ← Back to INAURA
          </Link>
        </div>
      </div>
    </div>
  );
}
