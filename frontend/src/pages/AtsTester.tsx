import React, { useState, useEffect, useRef } from "react";
import {
  getAtsRoles,
  getExistingResumes,
  testResumeAts,
  type AtsRoleOption,
  type ExistingResumeOption,
  type AtsTestResponse,
} from "../services/resume";
import "./AtsTester.css";

const POPULAR_ROLES = [
  "Software Engineer",
  "Backend Developer",
  "Frontend Developer",
  "Full Stack Developer",
  "Data Analyst",
  "Machine Learning Engineer",
  "DevOps Engineer",
];

export default function AtsTester() {
  // State: Role Selection
  const [roles, setRoles] = useState<AtsRoleOption[]>([]);
  const [selectedRole, setSelectedRole] = useState<string>("Software Engineer");
  const [customRole, setCustomRole] = useState<string>("");
  const [isCustomRole, setIsCustomRole] = useState<boolean>(false);

  // State: Job Description
  const [showJdInput, setShowJdInput] = useState<boolean>(false);
  const [jobDescription, setJobDescription] = useState<string>("");

  // State: Resume File
  const [uploadMode, setUploadMode] = useState<"upload" | "existing">("upload");
  const [file, setFile] = useState<File | null>(null);
  const [isDragOver, setIsDragOver] = useState<boolean>(false);
  const [existingResumes, setExistingResumes] = useState<ExistingResumeOption[]>([]);
  const [selectedEvidenceId, setSelectedEvidenceId] = useState<string | null>(null);

  // State: Execution & Results
  const [loading, setLoading] = useState<boolean>(false);
  const [loadingStep, setLoadingStep] = useState<string>("Analyzing document...");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AtsTestResponse | null>(null);
  const [activeTab, setActiveTab] = useState<"skills" | "audit" | "verbs" | "rewrites" | "parser">("skills");
  const [copied, setCopied] = useState<boolean>(false);

  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const resultsRef = useRef<HTMLDivElement | null>(null);

  // Load initial data
  useEffect(() => {
    getAtsRoles()
      .then((res) => {
        if (res && res.length > 0) setRoles(res);
      })
      .catch(() => {
        // Fallback silently
      });

    getExistingResumes()
      .then((res) => {
        if (res && res.length > 0) {
          const docxOnly = res.filter((r) => (r.filename || r.title || "").toLowerCase().endsWith(".docx"));
          setExistingResumes(docxOnly);
          if (docxOnly.length > 0) {
            setSelectedEvidenceId(docxOnly[0].id);
          }
        }
      })
      .catch(() => {
        // Fallback silently
      });
  }, []);

  // File Handling
  const handleFileDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      validateAndSetFile(e.dataTransfer.files[0]);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      validateAndSetFile(e.target.files[0]);
    }
  };

  const validateAndSetFile = (f: File) => {
    const ext = f.name.split(".").pop()?.toLowerCase();
    if (ext !== "docx") {
      setError("Only Microsoft Word (.docx) files are supported for ATS testing. Please upload a .docx resume.");
      return;
    }
    if (f.size > 10 * 1024 * 1024) {
      setError("File size exceeds 10 MB limit.");
      return;
    }
    setError(null);
    setFile(f);
  };

  const handleRoleSelect = (roleName: string) => {
    setIsCustomRole(false);
    setSelectedRole(roleName);
  };

  const effectiveRole = isCustomRole ? customRole.trim() || "Software Engineer" : selectedRole;

  // Run ATS Test
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (uploadMode === "upload" && !file) {
      setError("Please select or drop a resume file to test.");
      return;
    }

    if (uploadMode === "existing" && !selectedEvidenceId) {
      setError("Please select one of your uploaded resumes.");
      return;
    }

    setLoading(true);
    setLoadingStep("Extracting text and document structure...");

    try {
      const formData = new FormData();
      formData.append("target_role", effectiveRole);

      if (jobDescription.trim()) {
        formData.append("job_description", jobDescription.trim());
      }

      if (uploadMode === "upload" && file) {
        formData.append("file", file);
      } else if (uploadMode === "existing" && selectedEvidenceId) {
        formData.append("evidence_id", selectedEvidenceId);
      }

      const timer1 = setTimeout(() => setLoadingStep("Matching role keywords & technical skills..."), 900);
      const timer2 = setTimeout(() => setLoadingStep("Evaluating impact metrics & ATS formatting..."), 1800);

      const res = await testResumeAts(formData);

      clearTimeout(timer1);
      clearTimeout(timer2);

      setResult(res);
      setTimeout(() => {
        resultsRef.current?.scrollIntoView({ behavior: "smooth" });
      }, 100);
    } catch (err: any) {
      setError(err?.message || "Failed to analyze resume. Please verify the document format.");
    } finally {
      setLoading(false);
    }
  };

  // Score Color Helper
  const getScoreColor = (score: number) => {
    if (score >= 85) return "#059669"; // Emerald
    if (score >= 70) return "#2563eb"; // Blue
    if (score >= 50) return "#d97706"; // Amber
    return "#e11d48"; // Rose
  };

  const getScoreBg = (score: number) => {
    if (score >= 85) return "rgba(5, 150, 105, 0.12)";
    if (score >= 70) return "rgba(37, 99, 235, 0.12)";
    if (score >= 50) return "rgba(217, 119, 6, 0.12)";
    return "rgba(225, 29, 72, 0.12)";
  };

  const handleCopyReport = () => {
    if (!result) return;
    const reportText = `INAURA ATS Resume Score: ${result.scores.overall}/100 (${result.grade})
Target Role: ${result.target_role}
Status: ${result.verdict}

Score Breakdown:
- Keywords & Skills Match: ${result.scores.skills_match}%
- Impact & Metrics Strength: ${result.scores.impact_metrics}%
- Section Completeness: ${result.scores.sections_structure}%
- Formatting & Parseability: ${result.scores.formatting_parseability}%

Matched Skills (${result.matched_skills.length}): ${result.matched_skills.map((s) => s.skill).join(", ")}
Missing Critical Skills (${result.missing_skills.length}): ${result.missing_skills.map((s) => s.skill).join(", ")}

Key Recommendations:
${result.recommendations.map((r, i) => `${i + 1}. [${r.priority.toUpperCase()}] ${r.title}: ${r.description}`).join("\n")}`;

    navigator.clipboard.writeText(reportText);
    setCopied(true);
    setTimeout(() => setCopied(false), 2500);
  };

  return (
    <div className="ats-page">
      {/* Page Header */}
      <div className="ats-header">
        <div className="ats-badge-tag">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
            <path d="m9 15 2 2 4-4" />
          </svg>
          Resume Intelligence · ATS Engine
        </div>
        <h1 className="ats-title">ATS Resume Scanner & Matcher</h1>
        <p className="ats-subtitle">
          Test your resume against modern Applicant Tracking Systems (ATS) and target job roles.
          Identify missing keywords, assess impact metrics, and optimize your resume to maximize recruiter interview invites.
        </p>
      </div>

      {/* Input & Upload Card */}
      <div className="ats-card">
        <form onSubmit={handleSubmit}>
          {/* Step 1: Target Role */}
          <div className="ats-form-section">
            <label className="ats-form-label">
              1. Select Target Job Role
            </label>
            <div className="ats-roles-grid">
              {(roles.length > 0 ? roles.map((r) => r.title) : POPULAR_ROLES).map((r) => (
                <button
                  key={r}
                  type="button"
                  className={`ats-role-pill ${!isCustomRole && selectedRole === r ? "is-selected" : ""}`}
                  onClick={() => handleRoleSelect(r)}
                >
                  {r}
                </button>
              ))}
              <button
                type="button"
                className={`ats-role-pill ${isCustomRole ? "is-selected" : ""}`}
                onClick={() => setIsCustomRole(true)}
              >
                + Other / Custom Role
              </button>
            </div>

            {!isCustomRole && roles.find((r) => r.title === selectedRole) && (
              <div style={{ fontSize: "0.8rem", color: "var(--muted-2)", marginBottom: "0.75rem" }}>
                <strong>Benchmark Core Competencies:</strong>{" "}
                {roles
                  .find((r) => r.title === selectedRole)
                  ?.benchmark_skills.slice(0, 6).join(", ")}
              </div>
            )}

            {isCustomRole && (
              <div style={{ marginTop: "0.5rem" }}>
                <input
                  type="text"
                  className="ats-custom-role-input"
                  placeholder="e.g. Cloud Infrastructure Engineer, QA Automation"
                  value={customRole}
                  onChange={(e) => setCustomRole(e.target.value)}
                  autoFocus
                />
              </div>
            )}

            {/* Optional Job Description */}
            <div>
              <button
                type="button"
                className="ats-jd-toggle"
                onClick={() => setShowJdInput(!showJdInput)}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d={showJdInput ? "M18 15l-6-6-6 6" : "M6 9l6 6 6-6"} />
                </svg>
                {showJdInput ? "Hide Job Description" : "+ Add Specific Job Description for Exact Keyword Match (Optional)"}
              </button>
              {showJdInput && (
                <div>
                  <textarea
                    className="ats-jd-textarea"
                    placeholder="Paste the job posting or requirements here to test against this specific company's criteria..."
                    value={jobDescription}
                    onChange={(e) => setJobDescription(e.target.value)}
                  />
                  <div className="ats-form-hint">
                    Skills mentioned in this job description will be added to the ATS scanner requirements.
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Step 2: Resume Document */}
          <div className="ats-form-section">
            <label className="ats-form-label">
              2. Provide Resume
            </label>

            {existingResumes.length > 0 && (
              <div className="ats-upload-modes">
                <button
                  type="button"
                  className={`ats-mode-btn ${uploadMode === "upload" ? "is-active" : ""}`}
                  onClick={() => setUploadMode("upload")}
                >
                  Upload File
                </button>
                <button
                  type="button"
                  className={`ats-mode-btn ${uploadMode === "existing" ? "is-active" : ""}`}
                  onClick={() => setUploadMode("existing")}
                >
                  Use Profile Resume ({existingResumes.length})
                </button>
              </div>
            )}

            {uploadMode === "upload" ? (
              <div>
                {!file ? (
                  <div
                    className={`ats-dropzone ${isDragOver ? "is-dragover" : ""}`}
                    onDragOver={(e) => {
                      e.preventDefault();
                      setIsDragOver(true);
                    }}
                    onDragLeave={() => setIsDragOver(false)}
                    onDrop={handleFileDrop}
                    onClick={() => fileInputRef.current?.click()}
                  >
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                      style={{ display: "none" }}
                      onChange={handleFileChange}
                    />
                    <div className="ats-dropzone-icon">
                      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                        <polyline points="17 8 12 3 7 8" />
                        <line x1="12" y1="3" x2="12" y2="15" />
                      </svg>
                    </div>
                    <div className="ats-dropzone-title">Click or drag & drop your .docx resume here</div>
                    <div className="ats-dropzone-sub">Supports Microsoft Word (.docx) only (Max 10 MB)</div>
                  </div>
                ) : (
                  <div className="ats-file-selected">
                    <div className="ats-file-info">
                      <div className="ats-file-icon">
                        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                          <polyline points="14 2 14 8 20 8" />
                        </svg>
                      </div>
                      <div>
                        <div className="ats-file-name">{file.name}</div>
                        <div className="ats-file-size">{(file.size / 1024).toFixed(1)} KB</div>
                      </div>
                    </div>
                    <button
                      type="button"
                      className="ats-file-remove"
                      onClick={() => setFile(null)}
                      title="Remove file"
                    >
                      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <line x1="18" y1="6" x2="6" y2="18" />
                        <line x1="6" y1="6" x2="18" y2="18" />
                      </svg>
                    </button>
                  </div>
                )}
              </div>
            ) : (
              <div className="ats-existing-resumes">
                {existingResumes.map((ev) => (
                  <div
                    key={ev.id}
                    className={`ats-existing-item ${selectedEvidenceId === ev.id ? "is-selected" : ""}`}
                    onClick={() => setSelectedEvidenceId(ev.id)}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                        <polyline points="14 2 14 8 20 8" />
                      </svg>
                      <div>
                        <div style={{ fontWeight: 600, fontSize: "0.9rem", color: "var(--ink)" }}>{ev.filename}</div>
                        <div style={{ fontSize: "0.78rem", color: "var(--muted-2)" }}>
                          {ev.word_count ? `${ev.word_count} words · ` : ""}Uploaded Evidence
                        </div>
                      </div>
                    </div>
                    <input
                      type="radio"
                      name="existingResume"
                      checked={selectedEvidenceId === ev.id}
                      onChange={() => setSelectedEvidenceId(ev.id)}
                    />
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Error Message */}
          {error && (
            <div className="ats-error-banner">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="8" x2="12" y2="12" />
                <line x1="12" y1="16" x2="12.01" y2="16" />
              </svg>
              <span>{error}</span>
            </div>
          )}

          {/* Submit Action */}
          <div>
            <button
              type="submit"
              className="ats-submit-btn"
              disabled={loading}
            >
              {loading ? (
                <>
                  <svg
                    style={{ animation: "spin 1s linear infinite" }}
                    width="18"
                    height="18"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2.5"
                  >
                    <circle cx="12" cy="12" r="10" strokeDasharray="32" strokeDashoffset="12" />
                  </svg>
                  <span>{loadingStep}</span>
                </>
              ) : (
                <>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                    <circle cx="11" cy="11" r="8" />
                    <line x1="21" y1="21" x2="16.65" y2="16.65" />
                  </svg>
                  <span>Scan Resume & Calculate ATS Score</span>
                </>
              )}
            </button>
          </div>
        </form>
      </div>

      {/* Results Dashboard */}
      {result && (
        <div className="ats-results" ref={resultsRef}>
          {/* Top Score Hero */}
          <div className="ats-card">
            <div className="ats-score-hero">
              {/* Circular Gauge */}
              <div className="ats-meter-wrapper">
                <div
                  className="ats-gauge-circle"
                  style={{
                    "--score-pct": result.scores.overall,
                    "--score-color": getScoreColor(result.scores.overall),
                  } as React.CSSProperties}
                >
                  <div className="ats-gauge-inner">
                    <span className="ats-gauge-val">{result.scores.overall}</span>
                    <span className="ats-gauge-max">/ 100</span>
                  </div>
                </div>
                <div
                  className="ats-grade-pill"
                  style={{
                    "--score-color": getScoreColor(result.scores.overall),
                    "--score-bg": getScoreBg(result.scores.overall),
                  } as React.CSSProperties}
                >
                  Grade {result.grade}
                </div>
              </div>

              {/* Score Headline */}
              <div className="ats-score-content">
                <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "8px" }}>
                  <span
                    style={{
                      fontSize: "0.78rem",
                      fontWeight: 700,
                      padding: "3px 10px",
                      borderRadius: "6px",
                      background: "var(--accent-soft)",
                      color: "var(--accent)",
                      border: "1px solid var(--accent-border)",
                    }}
                  >
                    {result.target_role}
                  </span>
                  <span style={{ fontSize: "0.82rem", color: "var(--muted-2)" }}>
                    Tested file: <strong>{result.filename}</strong>
                  </span>
                </div>

                <h2 className="ats-verdict-title">{result.verdict}</h2>
                <p className="ats-summary-text">{result.summary}</p>

                <div className="ats-meta-strip">
                  <div className="ats-meta-item">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                      <line x1="16" y1="13" x2="8" y2="13" />
                      <line x1="16" y1="17" x2="8" y2="17" />
                    </svg>
                    <span>{result.word_count} words</span>
                  </div>
                  <div className="ats-meta-item">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <circle cx="12" cy="12" r="10" />
                      <polyline points="12 6 12 12 16 14" />
                    </svg>
                    <span>~{Math.max(1, Math.round(result.word_count / 200))} min read</span>
                  </div>
                  <div className="ats-meta-item">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
                      <polyline points="22 4 12 14.01 9 11.01" />
                    </svg>
                    <span>{result.matched_skills.length} role skills matched</span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* 4 Dimension Breakdown Cards */}
          <div className="ats-dimensions-grid">
            <div className="ats-dim-card">
              <div className="ats-dim-top">
                <span className="ats-dim-name">Skills & Keywords</span>
                <span className="ats-dim-score" style={{ color: getScoreColor(result.scores.skills_match) }}>
                  {result.scores.skills_match}%
                </span>
              </div>
              <div className="ats-progress-track">
                <div
                  className="ats-progress-fill"
                  style={{
                    width: `${result.scores.skills_match}%`,
                    backgroundColor: getScoreColor(result.scores.skills_match),
                  }}
                />
              </div>
              <p className="ats-dim-desc">
                Coverage of core technical competencies, libraries, and frameworks expected for {result.target_role}.
              </p>
            </div>

            <div className="ats-dim-card">
              <div className="ats-dim-top">
                <span className="ats-dim-name">Impact & Metrics</span>
                <span className="ats-dim-score" style={{ color: getScoreColor(result.scores.impact_metrics) }}>
                  {result.scores.impact_metrics}%
                </span>
              </div>
              <div className="ats-progress-track">
                <div
                  className="ats-progress-fill"
                  style={{
                    width: `${result.scores.impact_metrics}%`,
                    backgroundColor: getScoreColor(result.scores.impact_metrics),
                  }}
                />
              </div>
              <p className="ats-dim-desc">
                Action-oriented engineering verbs and quantified numerical outcomes (% gains, latency, users).
              </p>
            </div>

            <div className="ats-dim-card">
              <div className="ats-dim-top">
                <span className="ats-dim-name">Structure & Sections</span>
                <span className="ats-dim-score" style={{ color: getScoreColor(result.scores.sections_structure) }}>
                  {result.scores.sections_structure}%
                </span>
              </div>
              <div className="ats-progress-track">
                <div
                  className="ats-progress-fill"
                  style={{
                    width: `${result.scores.sections_structure}%`,
                    backgroundColor: getScoreColor(result.scores.sections_structure),
                  }}
                />
              </div>
              <p className="ats-dim-desc">
                Standard ATS-compliant headings for Experience, Skills, Education, Projects, and Contact.
              </p>
            </div>

            <div className="ats-dim-card">
              <div className="ats-dim-top">
                <span className="ats-dim-name">Formatting & Length</span>
                <span className="ats-dim-score" style={{ color: getScoreColor(result.scores.formatting_parseability) }}>
                  {result.scores.formatting_parseability}%
                </span>
              </div>
              <div className="ats-progress-track">
                <div
                  className="ats-progress-fill"
                  style={{
                    width: `${result.scores.formatting_parseability}%`,
                    backgroundColor: getScoreColor(result.scores.formatting_parseability),
                  }}
                />
              </div>
              <p className="ats-dim-desc">
                Clean text extraction, contact information completeness, and optimal word density (400-900 words).
              </p>
            </div>
          </div>

          {/* Recommendations Card */}
          {result.recommendations.length > 0 && (
            <div className="ats-card">
              <div className="ats-card-header">
                <h3 className="ats-card-title">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <circle cx="12" cy="12" r="10" />
                    <line x1="12" y1="16" x2="12" y2="12" />
                    <line x1="12" y1="8" x2="12.01" y2="8" />
                  </svg>
                  Priority Optimization Recommendations
                </h3>
                <p className="ats-card-desc">
                  Ranked actions to improve your ATS match score and pass initial automated screening filters.
                </p>
              </div>

              <div className="ats-recs-list">
                {result.recommendations.map((rec, i) => (
                  <div key={i} className="ats-rec-item">
                    <span className={`ats-rec-priority-tag is-${rec.priority}`}>
                      {rec.priority}
                    </span>
                    <div className="ats-rec-body">
                      <div className="ats-rec-title">{rec.title}</div>
                      <div className="ats-rec-desc">{rec.description}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Detail Tabs Card */}
          <div className="ats-card">
            {/* Tab Navigation */}
            <div className="ats-tabs">
              <button
                type="button"
                className={`ats-tab-btn ${activeTab === "skills" ? "is-active" : ""}`}
                onClick={() => setActiveTab("skills")}
              >
                Skills Breakdown ({result.matched_skills.length} matched / {result.missing_skills.length} missing)
              </button>
              <button
                type="button"
                className={`ats-tab-btn ${activeTab === "audit" ? "is-active" : ""}`}
                onClick={() => setActiveTab("audit")}
              >
                Sections & Contact Audit
              </button>
              <button
                type="button"
                className={`ats-tab-btn ${activeTab === "verbs" ? "is-active" : ""}`}
                onClick={() => setActiveTab("verbs")}
              >
                Power Verbs & Metrics ({result.action_verbs_found.length} verbs / {result.metrics_found.length} metrics)
              </button>
              <button
                type="button"
                className={`ats-tab-btn ${activeTab === "rewrites" ? "is-active" : ""}`}
                onClick={() => setActiveTab("rewrites")}
              >
                Recruiter Bullet Rewrites (XYZ Formula)
              </button>
              <button
                type="button"
                className={`ats-tab-btn ${activeTab === "parser" ? "is-active" : ""}`}
                onClick={() => setActiveTab("parser")}
              >
                ATS Parser View
              </button>
            </div>

            {/* Tab 1: Skills Breakdown */}
            {activeTab === "skills" && (
              <div className="ats-skills-grid">
                {/* Matched Skills */}
                <div className="ats-skills-box">
                  <h4 className="ats-skills-box-title">
                    <span>Matched Keywords & Skills ({result.matched_skills.length})</span>
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#059669" strokeWidth="2.5">
                      <polyline points="20 6 9 17 4 12" />
                    </svg>
                  </h4>
                  {result.matched_skills.length > 0 ? (
                    <div className="ats-skills-pills">
                      {result.matched_skills.map((s, idx) => (
                        <span key={idx} className="ats-skill-badge is-matched">
                          {s.skill}
                          {s.occurrences > 1 && (
                            <span className="ats-skill-count">×{s.occurrences}</span>
                          )}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <p style={{ fontSize: "0.85rem", color: "var(--muted)" }}>
                      No direct skill matches detected for {result.target_role}.
                    </p>
                  )}

                  {/* Extra Skills Found */}
                  {result.extra_skills.length > 0 && (
                    <div style={{ marginTop: "1.25rem", paddingTop: "0.75rem", borderTop: "1px solid var(--line)" }}>
                      <div style={{ fontSize: "0.8rem", fontWeight: 700, color: "var(--muted)", marginBottom: "6px" }}>
                        Additional Technical Skills Found in Resume:
                      </div>
                      <div className="ats-skills-pills">
                        {result.extra_skills.map((es, idx) => (
                          <span key={idx} className="ats-skill-badge is-extra">
                            {es}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>

                {/* Missing Skills */}
                <div className="ats-skills-box">
                  <h4 className="ats-skills-box-title">
                    <span>Missing Role Skills ({result.missing_skills.length})</span>
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#e11d48" strokeWidth="2.5">
                      <circle cx="12" cy="12" r="10" />
                      <line x1="15" y1="9" x2="9" y2="15" />
                      <line x1="9" y1="9" x2="15" y2="15" />
                    </svg>
                  </h4>
                  {result.missing_skills.length > 0 ? (
                    <div className="ats-skills-pills">
                      {result.missing_skills.map((s, idx) => (
                        <span
                          key={idx}
                          className={`ats-skill-badge ${s.importance >= 0.85 ? "is-missing-critical" : "is-missing-important"}`}
                          title={`Importance: ${Math.round(s.importance * 100)}%`}
                        >
                          {s.skill}
                          <span style={{ fontSize: "0.7rem", opacity: 0.8 }}>
                            {s.importance >= 0.85 ? "Critical" : "Important"}
                          </span>
                        </span>
                      ))}
                    </div>
                  ) : (
                    <p style={{ fontSize: "0.85rem", color: "var(--ok-ink)", fontWeight: 600 }}>
                      Outstanding! All canonical skills for {result.target_role} are present in your resume.
                    </p>
                  )}
                  <p style={{ fontSize: "0.78rem", color: "var(--muted-2)", marginTop: "10px", lineHeight: 1.4 }}>
                    Tip: Incorporate missing keywords organically under your Skills list, and demonstrate practical usage in your project and work experience bullet points.
                  </p>
                </div>
              </div>
            )}

            {/* Tab 2: Sections & Contact Audit */}
            {activeTab === "audit" && (
              <div>
                <h4 style={{ fontSize: "0.95rem", fontWeight: 700, margin: "0 0 0.75rem", color: "var(--ink)" }}>
                  Contact Channels & Header Audit
                </h4>
                <div className="ats-audit-list" style={{ marginBottom: "1.5rem" }}>
                  <div className="ats-audit-item">
                    <div className="ats-audit-status-icon">
                      {result.contact.has_email ? (
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#059669" strokeWidth="2.5">
                          <polyline points="20 6 9 17 4 12" />
                        </svg>
                      ) : (
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#e11d48" strokeWidth="2.5">
                          <line x1="18" y1="6" x2="6" y2="18" />
                          <line x1="6" y1="6" x2="18" y2="18" />
                        </svg>
                      )}
                    </div>
                    <div>
                      <div className="ats-audit-title">Email Address</div>
                      <div className="ats-audit-desc">
                        {result.contact.has_email && result.contact.email ? (
                          <a href={`mailto:${result.contact.email}`} style={{ color: "var(--accent)", textDecoration: "underline" }}>
                            {result.contact.email}
                          </a>
                        ) : (
                          "Not detected in parsed text"
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="ats-audit-item">
                    <div className="ats-audit-status-icon">
                      {result.contact.has_phone ? (
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#059669" strokeWidth="2.5">
                          <polyline points="20 6 9 17 4 12" />
                        </svg>
                      ) : (
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#e11d48" strokeWidth="2.5">
                          <line x1="18" y1="6" x2="6" y2="18" />
                          <line x1="6" y1="6" x2="18" y2="18" />
                        </svg>
                      )}
                    </div>
                    <div>
                      <div className="ats-audit-title">Phone Number</div>
                      <div className="ats-audit-desc">
                        {result.contact.has_phone && result.contact.phone ? (
                          <a href={`tel:${result.contact.phone}`} style={{ color: "var(--ink)", fontWeight: 500 }}>
                            {result.contact.phone}
                          </a>
                        ) : (
                          "Not detected"
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="ats-audit-item">
                    <div className="ats-audit-status-icon">
                      {result.contact.has_linkedin ? (
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#059669" strokeWidth="2.5">
                          <polyline points="20 6 9 17 4 12" />
                        </svg>
                      ) : (
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#d97706" strokeWidth="2.5">
                          <line x1="12" y1="8" x2="12" y2="12" />
                          <line x1="12" y1="16" x2="12.01" y2="16" />
                        </svg>
                      )}
                    </div>
                    <div>
                      <div className="ats-audit-title">LinkedIn Profile Link</div>
                      <div className="ats-audit-desc">
                        {result.contact.has_linkedin && result.contact.linkedin_url ? (
                          <a
                            href={result.contact.linkedin_url.startsWith("http") ? result.contact.linkedin_url : `https://${result.contact.linkedin_url}`}
                            target="_blank"
                            rel="noreferrer"
                            style={{ color: "var(--accent)", textDecoration: "underline", wordBreak: "break-all" }}
                          >
                            {result.contact.linkedin_url}
                          </a>
                        ) : (
                          "Missing LinkedIn link or handle"
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="ats-audit-item">
                    <div className="ats-audit-status-icon">
                      {result.contact.has_github ? (
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#059669" strokeWidth="2.5">
                          <polyline points="20 6 9 17 4 12" />
                        </svg>
                      ) : (
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#d97706" strokeWidth="2.5">
                          <line x1="12" y1="8" x2="12" y2="12" />
                          <line x1="12" y1="16" x2="12.01" y2="16" />
                        </svg>
                      )}
                    </div>
                    <div>
                      <div className="ats-audit-title">GitHub Profile / Repos</div>
                      <div className="ats-audit-desc">
                        {result.contact.has_github && result.contact.github_url ? (
                          <a
                            href={result.contact.github_url.startsWith("http") ? result.contact.github_url : `https://${result.contact.github_url}`}
                            target="_blank"
                            rel="noreferrer"
                            style={{ color: "var(--accent)", textDecoration: "underline", wordBreak: "break-all" }}
                          >
                            {result.contact.github_url}
                          </a>
                        ) : (
                          "Missing GitHub link or handle"
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="ats-audit-item">
                    <div className="ats-audit-status-icon">
                      {result.contact.has_portfolio ? (
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#059669" strokeWidth="2.5">
                          <polyline points="20 6 9 17 4 12" />
                        </svg>
                      ) : (
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--muted-3)" strokeWidth="2">
                          <circle cx="12" cy="12" r="10" />
                        </svg>
                      )}
                    </div>
                    <div>
                      <div className="ats-audit-title">Portfolio / Personal Website</div>
                      <div className="ats-audit-desc">
                        {result.contact.has_portfolio && result.contact.portfolio_url ? (
                          <a
                            href={result.contact.portfolio_url.startsWith("http") ? result.contact.portfolio_url : `https://${result.contact.portfolio_url}`}
                            target="_blank"
                            rel="noreferrer"
                            style={{ color: "var(--accent)", textDecoration: "underline", wordBreak: "break-all" }}
                          >
                            {result.contact.portfolio_url}
                          </a>
                        ) : (
                          "None detected (Optional)"
                        )}
                      </div>
                    </div>
                  </div>
                </div>

                {/* All Detected Links in Document */}
                {result.contact.all_links && result.contact.all_links.length > 0 && (
                  <div style={{ marginBottom: "1.5rem", padding: "12px 14px", borderRadius: "10px", background: "var(--glass-bg-strong)", border: "1px solid var(--line)" }}>
                    <div style={{ fontSize: "0.82rem", fontWeight: 700, color: "var(--ink)", marginBottom: "6px" }}>
                      All Detected Hyperlinks & Profiles ({result.contact.all_links.length}):
                    </div>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: "8px" }}>
                      {result.contact.all_links.map((link, lIdx) => (
                        <a
                          key={lIdx}
                          href={link.startsWith("http") ? link : `https://${link}`}
                          target="_blank"
                          rel="noreferrer"
                          style={{
                            fontSize: "0.78rem",
                            padding: "3px 10px",
                            borderRadius: "6px",
                            background: "var(--glass-bg-soft)",
                            border: "1px solid var(--line)",
                            color: "var(--accent)",
                            textDecoration: "none",
                            display: "inline-flex",
                            alignItems: "center",
                            gap: "4px",
                          }}
                        >
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
                            <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
                          </svg>
                          {link.replace(/^https?:\/\/(?:www\.)?/, "")}
                        </a>
                      ))}
                    </div>
                  </div>
                )}

                <h4 style={{ fontSize: "0.95rem", fontWeight: 700, margin: "0 0 0.75rem", color: "var(--ink)" }}>
                  Standard Resume Sections Check
                </h4>
                <div className="ats-audit-list">
                  {result.sections.map((sec, idx) => (
                    <div key={idx} className="ats-audit-item">
                      <div className="ats-audit-status-icon">
                        {sec.found ? (
                          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#059669" strokeWidth="2.5">
                            <polyline points="20 6 9 17 4 12" />
                          </svg>
                        ) : (
                          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#e11d48" strokeWidth="2.5">
                            <line x1="18" y1="6" x2="6" y2="18" />
                            <line x1="6" y1="6" x2="18" y2="18" />
                          </svg>
                        )}
                      </div>
                      <div>
                        <div className="ats-audit-title">
                          {sec.name}{" "}
                          <span style={{ fontSize: "0.7rem", fontWeight: 600, opacity: 0.7 }}>
                            ({sec.importance})
                          </span>
                        </div>
                        <div className="ats-audit-desc">{sec.description}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Tab 3: Action Verbs & Metrics */}
            {activeTab === "verbs" && (
              <div>
                <div style={{ marginBottom: "1.5rem" }}>
                  <h4 style={{ fontSize: "0.95rem", fontWeight: 700, margin: "0 0 0.5rem", color: "var(--ink)" }}>
                    Action Verbs Detected ({result.action_verbs_found.length})
                  </h4>
                  <p style={{ fontSize: "0.82rem", color: "var(--muted)", margin: "0 0 0.75rem" }}>
                    ATS systems award higher ranking to resumes with diverse leadership, engineering, and execution verbs.
                  </p>
                  <div className="ats-skills-pills">
                    {result.action_verbs_found.map((v, i) => (
                      <span key={i} className="ats-skill-badge is-matched">
                        {v}
                      </span>
                    ))}
                  </div>
                </div>

                <div>
                  <h4 style={{ fontSize: "0.95rem", fontWeight: 700, margin: "0 0 0.5rem", color: "var(--ink)" }}>
                    Quantifiable Impact Metrics Detected ({result.metrics_found.length})
                  </h4>
                  <p style={{ fontSize: "0.82rem", color: "var(--muted)", margin: "0 0 0.75rem" }}>
                    Data points, throughput, scale, and performance gains extracted from your document.
                  </p>
                  {result.metrics_found.length > 0 ? (
                    <div className="ats-skills-pills">
                      {result.metrics_found.map((m, i) => (
                        <span key={i} className="ats-skill-badge is-matched" style={{ background: "rgba(37, 99, 235, 0.12)", color: "var(--info-ink)", borderColor: "rgba(37, 99, 235, 0.3)" }}>
                          {m}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <p style={{ fontSize: "0.85rem", color: "var(--muted)" }}>
                      No quantifiable metrics detected. Add numbers, percentages, or scale metrics to your achievements.
                    </p>
                  )}
                </div>
              </div>
            )}

            {/* Tab 4: Recruiter Bullet Rewrites */}
            {activeTab === "rewrites" && (
              <div>
                <div style={{ marginBottom: "1rem" }}>
                  <h4 style={{ fontSize: "0.95rem", fontWeight: 700, margin: "0 0 0.25rem", color: "var(--ink)" }}>
                    Google X-Y-Z Achievement Transformations
                  </h4>
                  <p style={{ fontSize: "0.82rem", color: "var(--muted)", margin: 0 }}>
                    Transform weak or generic responsibilities into high-converting bullet points: <em>"Accomplished [X] as measured by [Y], by doing [Z]"</em>.
                  </p>
                </div>

                <div className="ats-rewrites-list">
                  {result.bullet_rewrites.map((br, idx) => (
                    <div key={idx} className="ats-rewrite-card">
                      <div className="ats-rewrite-line">
                        <div className="ats-rewrite-label is-original">
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                            <line x1="18" y1="6" x2="6" y2="18" />
                            <line x1="6" y1="6" x2="18" y2="18" />
                          </svg>
                          Before (Weak / Low ATS Signal)
                        </div>
                        <div className="ats-rewrite-text is-original">{br.original}</div>
                      </div>

                      <div className="ats-rewrite-line">
                        <div className="ats-rewrite-label is-improved">
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                            <polyline points="20 6 9 17 4 12" />
                          </svg>
                          After (High-Impact ATS Formulation)
                        </div>
                        <div className="ats-rewrite-text is-improved">{br.improved}</div>
                        <div className="ats-rewrite-explanation">{br.explanation}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Tab 5: ATS Parser View */}
            {activeTab === "parser" && (
              <div>
                <div style={{ marginBottom: "0.75rem" }}>
                  <h4 style={{ fontSize: "0.95rem", fontWeight: 700, margin: "0 0 0.25rem", color: "var(--ink)" }}>
                    What the ATS Parser Actually Extracts
                  </h4>
                  <p style={{ fontSize: "0.82rem", color: "var(--muted)", margin: 0 }}>
                    If formatting or columns break this text, your resume may fail ATS filters regardless of your qualifications.
                  </p>
                </div>
                <pre className="ats-inspector-pre">{result.parsed_text_preview}</pre>
              </div>
            )}
          </div>

          {/* Action Footer */}
          <div className="ats-actions-footer">
            <button
              type="button"
              className="ats-secondary-btn"
              onClick={handleCopyReport}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
              </svg>
              {copied ? "Report Copied to Clipboard!" : "Copy Summary Report"}
            </button>

            <button
              type="button"
              className="ats-secondary-btn"
              onClick={() => {
                window.scrollTo({ top: 0, behavior: "smooth" });
              }}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M12 19V5M5 12l7-7 7 7" />
              </svg>
              Test Another Role / Update Resume
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
