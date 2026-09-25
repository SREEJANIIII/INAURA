import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { updateProfile, type Profile as ProfileData, type ProfilePayload } from "../services/profile";
import { evidencePageData, profileData, refreshPageData } from "../lib/pageData";
import { branches, degrees, interestOptions, years } from "../lib/profileOptions";
import Button from "../components/ui/app-button";
import NotionIntegrationCard from "../components/integrations/NotionIntegrationCard";
import "./Profile.css";

type Status = "loading" | "ready" | "missing" | "error";

const toForm = (p: ProfileData): ProfilePayload => ({
  full_name: p.full_name,
  college: p.college,
  degree: p.degree,
  branch: p.branch,
  current_year: p.current_year,
  graduation_year: p.graduation_year,
  career_interests: p.career_interests,
  hours_per_week: p.hours_per_week,
  preferred_work_location: p.preferred_work_location ?? "",
});

const initials = (name: string) =>
  name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("") || "?";

function validate(form: ProfilePayload): string | null {
  if (form.full_name.trim().length < 2) return "Please enter your full name.";
  if (form.college.trim().length < 2) return "Please enter your college.";
  if (!form.degree) return "Please select your degree.";
  if (!form.branch) return "Please select your branch.";
  if (!form.current_year) return "Please select your current year.";
  if (!form.graduation_year || form.graduation_year < 2000 || form.graduation_year > 2035)
    return "Graduation year must be between 2000 and 2035.";
  if (form.career_interests.length === 0) return "Select at least one area of interest.";
  if (!form.hours_per_week || form.hours_per_week < 1 || form.hours_per_week > 80)
    return "Hours per week must be between 1 and 80.";
  return null;
}

// Keeps a saved value selectable even if it isn't in the standard list
const withCurrent = (options: string[], current: string) =>
  current && !options.includes(current) ? [current, ...options] : options;

export default function Profile() {
  const { user } = useAuth();
  const [profile, setProfile] = useState<ProfileData | null>(() => profileData.peek() ?? null);
  const [status, setStatus] = useState<Status>(() => (profileData.peek() ? "ready" : "loading"));
  const [loadError, setLoadError] = useState<string | null>(null);
  const [evidence, setEvidence] = useState(() => evidencePageData.peek() ?? null);

  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<ProfilePayload | null>(null);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [savedNotice, setSavedNotice] = useState(false);

  useEffect(() => {
    profileData
      .fetch()
      .then((p) => {
        setProfile(p);
        setStatus("ready");
      })
      .catch((e) => {
        if (profileData.peek()) return; // keep showing the last-seen profile
        const msg = e instanceof Error ? e.message : "";
        const lower = msg.toLowerCase();
        if (msg.includes("404") || lower.includes("not found")) {
          setStatus("missing");
        } else {
          setLoadError(
            msg.includes("401") || lower.includes("not authenticated")
              ? "Session expired. Please log in again."
              : "Could not load your profile. Please try again."
          );
          setStatus("error");
        }
      });
    evidencePageData
      .fetch()
      .then(setEvidence)
      .catch(() => undefined);
  }, []);

  const startEditing = () => {
    if (!profile) return;
    setForm(toForm(profile));
    setFormError(null);
    setSavedNotice(false);
    setEditing(true);
  };

  const cancelEditing = () => {
    setEditing(false);
    setForm(null);
    setFormError(null);
  };

  const update = <K extends keyof ProfilePayload>(key: K, value: ProfilePayload[K]) =>
    setForm((f) => (f ? { ...f, [key]: value } : f));

  const toggleInterest = (value: string) =>
    setForm((f) =>
      f
        ? {
            ...f,
            career_interests: f.career_interests.includes(value)
              ? f.career_interests.filter((x) => x !== value)
              : [...f.career_interests, value].slice(0, 10),
          }
        : f
    );

  const save = async () => {
    if (!form) return;
    const err = validate(form);
    if (err) {
      setFormError(err);
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      const updated = await updateProfile({ ...form, full_name: form.full_name.trim(), college: form.college.trim() });
      setProfile(updated);
      setEditing(false);
      setForm(null);
      setSavedNotice(true);
      // Dashboard, Evidence and Roadmap all show profile details
      refreshPageData();
    } catch (e) {
      const msg = e instanceof Error ? e.message : "";
      setFormError(
        msg.includes("401")
          ? "Session expired. Please log in again."
          : "Could not save your changes. Please check your connection and try again."
      );
    } finally {
      setSaving(false);
    }
  };

  if (status === "loading") {
    return (
      <div className="prof">
        <div className="container prof__main">
          <div className="prof__hero prof__hero--skeleton" aria-busy="true">
            <div className="prof__avatar prof__skeleton" />
            <div style={{ flex: 1 }}>
              <div className="prof__skeleton" style={{ height: 22, width: "50%" }} />
              <div className="prof__skeleton" style={{ height: 14, width: "70%", marginTop: 10 }} />
            </div>
          </div>
          <p className="prof__muted" style={{ marginTop: 16 }}>Loading your profile…</p>
        </div>
      </div>
    );
  }

  if (status === "missing") {
    return (
      <div className="prof">
        <div className="container prof__main">
          <div className="prof__card prof__empty">
            <h1 className="prof__empty-title">You haven’t set up your profile yet</h1>
            <p className="prof__muted">It takes about a minute and helps INAURA personalise your analysis and roadmap.</p>
            <Link to="/profile/setup">
              <Button variant="primary" size="md">Set up profile</Button>
            </Link>
          </div>
        </div>
      </div>
    );
  }

  if (status === "error" || !profile) {
    return (
      <div className="prof">
        <div className="container prof__main">
          <div className="prof__alert" role="alert">
            {loadError ?? "Could not load your profile."}
            <Button variant="secondary" size="sm" onClick={() => window.location.reload()}>
              Retry
            </Button>
          </div>
        </div>
      </div>
    );
  }

  const memberSince = new Date(profile.created_at).toLocaleDateString(undefined, { month: "long", year: "numeric" });
  const targetRole = evidence?.analysisState?.target_role;
  const stats = [
    { label: "Evidence sources", value: evidence ? String(evidence.evidence.length) : "—", to: "/analysis#profile-urls" },
    { label: "Projects", value: evidence ? String(evidence.projects.length) : "—", to: "/analysis#projects" },
    { label: "Certificates", value: evidence ? String(evidence.certs.length) : "—", to: "/analysis#certifications" },
  ];

  return (
    <div className="prof">
      <div className="container prof__main">
        {/* Identity */}
        <section className="prof__hero">
          <div className="prof__avatar" aria-hidden="true">
            {initials(profile.full_name)}
          </div>
          <div className="prof__identity">
            <h1 className="prof__name">{profile.full_name}</h1>
            <p className="prof__tagline">
              {profile.degree} · {profile.branch}
            </p>
            <p className="prof__muted prof__meta">
              {user?.email && <span>{user.email}</span>}
              <span>Member since {memberSince}</span>
            </p>
          </div>
          {!editing && (
            <Button variant="secondary" size="sm" className="prof__edit" onClick={startEditing}>
              Edit profile
            </Button>
          )}
        </section>

        {savedNotice && !editing && (
          <div className="prof__notice" role="status">
            Your profile has been updated.
          </div>
        )}

        {/* Progress snapshot */}
        {!editing && (
          <section className="prof__stats" aria-label="Your progress">
            <div className="prof__stat prof__stat--goal">
              <span className="prof__label">Career goal</span>
              <strong>{targetRole || "Not chosen yet"}</strong>
              <Link to="/analysis#career-goal" className="prof__stat-link">
                {targetRole ? "Change" : "Choose"} →
              </Link>
            </div>
            {stats.map((s) => (
              <Link key={s.label} to={s.to} className="prof__stat">
                <span className="prof__label">{s.label}</span>
                <strong className="prof__stat-num">{s.value}</strong>
              </Link>
            ))}
          </section>
        )}

        {editing && form ? (
          <div className="prof__grid">
            <section className="prof__card">
              <h2 className="prof__card-title">Personal</h2>
              <label className="prof__field">
                <span className="prof__label">Full name</span>
                <input
                  className="prof__input"
                  value={form.full_name}
                  onChange={(e) => update("full_name", e.target.value)}
                  maxLength={100}
                  autoComplete="name"
                />
              </label>
            </section>

            <section className="prof__card">
              <h2 className="prof__card-title">Academics</h2>
              <label className="prof__field">
                <span className="prof__label">College</span>
                <input
                  className="prof__input"
                  value={form.college}
                  onChange={(e) => update("college", e.target.value)}
                  maxLength={150}
                />
              </label>
              <div className="prof__row">
                <label className="prof__field">
                  <span className="prof__label">Degree</span>
                  <select className="prof__input" value={form.degree} onChange={(e) => update("degree", e.target.value)}>
                    <option value="">Select</option>
                    {withCurrent(degrees, form.degree).map((d) => (
                      <option key={d}>{d}</option>
                    ))}
                  </select>
                </label>
                <label className="prof__field">
                  <span className="prof__label">Branch</span>
                  <select className="prof__input" value={form.branch} onChange={(e) => update("branch", e.target.value)}>
                    <option value="">Select</option>
                    {withCurrent(branches, form.branch).map((b) => (
                      <option key={b}>{b}</option>
                    ))}
                  </select>
                </label>
              </div>
              <div className="prof__row">
                <label className="prof__field">
                  <span className="prof__label">Current year</span>
                  <select
                    className="prof__input"
                    value={form.current_year}
                    onChange={(e) => update("current_year", e.target.value)}
                  >
                    <option value="">Select</option>
                    {withCurrent(years, form.current_year).map((y) => (
                      <option key={y}>{y}</option>
                    ))}
                  </select>
                </label>
                <label className="prof__field">
                  <span className="prof__label">Graduation year</span>
                  <input
                    className="prof__input"
                    type="number"
                    inputMode="numeric"
                    min={2000}
                    max={2035}
                    value={form.graduation_year || ""}
                    onChange={(e) => update("graduation_year", Number(e.target.value))}
                  />
                </label>
              </div>
            </section>

            <section className="prof__card prof__card--full">
              <h2 className="prof__card-title">Career</h2>
              <div className="prof__field">
                <span className="prof__label">Areas of interest</span>
                <div className="prof__chips">
                  {[...interestOptions, ...form.career_interests.filter((i) => !interestOptions.includes(i))]
                    .map((opt) => {
                      const on = form.career_interests.includes(opt);
                      return (
                        <button
                          key={opt}
                          type="button"
                          className={`prof__chip prof__chip--toggle${on ? " is-on" : ""}`}
                          aria-pressed={on}
                          onClick={() => toggleInterest(opt)}
                        >
                          {opt}
                        </button>
                      );
                    })}
                </div>
              </div>
              <label className="prof__field prof__field--narrow">
                <span className="prof__label">Hours you can study per week</span>
                <input
                  className="prof__input"
                  type="number"
                  inputMode="numeric"
                  min={1}
                  max={80}
                  value={form.hours_per_week || ""}
                  onChange={(e) => update("hours_per_week", Number(e.target.value))}
                />
              </label>
              <label className="prof__field">
                <span className="prof__label">Preferred Work Location (optional)</span>
                <input className="prof__input" list="preferred-work-locations-edit" maxLength={160} value={form.preferred_work_location ?? ""} onChange={(e) => update("preferred_work_location", e.target.value)} placeholder="e.g. Bengaluru, Karnataka, India" />
                <datalist id="preferred-work-locations-edit"><option value="Bengaluru, Karnataka, India" /><option value="Hyderabad, Telangana, India" /><option value="Mumbai, Maharashtra, India" /><option value="Delhi NCR, India" /><option value="Pune, Maharashtra, India" /><option value="Chennai, Tamil Nadu, India" /><option value="Remote" /><option value="Anywhere in India" /><option value="Other" /></datalist>
                <span className="prof__muted">Used to tailor industry demand and role requirements to where you want to work.</span>
              </label>
            </section>

            {formError && (
              <div className="prof__alert prof__card--full" role="alert">
                {formError}
              </div>
            )}

            <div className="prof__actions prof__card--full">
              <Button variant="secondary" size="md" onClick={cancelEditing} disabled={saving}>
                Cancel
              </Button>
              <Button variant="primary" size="md" onClick={save} disabled={saving}>
                {saving ? "Saving…" : "Save changes"}
              </Button>
            </div>
          </div>
        ) : (
          <>
            <div className="prof__grid">
            <section className="prof__card">
              <h2 className="prof__card-title">Academics</h2>
              <dl className="prof__list">
                <div>
                  <dt>College</dt>
                  <dd>{profile.college}</dd>
                </div>
                <div>
                  <dt>Degree</dt>
                  <dd>{profile.degree}</dd>
                </div>
                <div>
                  <dt>Branch</dt>
                  <dd>{profile.branch}</dd>
                </div>
                <div>
                  <dt>Current year</dt>
                  <dd>{profile.current_year}</dd>
                </div>
                <div>
                  <dt>Graduating</dt>
                  <dd>{profile.graduation_year}</dd>
                </div>
              </dl>
            </section>

            <section className="prof__card">
              <h2 className="prof__card-title">Career</h2>
              <span className="prof__label">Areas of interest</span>
              <div className="prof__chips">
                {profile.career_interests.map((i) => (
                  <span key={i} className="prof__chip">
                    {i}
                  </span>
                ))}
              </div>
              <div className="prof__hours">
                <strong>{profile.hours_per_week}</strong>
                <span>hours a week for learning — your roadmap is paced to this.</span>
              </div>
              <div style={{ marginTop: 14 }}><span className="prof__label">Preferred work location</span><strong>{profile.preferred_work_location || "Not specified"}</strong></div>
            </section>
          </div>

            <section className="prof__card prof__card--full" style={{ padding: "20px 24px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "14px", flexWrap: "wrap", gap: "8px" }}>
                <div>
                  <h2 className="prof__card-title" style={{ margin: 0 }}>Connected Integrations</h2>
                  <p className="prof__muted" style={{ margin: "4px 0 0", fontSize: "0.85rem" }}>
                    Connect external workspaces to provide additional evidence of your learning and skills.
                  </p>
                </div>
                <Link to="/analysis#notion" style={{ fontSize: "0.82rem", color: "var(--accent)", textDecoration: "none", fontWeight: 600 }}>
                  Open in Evidence view →
                </Link>
              </div>
              <NotionIntegrationCard />
            </section>
          </>
        )}
      </div>
    </div>
  );
}
