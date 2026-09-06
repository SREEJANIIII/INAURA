import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { createProfile, getProfile, type ProfilePayload } from "../services/profile";
import Button from "../components/ui/Button";
import "./Auth.css";

const degrees = ["B.Tech", "B.E.", "B.Sc", "BCA", "M.Tech", "M.Sc", "MCA", "MBA", "Diploma", "Other"];
const branches = [
  "Computer Science",
  "Information Technology",
  "Electronics",
  "Electrical",
  "Mechanical",
  "Civil",
  "AI/ML",
  "Data Science",
  "Other",
];
const years = ["1st Year", "2nd Year", "3rd Year", "Final Year", "Graduate"];
const interestOptions = [
  "Software Engineering",
  "Data Science",
  "AI/ML",
  "Web Development",
  "Mobile Development",
  "DevOps",
  "Cloud",
  "Cybersecurity",
  "Product Management",
  "UI/UX Design",
  "Data Analytics",
  "Blockchain",
];

export default function ProfileSetup() {
  const { user, isConfigured } = useAuth();
  const nav = useNavigate();
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [loading, setLoading] = useState(false);
  const [fetching, setFetching] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const [form, setForm] = useState<ProfilePayload>({
    full_name: "",
    college: "",
    degree: "",
    branch: "",
    current_year: "",
    graduation_year: new Date().getFullYear() + 1,
    career_interests: [],
    hours_per_week: 10,
  });

  // Prefill if profile exists
  useEffect(() => {
    if (!isConfigured) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setFetching(false);
      return;
    }
    getProfile()
      .then((p) => {
        setForm({
          full_name: p.full_name,
          college: p.college,
          degree: p.degree,
          branch: p.branch,
          current_year: p.current_year,
          graduation_year: p.graduation_year,
          career_interests: p.career_interests,
          hours_per_week: p.hours_per_week,
        });
        if (p.profile_completed) {
          // Already completed — allow editing but show indicator
        }
      })
      .catch((e) => {
        const msg = e instanceof Error ? e.message : "";
        const lower = msg.toLowerCase();
        if (msg.includes("404") || lower.includes("not found")) {
          // 404 is expected for new users — keep empty form
        } else if (msg.includes("503") || lower.includes("permission denied") || lower.includes("supabase not configured")) {
          setError("Database not configured — profiles table not accessible. Please run backend/supabase/001_create_profiles.sql in Supabase SQL Editor.");
        } else if (msg.includes("401") || lower.includes("not authenticated")) {
          setError("Session expired. Please log in again.");
        }
        // otherwise ignore and allow fresh setup
      })
      .finally(() => setFetching(false));
  }, [isConfigured]);

  const toggleInterest = (val: string) => {
    setForm((f) => ({
      ...f,
      career_interests: f.career_interests.includes(val)
        ? f.career_interests.filter((x) => x !== val)
        : [...f.career_interests, val].slice(0, 10),
    }));
  };

  const validateStep = (s: number): string | null => {
    if (s === 1) {
      if (!form.full_name.trim() || form.full_name.trim().length < 2) return "Please enter your full name.";
    }
    if (s === 2) {
      if (!form.college.trim()) return "Please enter your college.";
      if (!form.degree) return "Please select your degree.";
      if (!form.branch) return "Please select your branch.";
      if (!form.current_year) return "Please select your current year.";
      if (!form.graduation_year || form.graduation_year < 2000 || form.graduation_year > 2035)
        return "Please enter a valid graduation year.";
    }
    if (s === 3) {
      if (form.career_interests.length === 0) return "Select at least one area of interest.";
      if (!form.hours_per_week || form.hours_per_week < 1 || form.hours_per_week > 80)
        return "Hours per week must be between 1 and 80.";
    }
    return null;
  };

  const next = () => {
    const err = validateStep(step);
    if (err) {
      setError(err);
      return;
    }
    setError(null);
    setStep((s) => (s < 3 ? ((s + 1) as 1 | 2 | 3) : s));
  };

  const back = () => {
    setError(null);
    setStep((s) => (s > 1 ? ((s - 1) as 1 | 2 | 3) : s));
  };

  const submit = async () => {
    const err = validateStep(3);
    if (err) {
      setError(err);
      return;
    }
    if (!isConfigured) {
      setError("Supabase not configured — cannot save profile.");
      return;
    }
    if (!user) {
      setError("Session expired. Please log in again.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await createProfile(form);
      setSuccess(true);
      setTimeout(() => nav("/dashboard", { replace: true }), 1200);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to save profile";
      if (msg.includes("401") || msg.toLowerCase().includes("not authenticated")) {
        setError("Session expired. Please log in again.");
      } else if (msg.includes("503")) {
        setError("Database not configured. Check backend Supabase settings.");
      } else {
        setError("Could not save profile. Please check your connection and try again.");
      }
    } finally {
      setLoading(false);
    }
  };

  if (fetching) {
    return (
      <div className="auth">
        <div className="auth__card auth__card--wide">
          <div style={{ textAlign: "center", color: "#64748b", padding: 24 }}>Loading your profile…</div>
        </div>
      </div>
    );
  }

  if (success) {
    return (
      <div className="auth">
        <div className="auth__card auth__card--wide" style={{ textAlign: "center" }}>
          <div style={{ fontSize: 32, marginBottom: 12 }}>✓</div>
          <h2 style={{ fontSize: "1.5rem", fontWeight: 750 }}>Your INAURA profile is ready.</h2>
          <p style={{ color: "#475569", marginTop: 8 }}>
            We’ll use this to personalize your analysis — evidence, gaps and roadmap come next.
          </p>
          <p style={{ color: "#64748b", fontSize: "0.9rem", marginTop: 12 }}>Redirecting to dashboard…</p>
        </div>
      </div>
    );
  }

  return (
    <div className="auth">
      <div className="auth__card auth__card--wide">
        <div className="auth__header" style={{ textAlign: "left", marginBottom: 16 }}>
          <img src="/logo.png" alt="INAURA" className="auth__logo" style={{ margin: "0 0 14px 0" }} width={120} height={30} />
          <h1 className="auth__title" style={{ fontSize: "1.4rem" }}>
            Set up your INAURA profile
          </h1>
          <p className="auth__subtitle" style={{ textAlign: "left" }}>
            Lightweight setup — helps us personalize your path. External profiles come later.
          </p>
        </div>

        <div className="setup__progress" aria-label="Progress">
          <div className={`setup__step ${step >= 1 ? "setup__step--active" : ""} ${step > 1 ? "setup__step--done" : ""}`}>
            <span className="setup__step-dot">{step > 1 ? "✓" : "1"}</span> Basic
          </div>
          <span className="setup__step-line" />
          <div className={`setup__step ${step >= 2 ? "setup__step--active" : ""} ${step > 2 ? "setup__step--done" : ""}`}>
            <span className="setup__step-dot">{step > 2 ? "✓" : "2"}</span> Academic
          </div>
          <span className="setup__step-line" />
          <div className={`setup__step ${step === 3 ? "setup__step--active" : ""}`}>
            <span className="setup__step-dot">3</span> Career
          </div>
        </div>

        <div style={{ marginBottom: 8, fontSize: "0.82rem", fontWeight: 600, color: "#64748b" }}>
          STEP {step} — {step === 1 ? "Basic Information" : step === 2 ? "Academic Information" : "Career Interests"}
        </div>

        {error && <div className="auth__error" role="alert">{error}</div>}
        {!isConfigured && <div className="auth__error">Supabase not configured — profile will not be saved. Configure backend.</div>}

        {step === 1 && (
          <div className="auth__form">
            <div className="auth__field">
              <label className="auth__label" htmlFor="full_name">
                Full name
              </label>
              <input
                id="full_name"
                className="auth__input"
                placeholder="Aarav Sharma"
                value={form.full_name}
                onChange={(e) => setForm({ ...form, full_name: e.target.value })}
              />
            </div>
            <div className="auth__hint">This is how we’ll greet you on your dashboard.</div>
          </div>
        )}

        {step === 2 && (
          <div className="auth__form">
            <div className="auth__field">
              <label className="auth__label" htmlFor="college">
                College / Institution
              </label>
              <input
                id="college"
                className="auth__input"
                placeholder="e.g., IIIT Hyderabad"
                value={form.college}
                onChange={(e) => setForm({ ...form, college: e.target.value })}
              />
            </div>

            <div className="setup__grid">
              <div className="auth__field">
                <label className="auth__label">Degree</label>
                <select
                  className="auth__select"
                  value={form.degree}
                  onChange={(e) => setForm({ ...form, degree: e.target.value })}
                >
                  <option value="">Select degree</option>
                  {degrees.map((d) => (
                    <option key={d} value={d}>
                      {d}
                    </option>
                  ))}
                </select>
              </div>

              <div className="auth__field">
                <label className="auth__label">Branch / Specialization</label>
                <select
                  className="auth__select"
                  value={form.branch}
                  onChange={(e) => setForm({ ...form, branch: e.target.value })}
                >
                  <option value="">Select branch</option>
                  {branches.map((b) => (
                    <option key={b} value={b}>
                      {b}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="setup__grid">
              <div className="auth__field">
                <label className="auth__label">Current year</label>
                <select
                  className="auth__select"
                  value={form.current_year}
                  onChange={(e) => setForm({ ...form, current_year: e.target.value })}
                >
                  <option value="">Select year</option>
                  {years.map((y) => (
                    <option key={y} value={y}>
                      {y}
                    </option>
                  ))}
                </select>
              </div>

              <div className="auth__field">
                <label className="auth__label" htmlFor="grad_year">
                  Graduation year
                </label>
                <input
                  id="grad_year"
                  type="number"
                  className="auth__input"
                  placeholder="2026"
                  value={form.graduation_year}
                  onChange={(e) => setForm({ ...form, graduation_year: Number(e.target.value) })}
                  min={2000}
                  max={2035}
                />
              </div>
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="auth__form">
            <div className="auth__field">
              <label className="auth__label">Areas of interest</label>
              <div className="setup__chips" role="group" aria-label="Career interests">
                {interestOptions.map((opt) => (
                  <button
                    key={opt}
                    type="button"
                    className={`setup__chip ${form.career_interests.includes(opt) ? "setup__chip--active" : ""}`}
                    onClick={() => toggleInterest(opt)}
                    aria-pressed={form.career_interests.includes(opt)}
                  >
                    {opt}
                  </button>
                ))}
              </div>
              <div className="auth__hint">Select up to 10. You can change these later.</div>
              {form.career_interests.length > 0 && (
                <div style={{ fontSize: "0.84rem", color: "#475569", marginTop: 4 }}>
                  Selected: {form.career_interests.join(", ")}
                </div>
              )}
            </div>

            <div className="auth__field">
              <label className="auth__label" htmlFor="hours">
                Hours available per week
              </label>
              <input
                id="hours"
                type="number"
                className="auth__input"
                value={form.hours_per_week}
                onChange={(e) => setForm({ ...form, hours_per_week: Number(e.target.value) })}
                min={1}
                max={80}
              />
              <div className="auth__hint">For planning your roadmap — be realistic.</div>
            </div>

            <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 12, padding: 12 }}>
              <div style={{ fontSize: "0.86rem", fontWeight: 600, color: "#0f172a" }}>What’s next?</div>
              <p style={{ fontSize: "0.86rem", color: "#475569", margin: "4px 0 0" }}>
                External evidence (GitHub, LeetCode, LinkedIn, Resume, etc.) will be collected later in the INAURA analysis flow — not here.
              </p>
            </div>
          </div>
        )}

        <div className="setup__nav" style={{ marginTop: 20 }}>
          {step > 1 ? (
            <Button type="button" variant="secondary" size="md" onClick={back} disabled={loading}>
              Back
            </Button>
          ) : (
            <span />
          )}

          {step < 3 ? (
            <Button type="button" variant="primary" size="md" onClick={next}>
              Continue
            </Button>
          ) : (
            <Button type="button" variant="primary" size="md" onClick={submit} disabled={loading}>
              {loading ? "Saving…" : "Complete Setup"}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
