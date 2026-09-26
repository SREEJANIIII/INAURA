import { useState, type CSSProperties } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { supabase } from "../lib/supabase";
import { AuthComponent, type SignUpResult } from "@/components/ui/sign-up";
import InauraLogo from "../components/layout/InauraLogo";

export default function Signup() {
  const { signUp, signInWithProvider, isConfigured } = useAuth();
  const nav = useNavigate();
  const [searchParams] = useSearchParams();
  const [selectedRole, setSelectedRole] = useState<"student" | "employer">(
    searchParams.get("role") === "employer" ? "employer" : "student"
  );

  // Creates the Supabase account with role metadata; routes correctly per portal
  const handleSignUp = async (email: string, password: string): Promise<SignUpResult> => {
    if (!isConfigured) {
      return { error: "Sign-up isn't available right now (Supabase isn't configured)." };
    }
    const { error } = await signUp(email, password, selectedRole);
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
      if (selectedRole === "employer") {
        setTimeout(() => nav("/employer/dashboard", { replace: true }), 1800);
        return { error: null, message: "Welcome aboard! Taking you to the Employer Portal…" };
      }
      setTimeout(() => nav("/profile/setup", { replace: true }), 1800);
      return { error: null, message: "Welcome aboard! Setting up your profile…" };
    }
    return { error: null, message: "Account created! Check your email to confirm it, then log in." };
  };

  return (
    // Lavender instead of INAURA's navy for this page's main colour: it tints the background
    // blobs and the loading spinner, and navy muddied the colour field
    <div className="tw-scope" style={{ "--color-primary": selectedRole === "employer" ? "#0d9488" : "#8b7cf6" } as CSSProperties}>
      <div style={{ maxWidth: 440, margin: "1rem auto 0", padding: "0 1rem", textAlign: "center" }}>
        <div style={{ display: "inline-flex", background: "rgba(0,0,0,0.06)", borderRadius: 999, padding: 3, gap: 4 }}>
          <button
            type="button"
            style={{
              padding: "5px 14px",
              borderRadius: 999,
              fontSize: "0.8rem",
              fontWeight: 600,
              border: "none",
              cursor: "pointer",
              background: selectedRole === "student" ? "#ffffff" : "transparent",
              color: selectedRole === "student" ? "#0f172a" : "#64748b",
              boxShadow: selectedRole === "student" ? "0 1px 3px rgba(0,0,0,0.1)" : "none",
            }}
            onClick={() => setSelectedRole("student")}
          >
            I am a Student
          </button>
          <button
            type="button"
            style={{
              padding: "5px 14px",
              borderRadius: 999,
              fontSize: "0.8rem",
              fontWeight: 600,
              border: "none",
              cursor: "pointer",
              background: selectedRole === "employer" ? "#0d9488" : "transparent",
              color: selectedRole === "employer" ? "#ffffff" : "#64748b",
              boxShadow: selectedRole === "employer" ? "0 1px 3px rgba(0,0,0,0.15)" : "none",
            }}
            onClick={() => setSelectedRole("employer")}
          >
            I am an Employer / Recruiter
          </button>
        </div>
      </div>

      <AuthComponent
        logo={<InauraLogo alt="INAURA" width={1748} height={899} className="h-16 w-auto sm:h-20" decoding="async" />}
        brandName=""
        title={selectedRole === "employer" ? "Join INAURA for Employers" : "Join INAURA"}
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
