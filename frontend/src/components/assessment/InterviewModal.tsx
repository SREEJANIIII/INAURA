import { useCallback, useEffect, useRef, useState } from "react";
import Button from "../ui/Button";
import {
  answerInterviewQuestion,
  completeSkillInterview,
  getSkillInterview,
  startSkillInterview,
  type CompleteInterviewResponse,
  type StartInterviewResponse,
} from "../../services/assessment";
import { useMediaDevices } from "../../hooks/useMediaDevices";
import { useSpeechRecognition } from "../../hooks/useSpeechRecognition";
import { useTextToSpeech } from "../../hooks/useTextToSpeech";
import "./InterviewModal.css";

type Props = {
  skill: string;
  onClose: () => void;
  onCompleted?: (result: CompleteInterviewResponse) => void;
};

type Phase =
  | "intro"
  | "initializing"
  | "ai_speaking"
  | "listening"
  | "processing"
  | "completing"
  | "completed"
  | "error";

type Question = {
  id: string;
  competency: string;
  prompt: string;
  follow_ups: string[];
};

const SILENCE_TIMEOUT_MS = 4000;

export default function InterviewModal({ skill, onClose, onCompleted }: Props) {
  const [phase, setPhase] = useState<Phase>("intro");
  const [session, setSession] = useState<StartInterviewResponse | null>(null);
  const [currentQuestion, setCurrentQuestion] = useState<Question | null>(null);
  const [totalQuestions, setTotalQuestions] = useState(0);
  const [answeredCount, setAnsweredCount] = useState(0);

  const [aiText, setAiText] = useState("");
  const [typedAnswer, setTypedAnswer] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const [result, setResult] = useState<CompleteInterviewResponse | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(
    () => sessionStorage.getItem("interview_session_id")
  );

  const {
    videoRef,
    camState,
    micState,
    micLevel,
    micEnabled,
    cameraEnabled,
    requestMedia,
    requestCamera,
    requestMicrophone,
    toggleMic,
    toggleCamera,
    stopAll: stopMedia,
  } = useMediaDevices();

  const tts = useTextToSpeech();
  const speech = useSpeechRecognition({ silenceTimeout: SILENCE_TIMEOUT_MS });

  const phaseRef = useRef(phase);
  const currentQuestionRef = useRef(currentQuestion);
  const sessionRef = useRef(session);
  const interviewActiveRef = useRef(false);
  const ttsRef = useRef(tts);
  const speechRef = useRef(speech);

  useEffect(() => { phaseRef.current = phase; });
  useEffect(() => { currentQuestionRef.current = currentQuestion; });
  useEffect(() => { sessionRef.current = session; });
  useEffect(() => { ttsRef.current = tts; });
  useEffect(() => { speechRef.current = speech; });

  // Cleanup on unmount
  useEffect(() => () => {
    interviewActiveRef.current = false;
    tts.stop();
    speech.stop();
    stopMedia();
    sessionStorage.removeItem("interview_session_id");
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---- Speak then listen: guarded async transition ----
  const speakThenListen = useCallback(async (text: string) => {
    if (!interviewActiveRef.current) return;
    setAiText(text);
    setPhase("ai_speaking");
    await ttsRef.current.speak(text);
    if (!interviewActiveRef.current) return;
    setAiText("");
    if (phaseRef.current === "ai_speaking" && interviewActiveRef.current) {
      setPhase("listening");
      speechRef.current.start();
    }
  }, []);

  // ---- Submit answer to backend ----
  const submitAnswer = useCallback(async (transcript: string) => {
    if (!interviewActiveRef.current) return;
    const sess = sessionRef.current;
    const q = currentQuestionRef.current;
    if (!sess || !q || !transcript.trim()) return;

    setPhase("processing");

    try {
      const res = await answerInterviewQuestion(sess.session_id, q.id, transcript.trim());
      if (!interviewActiveRef.current) return;
      setAnsweredCount(res.answered_count);

      if (res.completed || res.next_action === "complete" || !res.current_question) {
        setPhase("completing");
        const graded = await completeSkillInterview(sess.session_id);
        if (!interviewActiveRef.current) return;
        sessionStorage.removeItem("interview_session_id");
        interviewActiveRef.current = false;
        stopMedia();
        setResult(graded);
        setPhase("completed");
        onCompleted?.(graded);
        return;
      }

      const nextQ = res.current_question;
      let spokenText = "";
      if (res.evaluation?.follow_up_needed && res.evaluation.suggested_follow_up) {
        spokenText = res.evaluation.suggested_follow_up;
      } else if (nextQ) {
        spokenText = nextQ.prompt;
      }

      setCurrentQuestion(nextQ);
      speechRef.current.reset();
      await speakThenListen(spokenText);
    } catch (e) {
      if (!interviewActiveRef.current) return;
      const msg = e instanceof Error ? e.message : "Could not submit answer";
      if (msg.includes("409") || msg.includes("not the current question")) {
        setError("Session out of sync. Recovering...");
        setSessionId(sessionRef.current?.session_id || null);
      } else {
        setError(msg);
        setPhase("error");
      }
    }
  }, [speakThenListen, stopMedia, onCompleted]);

  // ---- Wire silence → submitAnswer ----
  useEffect(() => {
    speech.setOnSilence((transcript: string) => {
      void submitAnswer(transcript);
    });
  }, [speech, submitAnswer]);

  // ---- Session recovery on browser refresh ----
  useEffect(() => {
    if (!sessionId) return;
    let active = true;
    (async () => {
      try {
        const data = await getSkillInterview(sessionId);
        if (!active) return;
        if (["completed", "graded", "awaiting_review"].includes(data.status)) {
          const graded = await completeSkillInterview(sessionId);
          if (active) { setResult(graded); setPhase("completed"); }
          return;
        }
        setSession({
          session_id: data.session_id || sessionId,
          skill: data.skill || skill,
          skill_key: skill,
          interview_version: "interview-v2",
          status: data.status,
          started_at: data.started_at || "",
          plan: data.plan as StartInterviewResponse["plan"],
          evaluated_dimensions: {},
          privacy_notice: "",
          disclaimer: "",
        });
        const plan = data.plan as Record<string, unknown>;
        const questions = (plan?.questions ?? []) as Question[];
        const idx = (data as Record<string, unknown>).current_index as number ?? 0;
        setTotalQuestions(questions.length);
        setAnsweredCount(
          (data.transcript as Array<Record<string, unknown>> | undefined || [])
            .filter((t) => t.answer).length
        );
        if (questions[idx]) {
          setCurrentQuestion(questions[idx]);
          if (active) {
            setPhase("intro");
            void requestMedia();
          }
        } else {
          const graded = await completeSkillInterview(sessionId);
          if (active) { setResult(graded); setPhase("completed"); }
        }
      } catch {
        if (active) {
          sessionStorage.removeItem("interview_session_id");
          setSessionId(null);
        }
      }
    })();
    return () => { active = false; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, skill]);

  // ---- Start the interview ----
  const beginInterview = useCallback(async () => {
    if (interviewActiveRef.current) return;
    interviewActiveRef.current = true;
    setLoading(true);
    setError(null);

    await requestMedia();
    if (!interviewActiveRef.current) { setLoading(false); return; }

    try {
      const data = await startSkillInterview(skill);
      if (!interviewActiveRef.current) { setLoading(false); return; }
      setSession(data);
      sessionStorage.setItem("interview_session_id", data.session_id);
      setSessionId(data.session_id);

      const questions = data.plan.questions || [];
      setTotalQuestions(questions.length);
      setAnsweredCount(0);

      if (questions.length === 0) {
        setError("No questions generated for this skill.");
        setLoading(false);
        interviewActiveRef.current = false;
        return;
      }

      const firstQ = questions[0];
      setCurrentQuestion(firstQ);
      setLoading(false);
      speechRef.current.reset();

      const greeting = `Hi! I'm your INAURA AI interviewer. I've reviewed your profile and we'll focus on ${skill} today. Let's begin. ${firstQ.prompt}`;
      await speakThenListen(greeting);
    } catch (e) {
      if (!interviewActiveRef.current) return;
      setError(e instanceof Error ? e.message : "Could not start the interview");
      setLoading(false);
    }
  }, [skill, requestMedia, speakThenListen]);

  // ---- Manual typed submit (fallback) ----
  const submitTyped = useCallback(() => {
    if (typedAnswer.trim()) {
      speech.stop();
      void submitAnswer(typedAnswer);
      setTypedAnswer("");
    }
  }, [typedAnswer, speech, submitAnswer]);

  // ---- End interview ----
  const endInterview = useCallback(async () => {
    interviewActiveRef.current = false;
    tts.stop();
    speech.stop();
    const sess = sessionRef.current;
    if (sess) {
      try {
        setPhase("completing");
        const graded = await completeSkillInterview(sess.session_id);
        setResult(graded);
        sessionStorage.removeItem("interview_session_id");
        stopMedia();
        setPhase("completed");
        onCompleted?.(graded);
      } catch {
        stopMedia();
        setPhase("completed");
      }
    } else {
      stopMedia();
      setPhase("completed");
    }
  }, [tts, speech, stopMedia, onCompleted]);

  // ---- Repeat question ----
  const repeatQuestion = useCallback(() => {
    const q = currentQuestionRef.current;
    if (!q || !interviewActiveRef.current) return;
    tts.stop();
    speech.stop();
    speech.reset();
    void speakThenListen(q.prompt);
  }, [tts, speech, speakThenListen]);

  // ---- Retry devices ----
  const recheckCamera = useCallback(async () => {
    setError(null);
    await requestCamera();
  }, [requestCamera]);

  const recheckMicrophone = useCallback(async () => {
    setError(null);
    await requestMicrophone();
  }, [requestMicrophone]);

  const liveCaption = phase === "listening" ? speech.liveTranscript : "";
  const progress = totalQuestions > 0 ? Math.round((answeredCount / totalQuestions) * 100) : 0;
  const skillDisplay = session?.skill || skill;
  const isActive = phase === "ai_speaking" || phase === "listening" || phase === "processing";
  const camFailed = camState === "denied" || camState === "unavailable";
  const micFailed = micState === "denied" || micState === "unavailable";

  return (
    <div className="iv__overlay" role="dialog" aria-modal="true" aria-label={`${skill} live AI interview`}>

      {/* ===== INTRO SCREEN ===== */}
      {phase === "intro" && (
        <div className="iv__intro">
          <div className="iv__intro-card">
            <div className="iv__intro-icon">🎙</div>
            <h1 className="iv__intro-title">INAURA AI Interview</h1>
            <p className="iv__intro-skill">{skill}</p>
            <p className="iv__intro-desc">
              This is a live AI interview. The interviewer will ask questions
              verbally and adapt based on your answers.
            </p>
            <p className="iv__intro-req">
              Camera + microphone are required for the live interview experience.
            </p>
            <Button
              onClick={() => void beginInterview()}
              variant="primary"
              size="lg"
              disabled={loading}
            >
              {loading ? "Starting..." : "Let's Begin"}
            </Button>
            {error && (
              <div className="iv__intro-error" role="alert">{error}</div>
            )}
          </div>
        </div>
      )}

      {/* ===== CALL SCREEN ===== */}
      {phase !== "intro" && phase !== "completed" && (
        <div className="iv__call">
          <header className="iv__call-header">
            <div className="iv__call-brand">
              <span className="iv__call-logo">INAURA</span>
              <span className="iv__call-skill">{skillDisplay}</span>
            </div>
            <div className="iv__call-status">
              {phase === "ai_speaking" && <span className="iv__status-dot iv__status-dot--ai" />}
              {phase === "listening" && <span className="iv__status-dot iv__status-dot--mic" />}
              {phase === "processing" && <span className="iv__status-dot iv__status-dot--proc" />}
              <span className="iv__status-label">
                {phase === "initializing" && "Connecting..."}
                {phase === "ai_speaking" && "AI is speaking"}
                {phase === "listening" && "Listening..."}
                {phase === "processing" && "Analyzing your response..."}
                {phase === "completing" && "Building your report..."}
                {phase === "error" && "Error"}
              </span>
            </div>
            <div className="iv__call-progress">
              <div className="iv__call-progress-bar">
                <div className="iv__call-progress-fill" style={{ width: `${progress}%` }} />
              </div>
              <span className="iv__call-progress-text">{answeredCount}/{totalQuestions}</span>
            </div>
          </header>

          {error && (
            <div className="iv__error" role="alert">
              <span>{error}</span>
              <button className="iv__error-dismiss" onClick={() => setError(null)} aria-label="Dismiss">×</button>
            </div>
          )}

          {camFailed && isActive && (
            <div className="iv__device-banner iv__device-banner--warn">
              <span>Camera unavailable</span>
              <Button onClick={recheckCamera} variant="secondary" size="sm">Recheck camera</Button>
              <span className="iv__device-banner-note">Continuing with audio only.</span>
            </div>
          )}
          {micFailed && isActive && (
            <div className="iv__device-banner iv__device-banner--warn">
              <span>Microphone unavailable</span>
              <Button onClick={recheckMicrophone} variant="secondary" size="sm">Recheck mic</Button>
            </div>
          )}

          <div className="iv__call-body">
            <div className="iv__call-panel iv__call-panel--ai">
              <div className="iv__call-avatar">
                <div className={`iv__avatar-ring ${phase === "ai_speaking" ? "iv__avatar-ring--active" : ""}`}>
                  <span className="iv__avatar-icon">🤖</span>
                </div>
              </div>
              <div className="iv__call-panel-label">INAURA AI</div>
              {phase === "ai_speaking" && aiText && (
                <div className="iv__call-bubble iv__call-bubble--ai" aria-live="polite">{aiText}</div>
              )}
              {phase === "processing" && (
                <div className="iv__call-bubble iv__call-bubble--ai iv__call-bubble--muted">
                  <div className="iv__call-dots"><span /><span /><span /></div>
                </div>
              )}
            </div>

            <div className="iv__call-panel iv__call-panel--user">
              <div className="iv__call-camera">
                <video ref={videoRef} autoPlay muted playsInline className="iv__call-video" aria-label="Your camera preview" />
                {camState !== "live" && (
                  <div className="iv__call-camera-off">
                    <span>📹</span>
                    <span>{camFailed ? "Camera unavailable" : "Camera off"}</span>
                  </div>
                )}
                {phase === "listening" && !micFailed && (
                  <div className="iv__call-listening-badge">
                    <div className="iv__pulse" />
                    <div className="iv__call-mic-meter">
                      <div className="iv__call-mic-meter-fill" style={{ width: `${Math.round(micLevel * 100)}%` }} />
                    </div>
                    <span>Listening</span>
                  </div>
                )}
              </div>
              <div className="iv__call-panel-label">You</div>
            </div>
          </div>

          <div className="iv__call-caption" aria-live="polite">
            {phase === "listening" && liveCaption && (
              <span className="iv__call-caption-text">{liveCaption}</span>
            )}
            {phase === "listening" && !liveCaption && (
              <span className="iv__call-caption-hint">Speak now...</span>
            )}
            {phase === "ai_speaking" && aiText && (
              <span className="iv__call-caption-text iv__call-caption-text--ai">{aiText}</span>
            )}
            {phase === "processing" && (
              <span className="iv__call-caption-hint">Evaluating your response...</span>
            )}
          </div>

          {!speech.isSupported && phase === "listening" && (
            <div className="iv__call-typed">
              <input
                className="iv__call-typed-input"
                value={typedAnswer}
                onChange={(e) => setTypedAnswer(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submitTyped(); } }}
                placeholder="Type your answer here..."
                autoFocus
                aria-label="Type your answer"
              />
              <Button variant="primary" size="sm" onClick={submitTyped} disabled={!typedAnswer.trim()}>
                Send
              </Button>
            </div>
          )}

          <footer className="iv__call-controls">
            {phase === "initializing" && (
              <div className="iv__call-completing">
                <div className="iv__spinner" />
                <span>Setting up your interview...</span>
              </div>
            )}

            {isActive && (
              <>
                <Button onClick={toggleMic} variant={micEnabled ? "secondary" : "accent"} size="md"
                  aria-label={micEnabled ? "Mute microphone" : "Unmute microphone"}>
                  {micEnabled ? "🎙 Mute" : "🔇 Unmute"}
                </Button>
                <Button onClick={toggleCamera} variant={cameraEnabled ? "secondary" : "accent"} size="md"
                  aria-label={cameraEnabled ? "Turn off camera" : "Turn on camera"}>
                  {cameraEnabled ? "📷 Camera" : "📷 Camera off"}
                </Button>
                <Button onClick={repeatQuestion} variant="secondary" size="md">↻ Repeat</Button>
                <Button onClick={() => void endInterview()} variant="ghost" size="md">End</Button>
              </>
            )}

            {phase === "processing" && (
              <>
                <Button onClick={toggleMic} variant="secondary" size="md" disabled>Muted</Button>
                <Button onClick={toggleCamera} variant={cameraEnabled ? "secondary" : "accent"} size="md">
                  {cameraEnabled ? "📷 Camera" : "📷 Camera off"}
                </Button>
                <Button onClick={repeatQuestion} variant="secondary" size="md" disabled>↻ Repeat</Button>
                <Button onClick={() => void endInterview()} variant="ghost" size="md">End</Button>
              </>
            )}

            {phase === "completing" && (
              <div className="iv__call-completing">
                <div className="iv__spinner" />
                <span>Building your interview report...</span>
              </div>
            )}

            {phase === "error" && (
              <>
                <Button onClick={() => void recheckCamera()} variant="secondary" size="md">Recheck camera</Button>
                <Button onClick={() => void recheckMicrophone()} variant="secondary" size="md">Recheck mic</Button>
                <Button onClick={() => void beginInterview()} variant="primary" size="md">Retry</Button>
                <Button onClick={() => void endInterview()} variant="ghost" size="md">End</Button>
              </>
            )}
          </footer>
        </div>
      )}

      {/* ===== COMPLETED REPORT ===== */}
      {phase === "completed" && result && (
        <div className="iv__report-overlay">
          <div className="iv__report">
            <h2 className="iv__report-title">Interview Complete</h2>
            {result.status === "graded" ? (
              <>
                <div className="iv__report-scores">
                  <div className="iv__report-score">
                    <span className="iv__report-score-value">
                      {result.technical_scores?.overall != null ? `${Math.round(result.technical_scores.overall * 100)}%` : "—"}
                    </span>
                    <span className="iv__report-score-label">Technical Reasoning</span>
                  </div>
                  {result.communication_scores && (
                    <div className="iv__report-score">
                      <span className="iv__report-score-value">{`${Math.round(result.communication_scores.overall * 100)}%`}</span>
                      <span className="iv__report-score-label">Communication</span>
                    </div>
                  )}
                </div>
                {result.technical_scores && (
                  <div className="iv__report-breakdown">
                    <h3>Per-Competency</h3>
                    <ul>
                      {Object.entries(result.technical_scores.per_competency).map(([k, v]) => (
                        <li key={k}>
                          <span>{k.replace(/_/g, " ")}</span>
                          <span className="iv__report-bar">
                            <span className="iv__report-bar-fill" style={{ width: `${Math.round(v * 100)}%` }} />
                          </span>
                          <span className="iv__report-pct">{Math.round(v * 100)}%</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {result.note && <p className="iv__report-note">{result.note}</p>}
                <p className="iv__report-note iv__report-note--ok">
                  Assessment evidence has been added to your skill profile.
                </p>
              </>
            ) : (
              <p className="iv__report-note">
                {result.status === "awaiting_review"
                  ? "Your interview is saved and awaiting review."
                  : result.note || "INAURA found limited evidence of implementation understanding."}
              </p>
            )}
            <p className="iv__report-fine">
              Interview evidence combines with your GitHub, projects, and assessments through
              INAURA&apos;s existing evidence model. The deterministic skill engine decides how this
              evidence affects your profile — not Gemini directly.
            </p>
            <div className="iv__report-actions">
              <Button onClick={onClose} variant="primary" size="lg">Done</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
