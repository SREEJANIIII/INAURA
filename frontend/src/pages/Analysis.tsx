import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  listEvidence,
  createEvidence,
  deleteEvidence,
  uploadEvidenceFile,
  listProjects,
  createProject,
  deleteProject,
  listCerts,
  createCert,
  deleteCert,
  type Evidence,
  type Project,
  type Certification,
} from "../services/evidence";
import {
  listRoles,
  getAnalysisState,
  setTargetRole,
  type AnalysisState,
  type RetrieveResponse,
} from "../services/industry";
import { runAnalysis } from "../services/analysis";
import { getProfile } from "../services/profile";
import Button from "../components/ui/Button";
import "./Analysis.css";

type UrlSource = "github" | "leetcode" | "codeforces" | "kaggle" | "linkedin";
const urlSources: { type: UrlSource; label: string; placeholder: string; hint: string }[] = [
  { type: "github", label: "GitHub", placeholder: "https://github.com/username", hint: "Your GitHub profile or username" },
  { type: "leetcode", label: "LeetCode", placeholder: "https://leetcode.com/u/username", hint: "LeetCode username or profile URL" },
  { type: "codeforces", label: "Codeforces", placeholder: "https://codeforces.com/profile/username", hint: "Codeforces handle or URL" },
  { type: "kaggle", label: "Kaggle", placeholder: "https://www.kaggle.com/username", hint: "Kaggle username or URL" },
  { type: "linkedin", label: "LinkedIn", placeholder: "https://www.linkedin.com/in/username", hint: "LinkedIn profile URL" },
];

const fileSources: { type: "resume" | "syllabus"; label: string; desc: string }[] = [
  { type: "resume", label: "Resume", desc: "PDF, DOC or DOCX — your latest resume" },
  { type: "syllabus", label: "College syllabus / coursework", desc: "PDF/DOC — curriculum or key coursework" },
];

export default function Analysis() {
  const navigate = useNavigate();
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [certs, setCerts] = useState<Certification[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);

  // Role & analysis state
  const [roles, setRoles] = useState<string[]>([]);
  const [careerInterests, setCareerInterests] = useState<string[]>([]);
  const [targetRole, setTargetRoleState] = useState<string>("");
  const [customRole, setCustomRole] = useState<string>("");
  const [showCustom, setShowCustom] = useState(false);
  const [analysisState, setAnalysisState] = useState<AnalysisState | null>(null);
  const [retrieval, setRetrieval] = useState<RetrieveResponse | null>(null);
  const [preparing, setPreparing] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);

  // URL inputs
  const [urlInputs, setUrlInputs] = useState<Record<UrlSource, string>>({
    github: "",
    leetcode: "",
    codeforces: "",
    kaggle: "",
    linkedin: "",
  });

  // File inputs
  const [fileErrors, setFileErrors] = useState<Record<string, string | null>>({});

  // Project form
  const [projectForm, setProjectForm] = useState({ name: "", description: "", technologies: "", project_url: "", github_url: "" });
  // Cert form
  const [certForm, setCertForm] = useState({ name: "", issuing_org: "", completion_year: new Date().getFullYear(), certificate_url: "" });

  const loadAll = async () => {
    setLoading(true);
    setError(null);
    try {
      const [ev, pr, ce, rs, st, prof] = await Promise.all([
        listEvidence().catch(() => [] as Evidence[]),
        listProjects().catch(() => [] as Project[]),
        listCerts().catch(() => [] as Certification[]),
        listRoles().catch(() => [] as string[]),
        getAnalysisState().catch(() => null as AnalysisState | null),
        getProfile().catch(() => null),
      ]);
      setEvidence(ev);
      setProjects(pr);
      setCerts(ce);
      setRoles(rs);
      setAnalysisState(st);
      if (st?.target_role) {
        setTargetRoleState(st.target_role);
        if (!rs.includes(st.target_role)) {
          setShowCustom(true);
          setCustomRole(st.target_role);
        }
      } else if (prof?.career_interests?.[0]) {
        // Prefill from profile if no target set
        const first = prof.career_interests[0];
        if (rs.includes(first)) setTargetRoleState(first);
      }
      if (prof?.career_interests) setCareerInterests(prof.career_interests);
      if (st?.last_retrieval) setRetrieval(st.last_retrieval as RetrieveResponse);

      // Prefill url inputs
      const next: Record<UrlSource, string> = { github: "", leetcode: "", codeforces: "", kaggle: "", linkedin: "" };
      ev.forEach((e) => {
        if (urlSources.some((s) => s.type === e.evidence_type) && e.source_url) {
          next[e.evidence_type as UrlSource] = e.source_url;
        }
      });
      setUrlInputs(next);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to load";
      if (msg.includes("401") || msg.toLowerCase().includes("not authenticated")) {
        setError("Session expired. Please log in again.");
      } else if (msg.includes("503") || msg.toLowerCase().includes("permission denied") || msg.toLowerCase().includes("not found")) {
        // For industry/analysis 503, don't block whole page — show inline
        setError(null);
      } else {
        setError("Could not load your evidence. Please refresh.");
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAll();
  }, []);

  const findEvidence = (type: string) => evidence.find((e) => e.evidence_type === type);

  const handleSaveUrl = async (type: UrlSource) => {
    const val = urlInputs[type].trim();
    if (!val) {
      setError(`Please enter a ${type} URL or username.`);
      return;
    }
    if (val.includes(" ")) {
      setError("URL/username must not contain spaces.");
      return;
    }
    setSaving(type);
    setError(null);
    try {
      const existing = findEvidence(type);
      if (existing) await deleteEvidence(existing.id);
      await createEvidence({ evidence_type: type, source_url: val });
      await loadAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(null);
    }
  };

  const handleRemoveUrl = async (type: UrlSource) => {
    const existing = findEvidence(type);
    if (!existing) return;
    setSaving(type);
    try {
      await deleteEvidence(existing.id);
      setUrlInputs((prev) => ({ ...prev, [type]: "" }));
      await loadAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to remove");
    } finally {
      setSaving(null);
    }
  };

  const handleFile = async (type: "resume" | "syllabus" | "certification_file" | "project_doc", file: File | null) => {
    if (!file) return;
    const allowed = ["application/pdf", "application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"];
    const ext = file.name.split(".").pop()?.toLowerCase();
    const allowedExts = ["pdf", "doc", "docx"];
    if (!allowed.includes(file.type) && !allowedExts.includes(ext || "")) {
      setFileErrors((prev) => ({ ...prev, [type]: "Invalid file type. Allowed: PDF, DOC, DOCX" }));
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      setFileErrors((prev) => ({ ...prev, [type]: "File too large. Max 10 MB" }));
      return;
    }
    setFileErrors((prev) => ({ ...prev, [type]: null }));
    setSaving(type);
    try {
      const form = new FormData();
      form.append("evidence_type", type);
      form.append("file", file);
      form.append("title", file.name);
      const existing = findEvidence(type);
      if (existing) await deleteEvidence(existing.id);
      await uploadEvidenceFile(form);
      await loadAll();
    } catch (e) {
      setFileErrors((prev) => ({ ...prev, [type]: e instanceof Error ? e.message : "Upload failed" }));
    } finally {
      setSaving(null);
    }
  };

  const handleRemoveFile = async (type: string) => {
    const existing = findEvidence(type);
    if (!existing) return;
    setSaving(type);
    try {
      await deleteEvidence(existing.id);
      await loadAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to remove");
    } finally {
      setSaving(null);
    }
  };

  const handleAddProject = async () => {
    if (!projectForm.name.trim() || projectForm.name.trim().length < 2) {
      setError("Project name must be at least 2 characters.");
      return;
    }
    if (!projectForm.description.trim() || projectForm.description.trim().length < 10) {
      setError("Project description must be at least 10 characters.");
      return;
    }
    if (!projectForm.technologies.trim()) {
      setError("Please list technologies used.");
      return;
    }
    setSaving("project");
    setError(null);
    try {
      await createProject({
        name: projectForm.name.trim(),
        description: projectForm.description.trim(),
        technologies: projectForm.technologies.split(",").map((s) => s.trim()).filter(Boolean),
        project_url: projectForm.project_url.trim() || null,
        github_url: projectForm.github_url.trim() || null,
      });
      setProjectForm({ name: "", description: "", technologies: "", project_url: "", github_url: "" });
      await loadAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add project");
    } finally {
      setSaving(null);
    }
  };

  const handleAddCert = async () => {
    if (!certForm.name.trim() || certForm.name.trim().length < 2) {
      setError("Certification name required.");
      return;
    }
    if (!certForm.issuing_org.trim()) {
      setError("Issuing organization required.");
      return;
    }
    if (!certForm.completion_year || certForm.completion_year < 2000 || certForm.completion_year > 2035) {
      setError("Enter a valid year between 2000 and 2035.");
      return;
    }
    setSaving("cert");
    setError(null);
    try {
      await createCert({
        name: certForm.name.trim(),
        issuing_org: certForm.issuing_org.trim(),
        completion_year: Number(certForm.completion_year),
        certificate_url: certForm.certificate_url.trim() || null,
      });
      setCertForm({ name: "", issuing_org: "", completion_year: new Date().getFullYear(), certificate_url: "" });
      await loadAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add certification");
    } finally {
      setSaving(null);
    }
  };

  const summary = (() => {
    const present = new Set(evidence.map((e) => e.evidence_type));
    let count = present.size;
    if (projects.length > 0 && !present.has("project_doc")) count += 1;
    if (certs.length > 0 && !present.has("certification_file")) {
      if (!present.has("certification_file")) count += 1;
    }
    count = Math.min(count, 9);
    return { count, present };
  })();

  const handleSelectRole = async (role: string) => {
    if (role === "Other") {
      setShowCustom(true);
      return;
    }
    setShowCustom(false);
    setTargetRoleState(role);
    setError(null);
    try {
      const updated = await setTargetRole(role);
      setAnalysisState(updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to set target role");
    }
  };

  const handleCustomSave = async () => {
    const val = customRole.trim();
    if (!val || val.length < 2) {
      setError("Please enter a career role (at least 2 characters).");
      return;
    }
    setTargetRoleState(val);
    try {
      const updated = await setTargetRole(val);
      setAnalysisState(updated);
      setShowCustom(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to set target role");
    }
  };

  const handleStartAnalysis = async () => {
    const roleToUse = showCustom ? customRole.trim() : targetRole.trim();
    if (!roleToUse) {
      setError("Choose your primary career goal to start analysis.");
      return;
    }
    if (evidence.length === 0 && projects.length === 0 && certs.length === 0) {
      setError("Add at least one evidence source, project or certification to start analysis.");
      return;
    }
    setPreparing(true);
    setError(null);
    setShowConfirm(false);
    try {
      if (!analysisState || analysisState.target_role !== roleToUse) {
        await setTargetRole(roleToUse);
      }
      // Phase 4C: run deterministic skill engine (not just RAG prepare)
      const result = await runAnalysis(roleToUse);
      // Show brief retrieval for continuity if returned, then navigate to results
      const maybeRetrieval = (result as unknown as { retrieval?: RetrieveResponse }).retrieval;
      if (maybeRetrieval) setRetrieval(maybeRetrieval);
      setShowConfirm(true);
      // Navigate to results after short delay for UX
      setTimeout(() => navigate("/analysis/results"), 1200);
      await loadAll();
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to prepare analysis";
      if (msg.toLowerCase().includes("profile not found")) {
        setError("Please complete your profile setup first.");
      } else if (msg.toLowerCase().includes("no evidence")) {
        setError("Add at least one evidence source before starting analysis.");
      } else if (msg.includes("503") || msg.toLowerCase().includes("not configured") || msg.toLowerCase().includes("permission denied")) {
        setError("Analysis tables not configured — run backend/supabase/005_skill_engine.sql and 003/004");
      } else {
        setError(msg);
      }
    } finally {
      setPreparing(false);
    }
  };

  if (loading) {
    return (
      <div className="analysis">
        <div className="container" style={{ padding: "4rem 0", textAlign: "center", color: "#64748b" }}>
          Loading your evidence…
        </div>
      </div>
    );
  }

  return (
    <div className="analysis">
      <header className="analysis__header">
        <div className="container">
          <Link to="/dashboard" className="analysis__back">
            ← Back to Dashboard
          </Link>
          <div className="eyebrow" style={{ marginTop: 12 }}>
            INAURA Analysis Onboarding
          </div>
          <h1 className="analysis__title">Let’s understand where you stand.</h1>
          <p className="analysis__subtitle">
            Add the evidence you already have. INAURA will use it to understand your current skills and build a clearer path toward your goals.
          </p>
          <p className="analysis__hint">You don’t need every source. Add what you have.</p>

          <div className="analysis__principle">
            <strong>Don’t just claim your skills. Show them.</strong>
            <span>INAURA combines multiple forms of evidence instead of relying only on self-declared skills.</span>
          </div>
        </div>
      </header>

      <main className="container analysis__main">
        {error && (
          <div className="analysis__error" role="alert">
            {error}
          </div>
        )}

        {/* Target Role */}
        <section className="analysis__section">
          <h2 className="analysis__section-title">Choose your primary career goal</h2>
          <p className="analysis__section-desc">
            We’ll use your profile’s interests as suggestions, but you can pick any role. This chooses the industry requirements we retrieve — not a proficiency score.
          </p>

          {careerInterests.length > 0 && (
            <div style={{ marginTop: 8, fontSize: "0.84rem", color: "#475569" }}>
              Your interests: <strong>{careerInterests.join(", ")}</strong>
            </div>
          )}

          <div className="analysis__role-grid">
            {roles.map((r) => (
              <button
                key={r}
                type="button"
                className={`analysis__role-chip ${targetRole === r ? "analysis__role-chip--active" : ""}`}
                onClick={() => handleSelectRole(r)}
              >
                {r}
              </button>
            ))}
            <button
              type="button"
              className={`analysis__role-chip ${showCustom ? "analysis__role-chip--active" : ""}`}
              onClick={() => setShowCustom(true)}
            >
              Other career choice
            </button>
          </div>

          {showCustom && (
            <div className="analysis__custom-role">
              <input
                className="analysis__input"
                placeholder="e.g., Product Manager"
                value={customRole}
                onChange={(e) => setCustomRole(e.target.value)}
              />
              <Button variant="secondary" size="sm" onClick={handleCustomSave}>
                Save
              </Button>
              {targetRole && <span style={{ fontSize: "0.84rem", color: "#0f766e", fontWeight: 600 }}>Selected: {targetRole}</span>}
            </div>
          )}

          {!showCustom && targetRole && (
            <div style={{ marginTop: 10, fontSize: "0.86rem", color: "#0f766e", fontWeight: 600 }}>Selected: {targetRole}</div>
          )}

          {analysisState && (
            <div style={{ marginTop: 10, fontSize: "0.82rem", color: "#64748b" }}>
              Status: <strong>{analysisState.status}</strong>
              {analysisState.target_role && <> · Target: {analysisState.target_role}</>}
            </div>
          )}
        </section>

        {/* URL Sources */}
        <section className="analysis__section">
          <h2 className="analysis__section-title">Profile URLs</h2>
          <p className="analysis__section-desc">
            Provide a profile URL or username. We’ll validate and save it — actual fetching happens later.
          </p>
          <div className="analysis__grid">
            {urlSources.map((s) => {
              const existing = findEvidence(s.type);
              const isSaving = saving === s.type;
              return (
                <div key={s.type} className="analysis__card">
                  <div className="analysis__card-head">
                    <h3>{s.label}</h3>
                    {existing ? <span className="analysis__badge">Provided evidence</span> : <span className="analysis__badge analysis__badge--muted">Not added</span>}
                  </div>
                  <p className="analysis__card-hint">{s.hint}</p>
                  <div className="analysis__field">
                    <input
                      className="analysis__input"
                      placeholder={s.placeholder}
                      value={urlInputs[s.type]}
                      onChange={(e) => setUrlInputs((prev) => ({ ...prev, [s.type]: e.target.value }))}
                      disabled={!!existing}
                    />
                  </div>
                  <div className="analysis__card-actions">
                    {existing ? (
                      <>
                        <span className="analysis__saved">✓ {existing.source_url}</span>
                        <Button variant="secondary" size="sm" onClick={() => handleRemoveUrl(s.type)} disabled={isSaving}>
                          Remove
                        </Button>
                      </>
                    ) : (
                      <Button variant="secondary" size="sm" onClick={() => handleSaveUrl(s.type)} disabled={isSaving}>
                        {isSaving ? "Saving…" : "Save"}
                      </Button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </section>

        {/* File Evidence */}
        <section className="analysis__section">
          <h2 className="analysis__section-title">File Evidence</h2>
          <p className="analysis__section-desc">Validate, preview and store via Supabase Storage (private). We don’t parse yet.</p>
          <div className="analysis__grid">
            {fileSources.map((f) => {
              const existing = findEvidence(f.type);
              const isSaving = saving === f.type;
              return (
                <div key={f.type} className="analysis__card">
                  <div className="analysis__card-head">
                    <h3>{f.label}</h3>
                    {existing ? <span className="analysis__badge">Provided evidence</span> : <span className="analysis__badge analysis__badge--muted">Not added</span>}
                  </div>
                  <p className="analysis__card-hint">{f.desc}</p>
                  {existing ? (
                    <div className="analysis__file-saved">
                      <span>✓ {existing.title || existing.file_path}</span>
                      <Button variant="secondary" size="sm" onClick={() => handleRemoveFile(f.type)} disabled={isSaving}>
                        Remove
                      </Button>
                    </div>
                  ) : (
                    <>
                      <label className="analysis__file-label">
                        <input
                          type="file"
                          accept=".pdf,.doc,.docx,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                          onChange={(e) => {
                            const file = e.target.files?.[0] || null;
                            if (file) handleFile(f.type, file);
                            e.target.value = "";
                          }}
                          style={{ display: "none" }}
                        />
                        <span className="analysis__file-btn">{isSaving ? "Uploading…" : "Choose file"}</span>
                        <span className="analysis__file-hint">PDF, DOC, DOCX — max 10 MB</span>
                      </label>
                      {fileErrors[f.type] && <div className="analysis__file-error">{fileErrors[f.type]}</div>}
                    </>
                  )}
                </div>
              );
            })}

            {(["certification_file", "project_doc"] as const).map((t) => {
              const existing = findEvidence(t);
              const label = t === "certification_file" ? "Certification file" : "Project documentation";
              const desc = t === "certification_file" ? "Certificate PDF/DOC" : "Project docs or report";
              const isSaving = saving === t;
              return (
                <div key={t} className="analysis__card">
                  <div className="analysis__card-head">
                    <h3>{label}</h3>
                    {existing ? <span className="analysis__badge">Provided evidence</span> : <span className="analysis__badge analysis__badge--muted">Optional</span>}
                  </div>
                  <p className="analysis__card-hint">{desc}</p>
                  {existing ? (
                    <div className="analysis__file-saved">
                      <span>✓ {existing.title || existing.file_path}</span>
                      <Button variant="secondary" size="sm" onClick={() => handleRemoveFile(t)} disabled={isSaving}>
                        Remove
                      </Button>
                    </div>
                  ) : (
                    <>
                      <label className="analysis__file-label">
                        <input
                          type="file"
                          accept=".pdf,.doc,.docx"
                          onChange={(e) => {
                            const file = e.target.files?.[0] || null;
                            if (file) handleFile(t, file);
                            e.target.value = "";
                          }}
                          style={{ display: "none" }}
                        />
                        <span className="analysis__file-btn">{isSaving ? "Uploading…" : "Choose file"}</span>
                        <span className="analysis__file-hint">PDF, DOC, DOCX — max 10 MB</span>
                      </label>
                      {fileErrors[t] && <div className="analysis__file-error">{fileErrors[t]}</div>}
                    </>
                  )}
                </div>
              );
            })}
          </div>
        </section>

        {/* Projects */}
        <section className="analysis__section">
          <h2 className="analysis__section-title">Projects</h2>
          <p className="analysis__section-desc">Add projects manually — name, description, tech stack, URLs. We don’t analyze yet.</p>

          {projects.length > 0 && (
            <div className="analysis__list">
              {projects.map((p) => (
                <div key={p.id} className="analysis__list-item">
                  <div>
                    <strong>{p.name}</strong>
                    <span>{p.description}</span>
                    <span className="analysis__tech">{p.technologies.join(", ")}</span>
                    {(p.project_url || p.github_url) && (
                      <span>
                        {p.project_url && <a href={p.project_url} target="_blank" rel="noreferrer">Project ↗</a>}
                        {p.github_url && (
                          <>
                            {" · "}
                            <a href={p.github_url} target="_blank" rel="noreferrer">
                              GitHub ↗
                            </a>
                          </>
                        )}
                      </span>
                    )}
                  </div>
                  <Button variant="ghost" size="sm" onClick={async () => { await deleteProject(p.id); await loadAll(); }}>
                    Remove
                  </Button>
                </div>
              ))}
            </div>
          )}

          <div className="analysis__form">
            <div className="analysis__form-grid">
              <input
                className="analysis__input"
                placeholder="Project name"
                value={projectForm.name}
                onChange={(e) => setProjectForm({ ...projectForm, name: e.target.value })}
              />
              <input
                className="analysis__input"
                placeholder="Technologies (comma separated)"
                value={projectForm.technologies}
                onChange={(e) => setProjectForm({ ...projectForm, technologies: e.target.value })}
              />
            </div>
            <textarea
              className="analysis__textarea"
              placeholder="Short description (10-800 chars)"
              value={projectForm.description}
              onChange={(e) => setProjectForm({ ...projectForm, description: e.target.value })}
              rows={3}
            />
            <div className="analysis__form-grid">
              <input
                className="analysis__input"
                placeholder="Project URL (optional)"
                value={projectForm.project_url}
                onChange={(e) => setProjectForm({ ...projectForm, project_url: e.target.value })}
              />
              <input
                className="analysis__input"
                placeholder="GitHub URL (optional)"
                value={projectForm.github_url}
                onChange={(e) => setProjectForm({ ...projectForm, github_url: e.target.value })}
              />
            </div>
            <Button variant="secondary" size="md" onClick={handleAddProject} disabled={saving === "project"}>
              + Add Project
            </Button>
          </div>
        </section>

        {/* Certifications */}
        <section className="analysis__section">
          <h2 className="analysis__section-title">Certifications</h2>
          <p className="analysis__section-desc">Add certifications manually — we don’t verify yet.</p>

          {certs.length > 0 && (
            <div className="analysis__list">
              {certs.map((c) => (
                <div key={c.id} className="analysis__list-item">
                  <div>
                    <strong>{c.name}</strong>
                    <span>
                      {c.issuing_org} · {c.completion_year}
                    </span>
                    {c.certificate_url && (
                      <a href={c.certificate_url} target="_blank" rel="noreferrer">
                        Certificate ↗
                      </a>
                    )}
                  </div>
                  <Button variant="ghost" size="sm" onClick={async () => { await deleteCert(c.id); await loadAll(); }}>
                    Remove
                  </Button>
                </div>
              ))}
            </div>
          )}

          <div className="analysis__form">
            <div className="analysis__form-grid">
              <input
                className="analysis__input"
                placeholder="Certification name"
                value={certForm.name}
                onChange={(e) => setCertForm({ ...certForm, name: e.target.value })}
              />
              <input
                className="analysis__input"
                placeholder="Issuing organization"
                value={certForm.issuing_org}
                onChange={(e) => setCertForm({ ...certForm, issuing_org: e.target.value })}
              />
            </div>
            <div className="analysis__form-grid">
              <input
                className="analysis__input"
                placeholder="Completion year"
                type="number"
                value={certForm.completion_year}
                onChange={(e) => setCertForm({ ...certForm, completion_year: Number(e.target.value) })}
                min={2000}
                max={2035}
              />
              <input
                className="analysis__input"
                placeholder="Certificate URL (optional)"
                value={certForm.certificate_url}
                onChange={(e) => setCertForm({ ...certForm, certificate_url: e.target.value })}
              />
            </div>
            <Button variant="secondary" size="md" onClick={handleAddCert} disabled={saving === "cert"}>
              + Add Certification
            </Button>
          </div>
        </section>

        {/* Summary */}
        <section className="analysis__summary">
          <h2>Your evidence</h2>
          <div className="analysis__summary-grid">
            {[
              { key: "github", label: "GitHub" },
              { key: "leetcode", label: "LeetCode" },
              { key: "codeforces", label: "Codeforces" },
              { key: "kaggle", label: "Kaggle" },
              { key: "linkedin", label: "LinkedIn" },
              { key: "resume", label: "Resume" },
              { key: "syllabus", label: "Syllabus" },
              { key: "projects", label: "Projects" },
              { key: "certifications", label: "Certifications" },
            ].map((item) => {
              let added: boolean;
              if (item.key === "projects") added = projects.length > 0 || !!findEvidence("project_doc");
              else if (item.key === "certifications") added = certs.length > 0 || !!findEvidence("certification_file");
              else if (item.key === "syllabus") added = !!findEvidence("syllabus");
              else if (item.key === "resume") added = !!findEvidence("resume");
              else added = !!findEvidence(item.key);
              return (
                <div key={item.key} className={`analysis__summary-item ${added ? "analysis__summary-item--done" : ""}`}>
                  <span className="analysis__summary-dot">{added ? "✓" : "○"}</span>
                  <span>
                    {item.label} {added ? "added" : "not added"}
                  </span>
                </div>
              );
            })}
          </div>
          <div className="analysis__coverage">Evidence coverage: {summary.count} of 9 sources</div>
          <p className="analysis__coverage-hint">This is only a count — not a readiness percentage.</p>
        </section>

        {/* Start Analysis — now with RAG */}
        <section className="analysis__start">
          <Button variant="primary" size="lg" onClick={handleStartAnalysis} disabled={preparing}>
            {preparing ? "Preparing your INAURA analysis..." : "Start INAURA Analysis"}
          </Button>
          <p className="analysis__start-hint">Validates profile, target role and at least one evidence source, then retrieves industry context. No proficiency yet.</p>

          {preparing && <div style={{ marginTop: 12, color: "#64748b", fontSize: "0.9rem" }}>Preparing your INAURA analysis...</div>}

          {showConfirm && retrieval && (
            <div className="analysis__confirm" role="status">
              <div style={{ fontSize: 28, marginBottom: 8 }}>✓</div>
              <h3>Your evidence is ready.</h3>
              <p>INAURA can now analyze your profile against industry requirements.</p>

              <div className="analysis__retrieval">
                <div className="analysis__retrieval-head">
                  <strong>Target Role: {retrieval.role}</strong>
                  <span>Query: {retrieval.query}</span>
                </div>
                <p style={{ fontSize: "0.84rem", color: "#64748b", marginTop: 6 }}>{retrieval.note}</p>
                <div className="analysis__retrieval-list">
                  {retrieval.items.map((it) => (
                    <div key={it.id} className="analysis__retrieval-item">
                      <div className="analysis__retrieval-title">
                        <strong>{it.skill}</strong>
                        <span className="analysis__retrieval-cat">{it.skill_category}</span>
                      </div>
                      <div className="analysis__retrieval-meta">
                        <span>Importance: {it.importance.toFixed(2)}</span>
                        <span>Demand: {it.demand.toFixed(2)}</span>
                        <span>Interview: {it.interview_relevance.toFixed(2)}</span>
                        <span className="analysis__retrieval-sim">Similarity: {it.similarity.toFixed(3)}</span>
                      </div>
                      {it.description && <p className="analysis__retrieval-desc">{it.description}</p>}
                      <div style={{ fontSize: "0.78rem", color: "#64748b" }}>
                        Source: {it.source}
                        {it.source_url && (
                          <>
                            {" "}
                            — <a href={it.source_url} target="_blank" rel="noreferrer">{it.source_url}</a>
                          </>
                        )}
                        <span style={{ marginLeft: 8, color: "#94a3b8" }}>v: {it.version}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="analysis__placeholder">Analysis engine — next phase will calculate gaps & priorities (still disabled)</div>
              <div style={{ marginTop: 12 }}>
                <Link to="/dashboard" className="analysis__link">
                  Back to Dashboard →
                </Link>
              </div>
            </div>
          )}

          {showConfirm && !retrieval && (
            <div className="analysis__confirm" role="status">
              <div style={{ fontSize: 28, marginBottom: 8 }}>✓</div>
              <h3>Your evidence is ready.</h3>
              <p>INAURA can now analyze your profile against industry requirements.</p>
              <div className="analysis__placeholder">Analysis engine — coming next phase (RAG + scoring disabled)</div>
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
