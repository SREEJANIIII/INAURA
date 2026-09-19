import type { CSSProperties } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { supabase } from "../lib/supabase";
import { AuthComponent, type SignUpResult } from "@/components/ui/sign-up";

export default function Signup() {
  const { signUp, signInWithProvider, isConfigured } = useAuth();
  const nav = useNavigate();

  // Creates the Supabase account; the form shows whatever this returns
  const handleSignUp = async (email: string, password: string): Promise<SignUpResult> => {
    if (!isConfigured) {
      return { error: "Sign-up isn't available right now (Supabase isn't configured)." };
    }
    const { error } = await signUp(email, password);
    if (error) {
      const m = error.toLowerCase();
      if (m.includes("already registered") || m.includes("already exists") || m.includes("duplicate")) {
        return { error: "An account with this email already exists. Try logging in." };
      }
      return { error };
    }
    // Signed in straight away only when Supabase doesn't ask for email confirmation
    const session = supabase ? (await supabase.auth.getSession()).data.session : null;
    if (session) {
      setTimeout(() => nav("/profile/setup", { replace: true }), 1800);
      return { error: null, message: "Welcome aboard! Setting up your profile…" };
    }
    return { error: null, message: "Account created! Check your email to confirm it, then log in." };
  };

  return (
    // Lavender instead of INAURA's navy for this page's main colour: it tints the background
    // blobs and the loading spinner, and navy muddied the colour field
    <div className="tw-scope" style={{ "--color-primary": "#8b7cf6" } as CSSProperties}>
      <AuthComponent
        logo={<img src="/logo.png" alt="INAURA" width={1748} height={899} className="h-16 w-auto sm:h-20" decoding="async" />}
        brandName=""
        title="Join INAURA"
        onSignUp={handleSignUp}
        onSocial={signInWithProvider}
        footer={
          <div className="space-y-2 text-sm text-muted-foreground">
            <p>
              Already have an account?{" "}
              <Link to="/login" className="font-semibold text-[#4f46e5] hover:underline">
                Log in
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
