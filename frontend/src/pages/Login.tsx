import type { CSSProperties } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { getProfile } from "../services/profile";
import { returnPath } from "../lib/authRedirect";
import { statusOf } from "../lib/errors";
import { AuthComponent, type SignUpResult } from "@/components/ui/sign-up";

function validateEmail(v: string) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v);
}

export default function Login() {
  const { signIn, resetPassword, signInWithProvider, isConfigured } = useAuth();
  const nav = useNavigate();
  // Where they were headed before being asked to log in
  const location = useLocation();

  // Signs in, then sends the student to profile setup or their career track
  const handleLogIn = async (email: string, password: string): Promise<SignUpResult> => {
    if (!isConfigured) {
      return { error: "Logging in isn't available right now (Supabase isn't configured)." };
    }
    const { error: authErr } = await signIn(email, password);
    if (authErr) {
      const msg = authErr.toLowerCase();
      if (msg.includes("invalid login credentials") || msg.includes("invalid email or password")) {
        return { error: "Incorrect email or password. Please try again." };
      }
      if (msg.includes("email not confirmed")) {
        return { error: "Please confirm your email before logging in. Check your inbox." };
      }
      return { error: authErr };
    }

    try {
      await getProfile();
      nav(returnPath(location.state), { replace: true });
      return { error: null, message: "Welcome back!" };
    } catch (err) {
      const m = err instanceof Error ? err.message : "";
      const lower = m.toLowerCase();
      if (statusOf(err) === 404 || lower.includes("not found")) {
        nav("/profile/setup", { replace: true });
        return { error: null, message: "Welcome! Let’s set up your profile." };
      }
      if (statusOf(err) === 401 || lower.includes("not authenticated") || lower.includes("invalid token")) {
        return { error: "Your session couldn't be started. Please log in again." };
      }
      if (statusOf(err) === 0) {
        return { error: "You're logged in, but INAURA's server can't be reached right now. Try again in a moment." };
      }
      return { error: "You're logged in, but your profile couldn't be loaded. Please try again." };
    }
  };

  const handleForgot = async (email: string): Promise<SignUpResult> => {
    if (!validateEmail(email)) return { error: "Enter your email first to reset your password." };
    const { error } = await resetPassword(email);
    if (error) return { error };
    return { error: null, message: "Password reset email sent. Check your inbox." };
  };

  return (
    // Same look as the sign-up page (lavender in place of INAURA's navy for the colour field)
    <div className="tw-scope" style={{ "--color-primary": "#8b7cf6" } as CSSProperties}>
      <AuthComponent
        mode="login"
        logo={<img src="/logo.png" alt="INAURA" width={1748} height={899} className="h-16 w-auto sm:h-20" decoding="async" />}
        brandName=""
        title="Welcome back"
        onLogIn={handleLogIn}
        onForgotPassword={handleForgot}
        onSocial={signInWithProvider}
        footer={
          <div className="space-y-2 text-sm text-muted-foreground">
            <p>
              New to INAURA?{" "}
              <Link to="/signup" className="font-semibold text-[#4f46e5] hover:underline">
                Create an account
              </Link>
            </p>
            <p>
              <Link to="/" className="text-[#4f46e5] hover:underline">
                ← Back to INAURA
              </Link>
            </p>
          </div>
        }
      />
    </div>
  );
}
