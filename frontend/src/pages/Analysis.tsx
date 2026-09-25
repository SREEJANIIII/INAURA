import { useEffect, useLayoutEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  createEvidence,
  deleteEvidence,
  uploadEvidenceFile,
  createProject,
  deleteProject,
  createCert,
  deleteCert,
  verifyEvidence,
  type Evidence,
  type Project,
  type Certification,
} from "../services/evidence";
import {
  setTargetRole,
  type AnalysisState,
} from "../services/industry";
import { runAnalysis } from "../services/analysis";
import Button from "../components/ui/app-button";
import { evidencePageData, refreshPageData } from "../lib/pageData";

type EvidencePageData = NonNullable<ReturnType<typeof evidencePageData.peek>>;
import NotionIntegrationCard from "../components/integrations/NotionIntegrationCard";
import EvidenceSection from "../components/analysis/EvidenceSection";
import EvidenceLedger, { type LedgerSource } from "../components/analysis/EvidenceLedger";
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
  const [loading, setLoading] = useState(() => !evidencePageData.peek());
  const { hash } = useLocation();
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [verifyingId, setVerifyingId] = useState<string | null>(null);

  // Role & analysis state
  const [roles, setRoles] = useState<string[]>([]);
  const [careerInterests, setCareerInterests] = useState<string[]>([]);
  const [targetRole, setTargetRoleState] = useState<string>("");
  const [customRole, setCustomRole] = useState<string>("");
  const [showCustom, setShowCustom] = useState(false);
  const [analysisState, setAnalysisState] = useState<AnalysisState | null>(null);
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

  const applyData = (data: EvidencePageData) => {
    const { evidence: ev, projects: pr, certs: ce, roles: rs, analysisState: st, profile: prof } = data;
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

    // Prefill url inputs
    const next: Record<UrlSource, string> = { github: "", leetcode: "", codeforces: "", kaggle: "", linkedin: "" };
    ev.forEach((e) => {
      if (urlSources.some((s) => s.type === e.evidence_type) && e.source_url) {
        next[e.evidence_type as UrlSource] = e.source_url;
      }
    });
    setUrlInputs(next);
  };

  const loadAll = async (force = true) => {
    // Only show the full-page loader when there's nothing on screen yet
    if (!evidencePageData.peek()) setLoading(true);
    setError(null);
    try {
      applyData(await evidencePageData.fetch(force));
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

  const roleDone = !!targetRole.trim();
  const evidenceDone = evidence.length > 0 || projects.length > 0 || certs.length > 0;
  const analysisDone = analysisState?.status === "completed";

  // Everything is on this one page, so a source is opened rather than navigated to.
  // They all start shut: the ledger says what's still missing, so the page doesn't need to
  // open one to make the point. Only a #section in the address opens something by itself.
  const named = hash.slice(1);
  const [picked, setPicked] = useState<{ id: string | null } | null>(null);

  // A link straight to a section (from the search, say) opens that one instead
  const [lastNamed, setLastNamed] = useState(named);
  if (named !== lastNamed) {
    setLastNamed(named);
    setPicked(named ? { id: named } : null);
  }

  // Bring a linked section into view once it's open
  useEffect(() => {
    if (named) document.getElementById(named)?.scrollIntoView({ block: "start" });
  }, [named]);

  // Show last-seen data before the first paint, then refresh in the background
  useLayoutEffect(() => {
    const cachedData = evidencePageData.peek();
    if (cachedData) applyData(cachedData);
    loadAll(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- run once when the page opens
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

  const handleVerifyEvidence = async (id: string) => {
    setVerifyingId(id);
    setError(null);
    try {
      await verifyEvidence(id);
      await loadAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Verification failed");
    } finally {
      setVerifyingId(null);
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
      evidencePageData.fetch(true).catch(() => undefined);
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
      evidencePageData.fetch(true).catch(() => undefined);
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
      // Run the authoritative deterministic analysis pipeline.
      await runAnalysis(roleToUse);
      // Dashboard, results and roadmap all depend on the new analysis
      refreshPageData();
      setShowConfirm(true);
      navigate("/analysis/results");
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

  const urlsAdded = urlSources.filter((u) => findEvidence(u.type)).map((u) => u.label);
  const filesAdded = fileSources.filter((f) => findEvidence(f.type)).map((f) => (f.type === "resume" ? "Resume" : "Syllabus"));
  const notionAdded = !!findEvidence("notion");
  const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

  /**
   * Every section of this page, in the order it appears.
   *
   * Your career belongs to Career Track: changing it there re-runs the analysis and rebuilds
   * the roadmap for the new role, which changing it here never did. So this page only offers
   * the choice when nothing has been chosen yet, and otherwise just states what it's using.
   */
  const sections = [
    ...(roleDone
      ? []
      : [
          {
            id: "career-goal",
            title: "Choose your career goal",
            desc: "This decides the industry requirements INAURA compares you against — it isn't a score. Your profile's interests are suggestions; you can pick any role.",
            done: false,
            proves: "Which role everything here is measured against",
            status: "",
          },
        ]),
    {
      id: "profile-urls",
      title: "Profile URLs",
      proves: "Code you've pushed and problems you've solved",
      desc: "Give a profile URL or username and INAURA will check it's real and save it.",
      done: urlsAdded.length > 0,
      status: urlsAdded.join(", "),
    },
    {
      id: "file-evidence",
      title: "Files",
      proves: "Your resume and what your course covered",
      desc: "Stored privately in Supabase Storage. Nothing is read from them yet.",
      done: filesAdded.length > 0,
      status: filesAdded.join(", "),
    },
    {
      id: "notion",
      title: "Notion",
      proves: "Notes and write-ups from your workspace",
      done: notionAdded,
      status: "Connected and synced",
    },
    {
      id: "projects",
      title: "Projects",
      proves: "Things you've built from start to finish",
      desc: "Add what you've built — name, description, tech stack and links.",
      done: projects.length > 0,
      status: plural(projects.length, "project"),
    },
    {
      id: "certifications",
      title: "Certificates",
      proves: "Courses you've seen through to the end",
      desc: "Add courses you've completed. These aren't verified yet.",
      done: certs.length > 0,
      status: plural(certs.length, "certificate"),
    },
  ];

  const open = picked?.id ?? null;

  /** The ten named sources the tally counts, in the same order as the column beside it */
  const ledgerSources: LedgerSource[] = [
    { key: "github", label: "GitHub", present: !!findEvidence("github") },
    { key: "leetcode", label: "LeetCode", present: !!findEvidence("leetcode") },
    { key: "codeforces", label: "Codeforces", present: !!findEvidence("codeforces") },
    { key: "kaggle", label: "Kaggle", present: !!findEvidence("kaggle") },
    { key: "linkedin", label: "LinkedIn", present: !!findEvidence("linkedin") },
    { key: "resume", label: "Resume", present: !!findEvidence("resume") },
    { key: "syllabus", label: "Syllabus", present: !!findEvidence("syllabus") },
    { key: "notion", label: "Notion", present: notionAdded },
    { key: "projects", label: "Projects", present: projects.length > 0 || !!findEvidence("project_doc") },
    { key: "certifications", label: "Certificates", present: certs.length > 0 || !!findEvidence("certification_file") },
  ];

  const lastRun =
    analysisDone && analysisState?.updated_at
      ? new Date(analysisState.updated_at).toLocaleDateString(undefined, { day: "numeric", month: "short" })
      : null;

  const runBlocked = !roleDone
    ? "Choose the role you're aiming for first."
    : !evidenceDone
      ? "Add at least one source and this comes to life."
      : null;

  const sectionProps = (id: string) => {
    const sec = sections.find((x) => x.id === id)!;
    return {
      id,
      title: sec.title,
      proves: sec.proves,
      desc: sec.desc,
      status: sec.status,
      done: sec.done,
      open: open === id,
      onToggle: () => setPicked({ id: open === id ? null : id }),
    };
  };

  if (loading) {
    return (
      <div className="analysis">
        <div className="container" style={{ padding: "4rem 0", textAlign: "center", color: "var(--ev-ink-3)" }}>
          Loading your evidence…
        </div>
      </div>
    );
  }

  return (
    <div className="analysis">
      <header className="analysis__header">
        <div className="container">
          <h1 className="analysis__title">The case for you</h1>
          <p className="analysis__subtitle">
            {roleDone
              ? `Everything here is read against ${targetRole}. INAURA can only argue from what it can see, so the more of your work it has, the sharper it gets.`
              : "INAURA can only argue from what it can see. Add the work you've already done, and it reads that against the role you're aiming for."}
          </p>
        </div>
      </header>

      <main className="container analysis__main">
        {error && (
          <div className="analysis__error" role="alert">
            {error}
          </div>
        )}

        <div className="analysis__layout">
          <div className="analysis__sources">
        {/* Target Role — only until one is set; after that it's changed on Career Track */}
        {!roleDone && (
          <EvidenceSection {...sectionProps("career-goal")}>
            {careerInterests.length > 0 && (
              <div style={{ marginTop: 8, fontSize: "0.84rem", color: "var(--ev-ink-2)" }}>
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
                {targetRole && <span style={{ fontSize: "0.84rem", color: "var(--ev-ok-ink)", fontWeight: 600 }}>Selected: {targetRole}</span>}
              </div>
            )}

            {!showCustom && targetRole && (
              <div style={{ marginTop: 10, fontSize: "0.86rem", color: "var(--ev-ok-ink)", fontWeight: 600 }}>Selected: {targetRole}</div>
            )}

            {analysisState && (
              <div style={{ marginTop: 10, fontSize: "0.82rem", color: "var(--ev-ink-3)" }}>
                Status: <strong>{analysisState.status}</strong>
                {analysisState.target_role && <> · Target: {analysisState.target_role}</>}
              </div>
            )}
          </EvidenceSection>
        )}

        {/* URL Sources */}
        <EvidenceSection {...sectionProps("profile-urls")}>
          <div className="analysis__grid">
            {urlSources.map((s) => {
              const existing = findEvidence(s.type);
              const isSaving = saving === s.type;
              const isVerifying = existing ? verifyingId === existing.id : false;
              const vStatus = existing?.verification_status || "unverified";
              const detectedSkills = (
                (existing?.metadata as Record<string, unknown> | null)?.verified_signals as Array<{ skill?: string; canonical_name?: string }> | undefined
              )?.map((sig) => sig.skill || sig.canonical_name).filter(Boolean) as string[] | undefined;
              const githubInspection = s.type === "github"
                ? ((existing?.metadata as Record<string, unknown> | null)?.inspection as Record<string, unknown> | undefined)
                : undefined;

              let badgeText = "Not added";
              let badgeClass = "analysis__badge--muted";
              if (existing) {
                if (isVerifying) {
                  badgeText = "Verifying…";
                  badgeClass = "analysis__badge--verifying";
                } else if (vStatus === "verified") {
                  const deepStatus = githubInspection?.deep_inspection_status;
                  badgeText = s.type === "github" && deepStatus === "partial" ? "✓ Profile verified · partial inspection" : s.type === "github" && deepStatus === "failed" ? "⚠ Profile verified · inspection unavailable" : "✓ Verified";
                  badgeClass = deepStatus === "failed" ? "analysis__badge--failed" : deepStatus === "partial" ? "analysis__badge--unverified" : "analysis__badge--verified";
                } else if (vStatus === "failed") {
                  badgeText = "⚠ Failed";
                  badgeClass = "analysis__badge--failed";
                } else {
                  badgeText = "Unverified";
                  badgeClass = "analysis__badge--unverified";
                }
              }

              return (
                <div key={s.type} className="analysis__card">
                  <div className="analysis__card-head">
                    <h3>{s.label}</h3>
                    <span className={`analysis__badge ${badgeClass}`}>{badgeText}</span>
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
                  {existing && (
                    <div className="analysis__card-details">
                      {detectedSkills && detectedSkills.length > 0 && (
                        <p className="analysis__verification-details">
                          <strong>Detected:</strong> {detectedSkills.join(", ")}
                        </p>
                      )}
                      {Array.isArray((existing?.metadata as Record<string, unknown> | null)?.facts) &&
                        ((existing?.metadata as Record<string, unknown>).facts as string[]).map((fact, idx) => (
                          <p key={idx} className="analysis__verification-details">
                            • {fact}
                          </p>
                        ))}
                      {existing.verification_message && (
                        <p className="analysis__verification-details">
                          {existing.verification_message}
                        </p>
                      )}
                      {Array.isArray((existing?.metadata as Record<string, unknown> | null)?.warnings) &&
                        ((existing?.metadata as Record<string, unknown>).warnings as string[]).map((warn, idx) => (
                          <p key={`w-${idx}`} className="analysis__verification-details" style={{ color: "var(--ev-warn-ink)" }}>
                            ⚠ {warn}
                          </p>
                        ))}
                      {s.type === "linkedin" && (
                        <p className="analysis__verification-details" style={{ fontStyle: "italic", color: "var(--muted-2)" }}>
                          Used only as supporting/self-reported evidence
                        </p>
                      )}
                    </div>
                  )}
                  <div className="analysis__card-actions">
                    {existing ? (
                      <>
                        <span className="analysis__saved">✓ {existing.source_url}</span>
                        <div style={{ display: "flex", gap: "6px" }}>
                          {vStatus !== "verified" && (
                            <Button
                              variant="secondary"
                              size="sm"
                              onClick={() => handleVerifyEvidence(existing.id)}
                              disabled={isVerifying || isSaving}
                            >
                              {isVerifying ? "Verifying…" : vStatus === "failed" ? "Retry" : "Verify"}
                            </Button>
                          )}
                          <Button variant="ghost" size="sm" onClick={() => handleRemoveUrl(s.type)} disabled={isSaving || isVerifying}>
                            Remove
                          </Button>
                        </div>
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
        </EvidenceSection>

        {/* File Evidence */}
        <EvidenceSection {...sectionProps("file-evidence")}>
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
        </EvidenceSection>

        {/* Notion Integration */}
        <EvidenceSection {...sectionProps("notion")}>
          <NotionIntegrationCard onSyncComplete={() => loadAll(true)} onDisconnectComplete={() => loadAll(true)} />
        </EvidenceSection>

        {/* Projects */}
        <EvidenceSection {...sectionProps("projects")}>
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
        </EvidenceSection>

        {/* Certifications */}
        <EvidenceSection {...sectionProps("certifications")}>
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
        </EvidenceSection>

          </div>

          <EvidenceLedger
            sources={ledgerSources}
            role={roleDone ? targetRole : null}
            lastRun={lastRun}
            running={preparing}
            onRun={handleStartAnalysis}
            blocked={runBlocked}
          />
        </div>

        {showConfirm && (
          <div className="analysis__confirm" role="status">
            <h3>Analysis complete</h3>
            <p>Opening your results.</p>
          </div>
        )}
      </main>
    </div>
  );
}
