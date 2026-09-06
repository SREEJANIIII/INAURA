import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { supabase } from "../lib/supabase";
import Button from "../components/ui/Button";
import "./Auth.css";

function validateEmail(v: string) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v);
}

export default function Signup() {
  const { signUp, isConfigured } = useAuth();
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setInfo(null);

    if (!isConfigured) {
      setError("Supabase not configured. Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY.");
      return;
    }
    if (!validateEmail(email)) {
      setError("Please enter a valid email address.");
      return;
    }
    if (password.length < 6) {
      setError("Password must be at least 6 characters.");
      return;
    }
    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }

    setLoading(true);
    try {
      const { error: err } = await signUp(email.trim(), password);
      if (err) {
        const m = err.toLowerCase();
        if (m.includes("already registered") || m.includes("already exists") || m.includes("duplicate")) {
          setError("An account with this email already exists. Try logging in.");
        } else {
          setError(err);
        }
        return;
      }
      // Check if session was created (email confirmation may be required)
      try {
        const { data } = supabase ? await supabase.auth.getSession() : { data: { session: null } as unknown as { session: null } };
        if (data.session) {
          setInfo("Account created! Redirecting to profile setup…");
          setTimeout(() => nav("/profile/setup", { replace: true }), 800);
        } else {
          setInfo("Account created. Please check your email to confirm your address, then log in.");
        }
      } catch {
        setInfo("Account created. Please check your email to confirm, then log in.");
      }
    } catch {
      setError("Network error. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth">
      <div className="auth__card">
        <div className="auth__header">
          <img src="/logo.png" alt="INAURA" className="auth__logo" width={140} height={36} decoding="async" />
          <h1 className="auth__title">Create your account</h1>
          <p className="auth__subtitle">Start your INAURA journey — it takes less than a minute.</p>
        </div>

        {!isConfigured && (
          <div className="auth__error" role="alert">
            Supabase not configured. Add <code>VITE_SUPABASE_URL</code> and <code>VITE_SUPABASE_ANON_KEY</code> to <code>frontend/.env</code>.
          </div>
        )}

        <form className="auth__form" onSubmit={handleSubmit} noValidate>
          {error && <div className="auth__error" role="alert">{error}</div>}
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
            <label className="auth__label" htmlFor="password">
              Password
            </label>
            <input
              id="password"
              type="password"
              autoComplete="new-password"
              placeholder="At least 6 characters"
              className="auth__input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>

          <div className="auth__field">
            <label className="auth__label" htmlFor="confirm">
              Confirm Password
            </label>
            <input
              id="confirm"
              type="password"
              autoComplete="new-password"
              placeholder="Repeat password"
              className="auth__input"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              required
            />
          </div>

          <div className="auth__actions">
            <Button type="submit" variant="primary" size="lg" disabled={loading}>
              {loading ? "Creating account…" : "Create account"}
            </Button>
          </div>

          <p className="auth__hint" style={{ textAlign: "center" }}>
            By signing up you agree to our terms. No spam — just your career path.
          </p>
        </form>

        <div className="auth__divider">or</div>

        <div className="auth__footer">
          Already have an account?{" "}
          <Link to="/login" className="auth__link">
            Log in
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
