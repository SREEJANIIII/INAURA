import { useState, useEffect, useCallback } from "react";
import {
  getApplication,
  transitionApplication,
  getFeedback,
  submitFeedback,
  listPlacementsForEmployer,
  createPlacement,
  updatePlacement,
  confirmPlacement,
  listAlignments,
  type ApplicationDetail,
  type EmployerFeedback,
  type Placement,
  type Alignment,
  type ApplicationStatus,
} from "../../services/outcomes";
import {
  formatStatusLabel,
  getAllowedEmployerTransitions,
  isTerminalStatus,
} from "../../lib/applicationsModel";
import "./EmployerComponents.css";

type CandidateDetailModalProps = {
  applicationId: string;
  employerId: string;
  onClose: () => void;
  onApplicationUpdated: () => void;
};

type ModalTab = "skills" | "decision" | "feedback" | "placement";

export default function CandidateDetailModal({
  applicationId,
  employerId,
  onClose,
  onApplicationUpdated,
}: CandidateDetailModalProps) {
  const [detail, setDetail] = useState<ApplicationDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<ModalTab>("skills");

  // Decision state
  const [transitionNote, setTransitionNote] = useState("");
  const [transitioning, setTransitioning] = useState(false);

  // Feedback state
  const [feedback, setFeedback] = useState<EmployerFeedback | null>(null);
  const [loadingFeedback, setLoadingFeedback] = useState(false);
  const [submittingFeedback, setSubmittingFeedback] = useState(false);
  const [fbOverall, setFbOverall] = useState<number | "">(4);
  const [fbTech, setFbTech] = useState<number | "">(4);
  const [fbComm, setFbComm] = useState<number | "">(4);
  const [fbProblem, setFbProblem] = useState<number | "">(4);
  const [fbProject, setFbProject] = useState<number | "">(4);
  const [fbRole, setFbRole] = useState<number | "">(4);
  const [fbSummary, setFbSummary] = useState("");
  const [fbComment, setFbComment] = useState("");

  // Placements state
  const [placements, setPlacements] = useState<Placement[]>([]);
  const [joiningDate, setJoiningDate] = useState("");
  const [savingPlacement, setSavingPlacement] = useState(false);

  // Alignments state
  const [alignments, setAlignments] = useState<Alignment[]>([]);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const app = await getApplication(applicationId);
      setDetail(app);

      // Load feedback
      setLoadingFeedback(true);
      try {
        const fb = await getFeedback(applicationId);
        setFeedback(fb);
      } catch {
        setFeedback(null);
      } finally {
        setLoadingFeedback(false);
      }

      // Load employer placements
      try {
        const pls = await listPlacementsForEmployer(employerId);
        setPlacements(pls);
      } catch {
        setPlacements([]);
      }

      // Load alignments for requirement
      if (app.hiring_requirement_id) {
        try {
          const algs = await listAlignments(app.hiring_requirement_id);
          setAlignments(algs);
        } catch {
          setAlignments([]);
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [applicationId, employerId]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const handleTransition = async (toStatus: ApplicationStatus) => {
    if (!detail) return;
    setTransitioning(true);
    setError(null);
    try {
      await transitionApplication(detail.id, toStatus, transitionNote.trim() || undefined);
      setTransitionNote("");
      await loadData();
      onApplicationUpdated();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setTransitioning(false);
    }
  };

  const handleSubmitFeedback = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!detail) return;
    setSubmittingFeedback(true);
    setError(null);
    try {
      const skillFeedbackPayload = (detail.candidate_skills || []).map((s) => ({
        skill_id: s.skill_id,
        expected_level: s.required_level ?? 0.7,
        observed_level: s.observed_level ?? 0.7,
        comment: s.status === "gap" ? "Needs growth" : "Adequate proficiency observed",
      }));

      await submitFeedback(detail.id, {
        overall_rating: typeof fbOverall === "number" ? fbOverall : null,
        technical_ability: typeof fbTech === "number" ? fbTech : null,
        communication: typeof fbComm === "number" ? fbComm : null,
        problem_solving: typeof fbProblem === "number" ? fbProblem : null,
        project_readiness: typeof fbProject === "number" ? fbProject : null,
        role_readiness: typeof fbRole === "number" ? fbRole : null,
        interview_summary: fbSummary.trim() || null,
        overall_comment: fbComment.trim() || null,
        skills: skillFeedbackPayload,
      });

      await loadData();
      onApplicationUpdated();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmittingFeedback(false);
    }
  };

  const handleCreatePlacement = async () => {
    if (!detail) return;
    setSavingPlacement(true);
    setError(null);
    try {
      await createPlacement({
        employer_id: employerId,
        application_id: detail.id,
        role_title: detail.requirement_title || "Software Engineer",
        joining_date: joiningDate || null,
        status: "pending",
      });
      await loadData();
      onApplicationUpdated();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSavingPlacement(false);
    }
  };

  const handleConfirmPlacement = async (placementId: string, verified: boolean) => {
    setSavingPlacement(true);
    setError(null);
    try {
      await confirmPlacement(placementId, verified);
      await loadData();
      onApplicationUpdated();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSavingPlacement(false);
    }
  };

  const handleUpdatePlacementStatus = async (placementId: string, status: string, date?: string) => {
    setSavingPlacement(true);
    setError(null);
    try {
      await updatePlacement(placementId, {
        status,
        joining_date: date || undefined,
      });
      await loadData();
      onApplicationUpdated();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSavingPlacement(false);
    }
  };

  const candidatePlacement = placements.find((p) => p.application_id === applicationId);
  const allowedTransitions = detail ? getAllowedEmployerTransitions(detail.status) : [];
  const candidateName =
    detail?.candidate_name ||
    detail?.candidate_profile?.full_name ||
    `Candidate ${detail?.student_id?.slice(0, 8) || ""}`;

  return (
    <div className="emp-modal-overlay" onClick={onClose} role="dialog" aria-modal="true">
      <div className="emp-modal" style={{ maxWidth: 840 }} onClick={(e) => e.stopPropagation()}>
        <div className="emp-modal__header">
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "0.6rem" }}>
              <h2 style={{ fontSize: "1.25rem", margin: 0, fontWeight: 700 }}>
                {candidateName}
              </h2>
              {detail && (
                <span className={`emp-badge emp-badge--${detail.status}`}>
                  {formatStatusLabel(detail.status)}
                </span>
              )}
            </div>
            <div style={{ fontSize: "0.85rem", color: "var(--muted)", marginTop: "0.25rem" }}>
              Applied for: <strong>{detail?.requirement_title || "Hiring Requirement"}</strong> • Student ID: <code>{detail?.student_id}</code>
            </div>
          </div>
          <button type="button" className="emp-modal__close" onClick={onClose} aria-label="Close modal">
            ✕
          </button>
        </div>

        {error && (
          <div style={{ background: "#fef2f2", color: "#dc2626", padding: "0.6rem 0.85rem", borderRadius: "8px", marginBottom: "1rem", fontSize: "0.85rem" }}>
            {error}
          </div>
        )}

        {loading ? (
          <div style={{ padding: "3rem", textAlign: "center", color: "var(--muted)" }}>
            Loading candidate details, evidence and alignment…
          </div>
        ) : !detail ? (
          <div style={{ padding: "2rem", textAlign: "center" }}>Candidate record not found.</div>
        ) : (
          <>
            {/* Modal Tabs */}
            <div className="emp-tabs" style={{ marginBottom: "1rem" }}>
              <button
                type="button"
                className={`emp-tab-btn${tab === "skills" ? " is-active" : ""}`}
                onClick={() => setTab("skills")}
              >
                Skills &amp; Evidence Match
              </button>
              <button
                type="button"
                className={`emp-tab-btn${tab === "decision" ? " is-active" : ""}`}
                onClick={() => setTab("decision")}
              >
                Hiring Decision &amp; Audit ({detail.events.length})
              </button>
              <button
                type="button"
                className={`emp-tab-btn${tab === "feedback" ? " is-active" : ""}`}
                onClick={() => setTab("feedback")}
              >
                Evaluation Feedback {feedback ? "✓" : ""}
              </button>
              <button
                type="button"
                className={`emp-tab-btn${tab === "placement" ? " is-active" : ""}`}
                onClick={() => setTab("placement")}
              >
                Placement Outcome {candidatePlacement ? `(${candidatePlacement.status})` : ""}
              </button>
            </div>

            {/* TAB 1: SKILLS & EVIDENCE MATCH (Section 13) */}
            {tab === "skills" && (
              <div>
                {/* Candidate Education / Background */}
                {detail.candidate_profile && (
                  <div style={{ background: "var(--paper-2, #f8fafc)", padding: "0.85rem 1rem", borderRadius: "8px", marginBottom: "1rem", border: "1px solid var(--line)" }}>
                    <div style={{ fontSize: "0.8rem", fontWeight: 700, textTransform: "uppercase", color: "var(--muted)", marginBottom: "0.4rem" }}>
                      Academic &amp; Professional Background
                    </div>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "0.5rem", fontSize: "0.85rem" }}>
                      <div>College: <strong>{detail.candidate_profile.college || "N/A"}</strong></div>
                      <div>Degree: <strong>{detail.candidate_profile.degree || "N/A"}</strong> ({detail.candidate_profile.branch || "N/A"})</div>
                      <div>Graduation Year: <strong>{detail.candidate_profile.graduation_year || "N/A"}</strong></div>
                    </div>
                  </div>
                )}

                {/* Skill Alignment Comparison */}
                <div style={{ marginBottom: "1.25rem" }}>
                  <h4 style={{ fontSize: "0.95rem", fontWeight: 700, margin: "0 0 0.5rem" }}>
                    Required Skills vs. Demonstrated Proficiency
                  </h4>
                  {(!detail.candidate_skills || detail.candidate_skills.length === 0) ? (
                    <div style={{ padding: "0.75rem", background: "var(--paper-2, #f8fafc)", borderRadius: "8px", fontSize: "0.85rem", color: "var(--muted)" }}>
                      No explicit skill requirements mapped to this requirement yet. Manage skills under Hiring Requirements.
                    </div>
                  ) : (
                    <div className="emp-table-wrap">
                      <table className="emp-table">
                        <thead>
                          <tr>
                            <th>Skill</th>
                            <th>Priority</th>
                            <th>Target Level</th>
                            <th>Observed / Assessed</th>
                            <th>Status</th>
                          </tr>
                        </thead>
                        <tbody>
                          {detail.candidate_skills.map((sk) => {
                            const isMet = sk.status === "met";
                            const isGap = sk.status === "gap";
                            return (
                              <tr key={sk.skill_id}>
                                <td>
                                  <strong>{sk.skill_name || sk.skill_id}</strong>
                                </td>
                                <td>
                                  <span style={{ fontSize: "0.75rem", textTransform: "uppercase", fontWeight: 600, color: sk.importance === "required" ? "#dc2626" : "var(--muted)" }}>
                                    {sk.importance}
                                  </span>
                                </td>
                                <td>{sk.required_level != null ? `${Math.round(sk.required_level * 100)}%` : "Not specified"}</td>
                                <td>
                                  {sk.observed_level != null ? (
                                    <span>
                                      {Math.round(sk.observed_level * 100)}%{" "}
                                      <span
                                        className="emp-badge emp-badge--open"
                                        style={{ fontSize: "0.68rem" }}
                                        title="Level comes from the candidate's INAURA skill assessment record"
                                      >
                                        INAURA-assessed
                                      </span>
                                    </span>
                                  ) : (
                                    <span style={{ color: "var(--muted)" }}>Not assessed</span>
                                  )}
                                </td>
                                <td>
                                  {isMet && (
                                    <span className="emp-badge emp-badge--open">✓ Requirement Met</span>
                                  )}
                                  {isGap && (
                                    <span className="emp-badge emp-badge--rejected">Skill Gap Identified</span>
                                  )}
                                  {!isMet && !isGap && (
                                    <span className="emp-badge emp-badge--applied">Under Review</span>
                                  )}
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>

                {/* Candidate Evidence Items */}
                <div style={{ marginBottom: "1.25rem" }}>
                  <h4 style={{ fontSize: "0.95rem", fontWeight: 700, margin: "0 0 0.5rem" }}>
                    Demonstrated Evidence &amp; Artifacts
                  </h4>
                  {(!detail.candidate_evidence || detail.candidate_evidence.length === 0) ? (
                    <p style={{ fontSize: "0.85rem", color: "var(--muted)", margin: 0 }}>
                      No standalone projects or external certifications linked by the candidate yet.
                    </p>
                  ) : (
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "0.75rem" }}>
                      {detail.candidate_evidence.map((ev) => (
                        <div key={ev.id} style={{ background: "var(--paper-2, #f8fafc)", padding: "0.75rem", borderRadius: "8px", border: "1px solid var(--line)" }}>
                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "0.5rem" }}>
                            <strong style={{ fontSize: "0.85rem" }}>{ev.title || "Evidence Artifact"}</strong>
                            <span style={{ display: "flex", gap: "0.3rem", alignItems: "center" }}>
                              <span className="emp-badge emp-badge--applied" style={{ fontSize: "0.7rem" }}>{ev.type}</span>
                              <span
                                className="emp-badge emp-badge--applied"
                                style={{ fontSize: "0.68rem" }}
                                title="Submitted by the candidate; review the linked artifact before relying on it"
                              >
                                Student-provided
                              </span>
                            </span>
                          </div>
                          {ev.description && (
                            <p style={{ fontSize: "0.8rem", color: "var(--muted)", margin: "0.35rem 0" }}>
                              {ev.description}
                            </p>
                          )}
                          {ev.url && (
                            <a
                              href={ev.url}
                              target="_blank"
                              rel="noreferrer noopener"
                              style={{ fontSize: "0.75rem", color: "#0d9488", textDecoration: "underline" }}
                            >
                              Open Source Link ↗
                            </a>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* Qualification Alignments */}
                {alignments.length > 0 && (
                  <div>
                    <h4 style={{ fontSize: "0.95rem", fontWeight: 700, margin: "0 0 0.5rem" }}>
                      Course &amp; Curriculum Alignments
                    </h4>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem" }}>
                      {alignments.map((alg) => (
                        <span key={alg.id} style={{ fontSize: "0.8rem", padding: "0.35rem 0.65rem", background: "rgba(13, 148, 136, 0.08)", border: "1px solid rgba(13, 148, 136, 0.2)", borderRadius: "6px" }}>
                          {alg.course_name} {alg.coverage != null && `(${Math.round(alg.coverage * 100)}% coverage)`}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* TAB 2: HIRING DECISION & AUDIT (Section 12) */}
            {tab === "decision" && (
              <div>
                <div style={{ background: "var(--paper-2, #f8fafc)", padding: "1rem", borderRadius: "10px", border: "1px solid var(--line)", marginBottom: "1.25rem" }}>
                  <h4 style={{ fontSize: "0.95rem", fontWeight: 700, margin: "0 0 0.5rem" }}>
                    Stage Transition &amp; Decision Note
                  </h4>
                  {allowedTransitions.length === 0 ? (
                    <p style={{ fontSize: "0.85rem", color: "var(--muted)", margin: 0 }}>
                      {isTerminalStatus(detail.status)
                        ? `Application reached a terminal state (${formatStatusLabel(detail.status)}). No further transitions allowed.`
                        : "Waiting on candidate or no available actions from current status."}
                    </p>
                  ) : (
                    <div>
                      <input
                        className="emp-input"
                        style={{ width: "100%", marginBottom: "0.75rem" }}
                        placeholder="Internal decision rationale or note to team (optional)"
                        value={transitionNote}
                        onChange={(e) => setTransitionNote(e.target.value)}
                      />
                      <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem" }}>
                        {allowedTransitions.includes("screening") && (
                          <button
                            type="button"
                            className="emp-btn emp-btn--secondary"
                            onClick={() => handleTransition("screening")}
                            disabled={transitioning}
                          >
                            Move to Screening
                          </button>
                        )}
                        {allowedTransitions.includes("interview") && (
                          <button
                            type="button"
                            className="emp-btn emp-btn--primary"
                            onClick={() => handleTransition("interview")}
                            disabled={transitioning}
                          >
                            Advance to Interview
                          </button>
                        )}
                        {allowedTransitions.includes("offer_received") && (
                          <button
                            type="button"
                            className="emp-btn"
                            style={{ background: "#0d9488", color: "#ffffff" }}
                            onClick={() => handleTransition("offer_received")}
                            disabled={transitioning}
                          >
                            Extend Offer
                          </button>
                        )}
                        {allowedTransitions.includes("selected") && (
                          <button
                            type="button"
                            className="emp-btn"
                            style={{ background: "#16a34a", color: "#ffffff" }}
                            onClick={() => handleTransition("selected")}
                            disabled={transitioning}
                          >
                            Select / Hire
                          </button>
                        )}
                        {allowedTransitions.includes("rejected") && (
                          <button
                            type="button"
                            className="emp-btn emp-btn--danger-ghost"
                            onClick={() => handleTransition("rejected")}
                            disabled={transitioning}
                          >
                            Reject Application
                          </button>
                        )}
                      </div>
                    </div>
                  )}
                </div>

                {/* Audit Timeline */}
                <div>
                  <h4 style={{ fontSize: "0.95rem", fontWeight: 700, margin: "0 0 0.5rem" }}>
                    Candidate Audit Log ({detail.events.length})
                  </h4>
                  <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
                    {detail.events.map((ev) => (
                      <div
                        key={ev.id}
                        style={{
                          background: "var(--paper, #ffffff)",
                          border: "1px solid var(--line)",
                          padding: "0.6rem 0.85rem",
                          borderRadius: "8px",
                          fontSize: "0.85rem",
                        }}
                      >
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                          <div>
                            {ev.from_status ? (
                              <span>
                                {formatStatusLabel(ev.from_status)} → <strong>{formatStatusLabel(ev.to_status)}</strong>
                              </span>
                            ) : (
                              <span>Application Created ({formatStatusLabel(ev.to_status)})</span>
                            )}
                          </div>
                          <span className="emp-badge emp-badge--applied" style={{ fontSize: "0.7rem" }}>
                            {ev.actor || "system"}
                          </span>
                        </div>
                        {ev.note && <div style={{ color: "var(--muted)", marginTop: "0.25rem" }}>&ldquo;{ev.note}&rdquo;</div>}
                        <div style={{ fontSize: "0.75rem", color: "var(--muted-2)", marginTop: "0.2rem" }}>
                          {new Date(ev.created_at).toLocaleString()}
                        </div>
                      </div>
                    ))}
                    {detail.events.length === 0 && (
                      <p style={{ fontSize: "0.85rem", color: "var(--muted)" }}>No events recorded.</p>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* TAB 3: EMPLOYER FEEDBACK (Section 14) */}
            {tab === "feedback" && (
              <div>
                {loadingFeedback ? (
                  <p style={{ color: "var(--muted)" }}>Checking submitted feedback…</p>
                ) : feedback ? (
                  <div style={{ background: "var(--paper-2, #f8fafc)", padding: "1.25rem", borderRadius: "10px", border: "1px solid var(--line)" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.75rem" }}>
                      <h4 style={{ fontSize: "1rem", fontWeight: 700, margin: 0 }}>
                        Summative Evaluation Submitted
                      </h4>
                      <span className="emp-badge emp-badge--open">Final Feedback Logged</span>
                    </div>

                    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: "0.75rem", marginBottom: "1rem" }}>
                      <div style={{ background: "var(--paper)", padding: "0.5rem 0.75rem", borderRadius: "6px", border: "1px solid var(--line)" }}>
                        <div style={{ fontSize: "0.75rem", color: "var(--muted)" }}>Overall Rating</div>
                        <div style={{ fontSize: "1.2rem", fontWeight: 700 }}>{feedback.overall_rating ?? "—"}/5</div>
                      </div>
                      <div style={{ background: "var(--paper)", padding: "0.5rem 0.75rem", borderRadius: "6px", border: "1px solid var(--line)" }}>
                        <div style={{ fontSize: "0.75rem", color: "var(--muted)" }}>Technical</div>
                        <div style={{ fontSize: "1.2rem", fontWeight: 700 }}>{feedback.technical_ability ?? "—"}/5</div>
                      </div>
                      <div style={{ background: "var(--paper)", padding: "0.5rem 0.75rem", borderRadius: "6px", border: "1px solid var(--line)" }}>
                        <div style={{ fontSize: "0.75rem", color: "var(--muted)" }}>Communication</div>
                        <div style={{ fontSize: "1.2rem", fontWeight: 700 }}>{feedback.communication ?? "—"}/5</div>
                      </div>
                      <div style={{ background: "var(--paper)", padding: "0.5rem 0.75rem", borderRadius: "6px", border: "1px solid var(--line)" }}>
                        <div style={{ fontSize: "0.75rem", color: "var(--muted)" }}>Problem Solving</div>
                        <div style={{ fontSize: "1.2rem", fontWeight: 700 }}>{feedback.problem_solving ?? "—"}/5</div>
                      </div>
                      <div style={{ background: "var(--paper)", padding: "0.5rem 0.75rem", borderRadius: "6px", border: "1px solid var(--line)" }}>
                        <div style={{ fontSize: "0.75rem", color: "var(--muted)" }}>Project Readiness</div>
                        <div style={{ fontSize: "1.2rem", fontWeight: 700 }}>{feedback.project_readiness ?? "—"}/5</div>
                      </div>
                      <div style={{ background: "var(--paper)", padding: "0.5rem 0.75rem", borderRadius: "6px", border: "1px solid var(--line)" }}>
                        <div style={{ fontSize: "0.75rem", color: "var(--muted)" }}>Role Readiness</div>
                        <div style={{ fontSize: "1.2rem", fontWeight: 700 }}>{feedback.role_readiness ?? "—"}/5</div>
                      </div>
                    </div>

                    {feedback.interview_summary && (
                      <div style={{ marginBottom: "0.75rem", fontSize: "0.85rem" }}>
                        <strong>Interview Summary:</strong>
                        <p style={{ margin: "0.25rem 0", color: "var(--muted)" }}>{feedback.interview_summary}</p>
                      </div>
                    )}

                    {feedback.overall_comment && (
                      <div style={{ marginBottom: "0.75rem", fontSize: "0.85rem" }}>
                        <strong>Overall Comments:</strong>
                        <p style={{ margin: "0.25rem 0", fontStyle: "italic", color: "var(--muted)" }}>&ldquo;{feedback.overall_comment}&rdquo;</p>
                      </div>
                    )}

                    {feedback.skills && feedback.skills.length > 0 && (
                      <div>
                        <strong style={{ fontSize: "0.85rem" }}>Evaluated Skills:</strong>
                        <div style={{ marginTop: "0.35rem", display: "flex", flexDirection: "column", gap: "0.4rem" }}>
                          {feedback.skills.map((s) => (
                            <div key={s.id} style={{ display: "flex", justifyContent: "space-between", fontSize: "0.8rem", background: "var(--paper)", padding: "0.4rem 0.75rem", borderRadius: "6px", border: "1px solid var(--line)" }}>
                              <span><strong>{s.skill_name || s.skill_id}</strong></span>
                              <span>Expected: {s.expected_level != null ? `${Math.round(s.expected_level * 100)}%` : "—"} | Observed: {s.observed_level != null ? `${Math.round(s.observed_level * 100)}%` : "—"}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                ) : !["interview", "offer_received", "selected", "rejected"].includes(detail.status) ? (
                  <div style={{ padding: "2rem", textAlign: "center", color: "var(--muted)" }}>
                    Candidate evaluation and summative feedback becomes accessible once the candidate advances to Interview stage.
                  </div>
                ) : (
                  <form onSubmit={handleSubmitFeedback}>
                    <h4 style={{ fontSize: "1rem", fontWeight: 700, margin: "0 0 0.5rem" }}>
                      Candidate Structured Evaluation Form
                    </h4>
                    <p style={{ fontSize: "0.85rem", color: "var(--muted)", marginBottom: "1rem" }}>
                      Provide ratings (1 to 5) and observations. This feedback serves as the authoritative evaluation record.
                    </p>

                    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: "0.75rem", marginBottom: "1rem" }}>
                      <div className="emp-field">
                        <label className="emp-label">Overall (1-5)</label>
                        <input className="emp-input" type="number" min="1" max="5" value={fbOverall} onChange={(e) => setFbOverall(Number(e.target.value))} required />
                      </div>
                      <div className="emp-field">
                        <label className="emp-label">Technical (1-5)</label>
                        <input className="emp-input" type="number" min="1" max="5" value={fbTech} onChange={(e) => setFbTech(Number(e.target.value))} required />
                      </div>
                      <div className="emp-field">
                        <label className="emp-label">Communication (1-5)</label>
                        <input className="emp-input" type="number" min="1" max="5" value={fbComm} onChange={(e) => setFbComm(Number(e.target.value))} required />
                      </div>
                      <div className="emp-field">
                        <label className="emp-label">Problem Solving (1-5)</label>
                        <input className="emp-input" type="number" min="1" max="5" value={fbProblem} onChange={(e) => setFbProblem(Number(e.target.value))} required />
                      </div>
                      <div className="emp-field">
                        <label className="emp-label">Project Readiness</label>
                        <input className="emp-input" type="number" min="1" max="5" value={fbProject} onChange={(e) => setFbProject(Number(e.target.value))} required />
                      </div>
                      <div className="emp-field">
                        <label className="emp-label">Role Readiness</label>
                        <input className="emp-input" type="number" min="1" max="5" value={fbRole} onChange={(e) => setFbRole(Number(e.target.value))} required />
                      </div>
                    </div>

                    <div className="emp-field" style={{ marginBottom: "0.75rem" }}>
                      <label className="emp-label">Interview Summary</label>
                      <textarea
                        className="emp-textarea"
                        rows={2}
                        placeholder="Key interview highlights, problem solving approach..."
                        value={fbSummary}
                        onChange={(e) => setFbSummary(e.target.value)}
                      />
                    </div>

                    <div className="emp-field" style={{ marginBottom: "1rem" }}>
                      <label className="emp-label">Overall Recommendation / Decision Comments</label>
                      <textarea
                        className="emp-textarea"
                        rows={2}
                        placeholder="Final recommendation, strengths and identified areas for training..."
                        value={fbComment}
                        onChange={(e) => setFbComment(e.target.value)}
                      />
                    </div>

                    <button
                      type="submit"
                      className="emp-btn emp-btn--primary"
                      disabled={submittingFeedback}
                    >
                      {submittingFeedback ? "Saving Evaluation…" : "Submit Summative Feedback"}
                    </button>
                  </form>
                )}
              </div>
            )}

            {/* TAB 4: PLACEMENT & JOINING (Section 15) */}
            {tab === "placement" && (
              <div>
                <h4 style={{ fontSize: "1rem", fontWeight: 700, margin: "0 0 0.5rem" }}>
                  Placement &amp; Joining Verification
                </h4>

                {candidatePlacement ? (
                  <div style={{ background: "var(--paper-2, #f8fafc)", padding: "1.25rem", borderRadius: "10px", border: "1px solid var(--line)" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
                      <div>
                        <div style={{ fontSize: "1.05rem", fontWeight: 700 }}>{candidatePlacement.role_title}</div>
                        <div style={{ fontSize: "0.85rem", color: "var(--muted)" }}>
                          Joining Date: <strong>{candidatePlacement.joining_date ? new Date(candidatePlacement.joining_date).toLocaleDateString() : "Pending"}</strong>
                        </div>
                      </div>
                      <div style={{ display: "flex", gap: "0.5rem" }}>
                        <span className={`emp-badge emp-badge--${candidatePlacement.status}`}>
                          {formatStatusLabel(candidatePlacement.status)}
                        </span>
                        <span className={`emp-badge emp-badge--${candidatePlacement.verification_status === "verified" ? "open" : "suspended"}`}>
                          {candidatePlacement.verification_status}
                        </span>
                      </div>
                    </div>

                    <div style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem", alignItems: "center", borderTop: "1px solid var(--line)", paddingTop: "0.75rem" }}>
                      {candidatePlacement.verification_status !== "verified" && (
                        <button
                          type="button"
                          className="emp-btn emp-btn--primary emp-btn--sm"
                          disabled={savingPlacement}
                          onClick={() => handleConfirmPlacement(candidatePlacement.id, true)}
                        >
                          ✓ Confirm &amp; Verify Placement
                        </button>
                      )}
                      {candidatePlacement.verification_status !== "disputed" && candidatePlacement.verification_status !== "verified" && (
                        <button
                          type="button"
                          className="emp-btn emp-btn--secondary emp-btn--sm"
                          disabled={savingPlacement}
                          onClick={() => handleConfirmPlacement(candidatePlacement.id, false)}
                        >
                          Mark Disputed
                        </button>
                      )}
                      {candidatePlacement.status !== "joined" && (
                        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                          <input
                            type="date"
                            className="emp-input"
                            style={{ padding: "0.3rem 0.5rem", fontSize: "0.8rem" }}
                            value={joiningDate}
                            onChange={(e) => setJoiningDate(e.target.value)}
                          />
                          <button
                            type="button"
                            className="emp-btn emp-btn--secondary emp-btn--sm"
                            disabled={savingPlacement || !joiningDate}
                            onClick={() => handleUpdatePlacementStatus(candidatePlacement.id, "joined", joiningDate)}
                          >
                            Mark Joined
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                ) : detail.status === "selected" ? (
                  <div style={{ background: "var(--paper-2, #f8fafc)", padding: "1.25rem", borderRadius: "10px", border: "1px solid var(--line)" }}>
                    <p style={{ fontSize: "0.85rem", color: "var(--muted)", margin: "0 0 1rem" }}>
                      This candidate is selected. You can now establish the official placement record and specify the expected joining date.
                    </p>
                    <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", flexWrap: "wrap" }}>
                      <input
                        type="date"
                        className="emp-input"
                        placeholder="Expected Joining Date"
                        value={joiningDate}
                        onChange={(e) => setJoiningDate(e.target.value)}
                      />
                      <button
                        type="button"
                        className="emp-btn emp-btn--primary"
                        disabled={savingPlacement}
                        onClick={handleCreatePlacement}
                      >
                        {savingPlacement ? "Creating Record…" : "Create Placement Record"}
                      </button>
                    </div>
                  </div>
                ) : (
                  <div style={{ padding: "2rem", textAlign: "center", color: "var(--muted)" }}>
                    Placement records are generated once the candidate reaches the <strong>Selected</strong> stage.
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
