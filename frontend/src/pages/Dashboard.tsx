import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { getProfile, type Profile } from "../services/profile";
import Button from "../components/ui/Button";
import "./Dashboard.css";

export default function Dashboard() {
  const { user, signOut } = useAuth();
  const nav = useNavigate();
  const [profile, setProfile] = useState<Profile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getProfile()
      .then(setProfile)
      .catch((e) => {
        const msg = e instanceof Error ? e.message : "Failed to load profile";
        const lower = msg.toLowerCase();
        if (msg.includes("404") || lower.includes("not found")) {
          nav("/profile/setup", { replace: true });
        } else if (msg.includes("401") || lower.includes("not authenticated") || lower.includes("invalid token")) {
          setError("Session expired. Please log in again.");
        } else if (msg.includes("503") || lower.includes("supabase not configured") || lower.includes("permission denied")) {
          setError("Database not configured — profiles table not accessible. Please run the latest SQL in Supabase (see backend/supabase/001_create_profiles.sql).");
        } else {
          setError("Could not load your profile. Please try again.");
        }
      })
      .finally(() => setLoading(false));
  }, [nav]);

  const handleLogout = async () => {
    await signOut();
    nav("/login", { replace: true });
  };

  if (loading) {
    return (
      <div className="dash">
        <div className="container" style={{ padding: "4rem 0", textAlign: "center", color: "#64748b" }}>
          Loading your INAURA workspace…
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="dash">
        <div className="container" style={{ padding: "2rem 0" }}>
          <div style={{ background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 12, padding: 16, maxWidth: 640, margin: "0 auto" }}>
            <div style={{ color: "#dc2626", fontWeight: 700 }}>{error}</div>
            <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
              <Button variant="primary" size="sm" onClick={() => window.location.reload()}>
                Retry
              </Button>
              <Button variant="secondary" size="sm" onClick={handleLogout}>
                Log out
              </Button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  const name = profile?.full_name || user?.email?.split("@")[0] || "there";

  return (
    <div className="dash">
      <header className="dash__header">
        <div className="container dash__header-inner">
          <Link to="/" className="dash__brand" aria-label="INAURA Home">
            <img src="/logo.png" alt="INAURA" width={120} height={30} style={{ height: 28, width: "auto", display: "block" }} />
          </Link>
          <nav className="dash__nav" aria-label="Dashboard">
            <Link to="/profile/setup" className="dash__link">
              Profile
            </Link>
            <button type="button" className="dash__link dash__link--btn" onClick={handleLogout}>
              Logout
            </button>
          </nav>
        </div>
      </header>

      <main className="container dash__main">
        <div className="dash__eyebrow">Dashboard — Early access</div>
        <h1 className="dash__title">Welcome to INAURA, {name}.</h1>
        <p className="dash__subtitle">
          Your profile is ready. Next, complete your INAURA analysis to map your evidence against industry requirements.
        </p>

        <div className="dash__card">
          <div className="dash__card-head">
            <h2 style={{ fontSize: "1.05rem", fontWeight: 700, margin: 0 }}>Next step</h2>
            <span style={{ fontSize: "0.74rem", letterSpacing: "0.08em", textTransform: "uppercase", fontWeight: 700, color: "#64748b" }}>
              Phase 4
            </span>
          </div>
          <p style={{ color: "#475569", fontSize: "0.96rem", lineHeight: 1.6, marginTop: 8 }}>
            Your analysis will use your profile plus future evidence (GitHub, LeetCode, etc.) to generate skill gaps and a personalized roadmap.
            This is currently a placeholder for the next phase.
          </p>
          <div style={{ marginTop: 18 }}>
            <Button variant="primary" size="lg" onClick={() => nav("/analysis")}>
              Complete Your INAURA Analysis
            </Button>
          </div>
          <div style={{ marginTop: 12, fontSize: "0.84rem", color: "#64748b" }}>
            Add your GitHub, LeetCode, resume, projects and more — analysis readiness is next.
          </div>
        </div>

        {profile && (
          <div className="dash__profile">
            <h3 style={{ fontSize: "0.9rem", fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase", color: "#64748b", marginBottom: 10 }}>
              Your profile
            </h3>
            <div className="dash__profile-grid">
              <div>
                <span>College</span>
                <strong>{profile.college}</strong>
              </div>
              <div>
                <span>Degree</span>
                <strong>
                  {profile.degree} — {profile.branch}
                </strong>
              </div>
              <div>
                <span>Year</span>
                <strong>
                  {profile.current_year} · {profile.graduation_year}
                </strong>
              </div>
              <div>
                <span>Hours/week</span>
                <strong>{profile.hours_per_week}h</strong>
              </div>
              <div style={{ gridColumn: "1 / -1" }}>
                <span>Interests</span>
                <strong>{profile.career_interests.join(", ")}</strong>
              </div>
            </div>
            <div style={{ marginTop: 14 }}>
              <Link to="/profile/setup" style={{ color: "#4f46e5", fontWeight: 600, fontSize: "0.9rem" }}>
                Edit profile →
              </Link>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
