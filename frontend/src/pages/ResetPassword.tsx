import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { HOME } from "../lib/authRedirect";
import Button from "../components/ui/app-button";
import "./Auth.css";

const MIN_LENGTH = 6;

/**
 * Where the "reset your password" email lands.
 *
 * The link in that email signs the student in for this one purpose, so by the time this page
 * renders there's a session to set the new password on. Without one, the link has expired or
 * was already used, and the only useful thing to offer is a fresh one.
 */
export default function ResetPassword() {
  const { user, loading, updatePassword } = useAuth();
  const nav = useNavigate();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [show, setShow] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (password.length < MIN_LENGTH) {
      setError(`Use at least ${MIN_LENGTH} characters.`);
      return;
    }
    if (password !== confirm) {
      setError("The two passwords don’t match.");
      return;
    }
    setSaving(true);
    setError(null);
    const { error: failed } = await updatePassword(password);
    setSaving(false);
    if (failed) {
      const lower = failed.toLowerCase();
      setError(
        lower.includes("different from the old")
          ? "Choose a password you haven’t used for INAURA before."
          : lower.includes("session") || lower.includes("jwt")
            ? "This reset link has expired. Ask for a new one from the login page."
            : "Your password couldn’t be changed. Try again in a moment."
      );
      return;
    }
    setDone(true);
    window.setTimeout(() => nav(HOME, { replace: true }), 1500);
  };

  return (
    <div className="auth">
      <div className="auth__card">
        <div className="auth__header">
          <img src="/logo.png" alt="INAURA" className="auth__logo" width={120} height={30} />
          <h1 className="auth__title">{done ? "Password changed" : "Choose a new password"}</h1>
          {!done && user?.email && <p className="auth__subtitle">For {user.email}</p>}
        </div>

        {loading ? (
          <p className="auth__muted" role="status">Checking your reset link…</p>
        ) : done ? (
          <div className="auth__success" role="status">Your new password is saved. Taking you to your Career Track…</div>
        ) : !user ? (
          <div className="auth__form">
            <div className="auth__error" role="alert">
              This reset link has expired or has already been used.
            </div>
            <p className="auth__hint">On the login page, enter your email and choose “Forgot password?” to get a new link.</p>
            <div className="auth__actions">
              <Button asChild variant="primary" size="md">
                <Link to="/login">Back to log in</Link>
              </Button>
            </div>
          </div>
        ) : (
          <form className="auth__form" onSubmit={submit} noValidate>
            <div className="auth__field">
              <label className="auth__label" htmlFor="new-password">New password</label>
              <input
                id="new-password"
                className="auth__input"
                type={show ? "text" : "password"}
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                minLength={MIN_LENGTH}
                required
                autoFocus
              />
            </div>
            <div className="auth__field">
              <label className="auth__label" htmlFor="confirm-password">Type it again</label>
              <input
                id="confirm-password"
                className="auth__input"
                type={show ? "text" : "password"}
                autoComplete="new-password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                required
              />
            </div>
            <label className="auth__hint" style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <input type="checkbox" checked={show} onChange={(e) => setShow(e.target.checked)} />
              Show passwords
            </label>
            {error && <div className="auth__error" role="alert">{error}</div>}
            <div className="auth__actions">
              <Button type="submit" variant="primary" size="md" disabled={saving}>
                {saving ? "Saving…" : "Save new password"}
              </Button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
