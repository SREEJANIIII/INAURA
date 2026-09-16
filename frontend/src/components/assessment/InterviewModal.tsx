import { useEffect, useRef, useState } from "react";
import Button from "../ui/Button";
import {
  completeSkillInterview,
  startSkillInterview,
  submitInterviewResponses,
  type CompleteInterviewResponse,
  type StartInterviewResponse,
} from "../../services/assessment";
import "./InterviewModal.css";

type Props = {
  skill: string;
  onClose: () => void;
  /** Called after grading completes so the parent can refresh the analysis. */
  onCompleted?: (result: CompleteInterviewResponse) => void;
};

type Step = "intro" | "media" | "questions" | "result";

type MediaState = {
  camera: "unknown" | "ok" | "denied" | "unavailable" | "skipped";
  microphone: "unknown" | "ok" | "denied" | "unavailable" | "skipped";
  message?: string;
};

function stopStream(stream: MediaStream | null) {
  stream?.getTracks().forEach((t) => {
    try {
      t.stop();
    } catch {
      // ignore
    }
  });
}

export default function InterviewModal({ skill, onClose, onCompleted }: Props) {
  const [step, setStep] = useState<Step>("intro");
  const [session, setSession] = useState<StartInterviewResponse | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [activeIdx, setActiveIdx] = useState(0);
  const [result, setResult] = useState<CompleteInterviewResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [media, setMedia] = useState<MediaState>({ camera: "unknown", microphone: "unknown" });
  const [hasPreview, setHasPreview] = useState(false);
  const [micLevel, setMicLevel] = useState(0);
  const streamRef = useRef<MediaStream | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const rafRef = useRef<number | null>(null);

  // Always release camera/mic on unmount. Nothing is recorded or uploaded —
  // the stream is a local preview only.
  useEffect(() => {
    return () => {
      stopStream(streamRef.current);
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
      void audioCtxRef.current?.close().catch(() => undefined);
    };
  }, []);

  const checkMedia = async () => {
    setError(null);
    setMedia({ camera: "unknown", microphone: "unknown" });
    if (!navigator.mediaDevices?.getUserMedia) {
      setMedia({
        camera: "unavailable",
        microphone: "unavailable",
        message: "This device or browser does not support camera/microphone access.",
      });
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
      stopStream(streamRef.current);
      streamRef.current = stream;
      const hasVideo = stream.getVideoTracks().length > 0;
      const hasAudio = stream.getAudioTracks().length > 0;
      setHasPreview(hasVideo);
      setMedia({
        camera: hasVideo ? "ok" : "unavailable",
        microphone: hasAudio ? "ok" : "unavailable",
      });
      if (videoRef.current && hasVideo) {
        videoRef.current.srcObject = stream;
      }
      if (hasAudio) startMicMeter(stream);
    } catch (e) {
      const name = e instanceof DOMException ? e.name : "";
      const denied = name === "NotAllowedError" || name === "SecurityError";
      setMedia({
        camera: denied ? "denied" : "unavailable",
        microphone: denied ? "denied" : "unavailable",
        message: denied
          ? "Permission was denied. You can continue without camera and microphone."
          : "Camera/microphone are unavailable. You can continue without them.",
      });
    }
  };

  const startMicMeter = (stream: MediaStream) => {
    try {
      const Ctx = window.AudioContext;
      if (!Ctx) return;
      const ctx = new Ctx();
      audioCtxRef.current = ctx;
      const src = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 256;
      src.connect(analyser);
      const data = new Uint8Array(analyser.frequencyBinCount);
      const tick = () => {
        analyser.getByteTimeDomainData(data);
        let sum = 0;
        for (let i = 0; i < data.length; i++) {
          const v = (data[i] - 128) / 128;
          sum += v * v;
        }
        setMicLevel(Math.min(1, Math.sqrt(sum / data.length) * 3));
        rafRef.current = requestAnimationFrame(tick);
      };
      tick();
    } catch {
      // meter is best-effort only
    }
  };

  const beginInterview = async (withMedia: boolean) => {
    if (!withMedia) {
      stopStream(streamRef.current);
      streamRef.current = null;
      setHasPreview(false);
      if (videoRef.current) videoRef.current.srcObject = null;
    }
    setLoading(true);
    setError(null);
    try {
      const data = await startSkillInterview(skill);
      setSession(data);
      setStep("questions");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start the interview");
    } finally {
      setLoading(false);
    }
  };

  const questions = session?.plan.questions ?? [];
  const activeQ = questions[activeIdx];
  const answeredCount = questions.filter((q) => (answers[q.id] || "").trim().length > 0).length;

  const finishInterview = async () => {
    if (!session || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      await submitInterviewResponses(session.session_id, answers);
      const graded = await completeSkillInterview(session.session_id);
      setResult(graded);
      setStep("result");
      stopStream(streamRef.current);
      streamRef.current = null;
      onCompleted?.(graded);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not finish the interview");
    } finally {
      setSubmitting(false);
    }
  };

  const pct = (v: number | null | undefined) =>
    v === null || v === undefined ? "—" : `${Math.round(v * 100)}%`;

  const mediaLabel = (s: MediaState["camera"]) =>
    s === "ok" ? "Ready ✓" : s === "denied" ? "Denied" : s === "skipped" ? "Skipped" : s === "unavailable" ? "Unavailable" : "Not checked";

  return (
    <div className="iv__overlay" role="dialog" aria-modal="true" aria-label={`${skill} AI skill interview`}>
      <div className="iv__modal">
        <header className="iv__header">
          <div>
            <div className="iv__eyebrow">🎤 {skill} Skill Interview</div>
            <h2 className="iv__title">
              {step === "intro" && "Explain your reasoning"}
              {step === "media" && "Camera & microphone check"}
              {step === "questions" && `Question ${Math.min(activeIdx + 1, questions.length)} of ${questions.length}`}
              {step === "result" && "Interview complete ✓"}
            </h2>
          </div>
          <button className="iv__close" onClick={onClose} aria-label="Close interview">
            ×
          </button>
        </header>

        {step === "intro" && (
          <>
            <p className="iv__lede">
              ~{session?.plan.estimated_minutes ?? 10} minutes · skill-specific questions about {skill},
              adapted to your evidence and assessment results.
            </p>
            <div className="iv__dims">
              <div>
                <strong>INAURA will evaluate:</strong>
                <ul>
                  <li>Technical reasoning</li>
                  <li>Practical understanding</li>
                  <li>Technical communication (scored separately)</li>
                </ul>
              </div>
            </div>
            <p className="iv__privacy">
              Camera + microphone are used for a presence check only. Your preview stays on this
              device — INAURA does not store video or audio. Only your written answers are saved.
              You can continue without camera access.
            </p>
            <div className="iv__footer">
              <span className="iv__hint">Show INAURA that you can explain and defend your work.</span>
              <Button onClick={() => setStep("media")}>Check camera &amp; microphone</Button>
            </div>
          </>
        )}

        {step === "media" && (
          <>
            <div className="iv__media-grid">
              <div className="iv__media-box">
                <video ref={videoRef} autoPlay muted playsInline className="iv__preview" aria-label="Camera preview" />
                {!hasPreview && <div className="iv__preview-empty">No preview yet</div>}
              </div>
              <div className="iv__media-status">
                <div>
                  Camera: <strong>{mediaLabel(media.camera)}</strong>
                </div>
                <div>
                  Microphone: <strong>{mediaLabel(media.microphone)}</strong>
                </div>
                {media.microphone === "ok" && (
                  <div className="iv__meter" aria-label="Microphone level">
                    <div className="iv__meter-fill" style={{ width: `${Math.round(micLevel * 100)}%` }} />
                  </div>
                )}
                {media.message && <div className="iv__media-msg">{media.message}</div>}
              </div>
            </div>
            {error && <div className="iv__error">{error}</div>}
            <div className="iv__footer">
              <Button onClick={checkMedia}>Recheck devices</Button>
              <Button
                onClick={() => {
                  setMedia((m) => ({ ...m, camera: "skipped", microphone: "skipped" }));
                  void beginInterview(false);
                }}
                disabled={loading}
              >
                Continue without camera
              </Button>
              <Button onClick={() => void beginInterview(true)} disabled={loading}>
                {loading ? "Starting…" : "Start interview"}
              </Button>
            </div>
          </>
        )}

        {step === "questions" && session && activeQ && (
          <>
            <div className="iv__progress">
              Answered {answeredCount}/{questions.length}
            </div>
            <p className="iv__prompt">{activeQ.prompt}</p>
            <label className="iv__label" htmlFor="iv-answer">
              Your answer (content and structure are evaluated — never appearance)
            </label>
            <textarea
              id="iv-answer"
              className="iv__answer"
              value={answers[activeQ.id] || ""}
              onChange={(e) => setAnswers((a) => ({ ...a, [activeQ.id]: e.target.value }))}
              rows={7}
              placeholder="Explain your reasoning…"
            />
            {activeQ.follow_ups.length > 0 && (
              <details className="iv__followups">
                <summary>Possible follow-ups INAURA may explore</summary>
                <ul>
                  {activeQ.follow_ups.map((f, i) => (
                    <li key={i}>{f}</li>
                  ))}
                </ul>
              </details>
            )}
            {error && <div className="iv__error">{error}</div>}
            <div className="iv__footer">
              <Button onClick={() => setActiveIdx((i) => Math.max(0, i - 1))} disabled={activeIdx === 0}>
                Back
              </Button>
              {activeIdx < questions.length - 1 ? (
                <Button onClick={() => setActiveIdx((i) => i + 1)}>Next</Button>
              ) : (
                <Button onClick={() => void finishInterview()} disabled={submitting}>
                  {submitting ? "Finishing…" : "Finish interview"}
                </Button>
              )}
            </div>
          </>
        )}

        {step === "result" && result && (
          <div className="iv__result">
            {result.status === "graded" ? (
              <>
                <div className="iv__scores">
                  <div>
                    <strong>Technical reasoning:</strong> {pct(result.technical_scores?.overall)}
                  </div>
                  {result.communication_scores && (
                    <div>
                      <strong>Technical communication:</strong> {pct(result.communication_scores.overall)}
                    </div>
                  )}
                </div>
                {result.technical_scores && (
                  <ul className="iv__breakdown">
                    {Object.entries(result.technical_scores.per_competency).map(([k, v]) => (
                      <li key={k}>
                        {k}: <strong>{pct(v)}</strong>
                      </li>
                    ))}
                  </ul>
                )}
                {result.note && <p className="iv__note">{result.note}</p>}
                <p className="iv__note iv__note--ok">Assessment evidence added to your skill profile.</p>
              </>
            ) : (
              <>
                <p className="iv__note">
                  {result.status === "awaiting_review"
                    ? "Your answers are saved. Grading is not configured yet, so this interview is awaiting review and does not change your skill profile."
                    : result.note || "INAURA found limited evidence of implementation understanding."}
                </p>
              </>
            )}
            <div className="iv__footer">
              <span className="iv__hint">
                The interview is one evidence source among your GitHub, projects, and assessments.
              </span>
              <Button onClick={onClose}>Done</Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
