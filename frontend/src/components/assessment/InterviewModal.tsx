import { useCallback, useEffect, useRef, useState } from "react";
import Button from "../ui/app-button";
import {
  answerInterviewQuestion,
  completeSkillInterview,
  startSkillInterview,
  transcribeInterviewAudio,
  type CompleteInterviewResponse,
  type StartInterviewResponse,
} from "../../services/assessment";
import { useMediaDevices } from "../../hooks/useMediaDevices";
import { normalizeTechnicalTerms, useSpeechRecognition } from "../../hooks/useSpeechRecognition";
import { useInterviewAudioCapture } from "../../hooks/useInterviewAudioCapture";
import { useTextToSpeech } from "../../hooks/useTextToSpeech";
import { withTimeout } from "../../services/tts";
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
  | "device_error"
  | "recoverable_error"
  | "error";

type Question = {
  id: string;
  competency: string;
  prompt: string;
  follow_ups: string[];
};

/** What the AI interviewer calls itself, on screen and out loud. */
const INTERVIEWER_NAME = "Donald Duck";

const SILENCE_TIMEOUT_MS = 2800;
/** Watchdogs so no phase can wedge forever (backend budgets are shorter). */
const SPEAK_TIMEOUT_MS = 120000;
const SUBMIT_TIMEOUT_MS = 150000;

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

  const {
    videoRef,
    setVideoRef,
    camState,
    micState,
    micLevel,
    micEnabled,
    cameraEnabled,
    requestMedia,
    requestCamera,
    requestMicrophone,
    getAudioStream,
    toggleMic,
    toggleCamera,
    stopAll: stopMedia,
  } = useMediaDevices();

  const tts = useTextToSpeech();
  const speech = useSpeechRecognition({ silenceTimeout: SILENCE_TIMEOUT_MS });
  const audioCapture = useInterviewAudioCapture();

  const phaseRef = useRef(phase);
  const currentQuestionRef = useRef(currentQuestion);
  const sessionRef = useRef(session);
  const interviewActiveRef = useRef(false);
  const isSubmittingRef = useRef(false);
  const ttsRef = useRef(tts);
  const speechRef = useRef(speech);
  // Speech-turn generation: stale async continuations (older question's
  // audio/evaluation) can never advance a newer turn. Bumped on every new
  // speak flow and on explicit stops/repeats/retries.
  const turnRef = useRef(0);
  // Last submitted transcript, so a recoverable failure can retry the SAME
  // answer without asking the candidate to repeat themselves.
  const lastTranscriptRef = useRef("");
  const transcriptionBusyRef = useRef(false);
  const [submittedTranscript, setSubmittedTranscript] = useState("");

  useEffect(() => { phaseRef.current = phase; });
  useEffect(() => { currentQuestionRef.current = currentQuestion; });
  useEffect(() => { sessionRef.current = session; });
  useEffect(() => { ttsRef.current = tts; });
  useEffect(() => { speechRef.current = speech; });

  // Cleanup on unmount
  useEffect(() => () => {
    interviewActiveRef.current = false;
    isSubmittingRef.current = false;
    tts.stop();
    speech.stop();
    void audioCapture.stop();
    stopMedia();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Sync video element srcObject when mounted or camera state becomes active
  useEffect(() => {
    if (phase !== "intro" && phase !== "completed" && videoRef.current) {
      setVideoRef(videoRef.current);
    }
  }, [phase, camState, setVideoRef, videoRef]);

  const startListening = useCallback(() => {
    speechRef.current.reset();
    setSubmittedTranscript("");
    isSubmittingRef.current = false;
    setPhase("listening");
    speechRef.current.start();
    audioCapture.start(getAudioStream());
  }, [audioCapture, getAudioStream]);

  // ---- Speak one utterance with a watchdog: true = spoken, false = voice
  // failed gracefully (fallback UI), null = aborted (interview ended or a
  // newer turn superseded this one). Never hangs: the timeout forces a path.
  const speakOnce = useCallback(async (text: string): Promise<boolean | null> => {
    if (!interviewActiveRef.current) return null;
    try {
      await withTimeout(ttsRef.current.speak(text), SPEAK_TIMEOUT_MS);
      return interviewActiveRef.current ? true : null;
    } catch {
      if (!interviewActiveRef.current) return null;
      setError("Voice playback is unavailable. You can continue by speaking or typing your answer.");
      return false;
    }
  }, []);

  // ---- Speak then listen: guarded async transition ----
  // Voice is strictly an enhancement: if TTS fails, the session, the current
  // question, and speech recognition are preserved and the candidate answers
  // from the on-screen question text. TTS never consumes evaluation traffic.
  const speakThenListen = useCallback(async (text: string) => {
    if (!interviewActiveRef.current) return;
    const turn = ++turnRef.current;
    speechRef.current.stop();
    setAiText(text);
    setPhase("ai_speaking");
    const voice = await speakOnce(text);
    if (voice === null || turnRef.current !== turn) return;
    if (!interviewActiveRef.current) return;
    // On voice failure the question text stays on screen so it can still be
    // read and answered; on success it is cleared as before.
    if (voice) {
      setAiText("");
    }
    if (phaseRef.current === "ai_speaking" && interviewActiveRef.current && turnRef.current === turn) {
      startListening();
    }
  }, [speakOnce, startListening]);

  // ---- Submit answer to backend ----
  const submitAnswer = useCallback(async (transcript: string) => {
    if (!interviewActiveRef.current || isSubmittingRef.current) return;
    isSubmittingRef.current = true;

    const sess = sessionRef.current;
    const q = currentQuestionRef.current;
    if (!sess || !q) {
      isSubmittingRef.current = false;
      return;
    }

    const trimmed = transcript.trim();
    // Guard against empty speech: prompt candidate conversationally instead of submitting empty evidence
    if (!trimmed) {
      isSubmittingRef.current = false;
      await speakThenListen("I didn't catch that. Take your time and explain it in your own words.");
      return;
    }

    speechRef.current.stop();
    setPhase("processing");
    lastTranscriptRef.current = trimmed;

    try {
      const res = await withTimeout(
        answerInterviewQuestion(sess.session_id, q.id, trimmed),
        SUBMIT_TIMEOUT_MS
      );
      if (!interviewActiveRef.current) return;
      setAnsweredCount(res.answered_count);
      // The interview length is server-driven: the initial plan intentionally
      // contains only Q1, so questions.length === 1 must never be treated as
      // the complete interview. Track the server's authoritative total.
      setTotalQuestions((prev) => Math.max(prev, res.total_questions, res.answered_count));

      // Completion is decided by the server's explicit terminal state ONLY.
      // A missing current_question on a NON-terminal turn is a transport/race
      // gap — never a reason to end the interview (it previously ended the
      // interview right after Q1 because the single-question plan had no
      // second question generated yet).
      if (res.completed || res.next_action === "complete" || res.action === "COMPLETE") {
        const closing =
          res.spoken_response ||
          "Thank you. That concludes all questions for this interview. I am finalizing your evaluation now.";
        setPhase("ai_speaking");
        try {
          await withTimeout(ttsRef.current.speak(closing), SPEAK_TIMEOUT_MS);
        } catch {
          setError("Voice playback is unavailable. Finalizing your interview.");
        }
        if (!interviewActiveRef.current) return;

        setPhase("completing");
        const graded = await completeSkillInterview(sess.session_id);
        if (!interviewActiveRef.current) return;
        interviewActiveRef.current = false;
        stopMedia();
        setResult(graded);
        setPhase("completed");
        onCompleted?.(graded);
        return;
      }

      // Server says continue but sent no next question: stay in the
      // interview and offer a retry instead of silently completing.
      if (!res.current_question) {
        isSubmittingRef.current = false;
        setError("The next question didn't come through. Your answer is saved — you can retry.");
        setPhase("recoverable_error");
        return;
      }

      const nextQ = res.current_question;
      setCurrentQuestion(nextQ);

      // Ack and question are separate fields: voice each exactly once, in
      // order, then listen. The question renders on screen exactly once.
      const ack = (res.spoken_response || "").trim();
      const qprompt = (nextQ?.prompt || "").trim();
      if (!interviewActiveRef.current) return;
      const turn = ++turnRef.current;
      speechRef.current.stop();
      setAiText(qprompt);
      setPhase("ai_speaking");
      let voiceOk = true;
      if (ack) {
        const v = await speakOnce(ack);
        if (v === null || turnRef.current !== turn) return;
        if (!interviewActiveRef.current) return;
        voiceOk = v && voiceOk;
        if (qprompt) await new Promise((resolve) => setTimeout(resolve, 180));
      }
      if (qprompt) {
        const v = await speakOnce(qprompt);
        if (v === null || turnRef.current !== turn) return;
        if (!interviewActiveRef.current) return;
        voiceOk = v && voiceOk;
      }
      if (!interviewActiveRef.current || turnRef.current !== turn) return;
      if (voiceOk) {
        setAiText("");
      }
      if (phaseRef.current === "ai_speaking" && interviewActiveRef.current && turnRef.current === turn) {
        startListening();
      }
    } catch (e) {
      if (!interviewActiveRef.current) return;
      isSubmittingRef.current = false;
      const msg = e instanceof Error ? e.message : "Could not submit answer";
      // The backend distinguishes "still working on it" from "genuinely stuck";
      // only the second sort should end the call.
      if (msg.includes("answer_in_progress") || msg.includes("completion_in_progress")) {
        setError("Your answer is still being graded. Give it a few seconds, then retry.");
        setPhase("recoverable_error");
      } else if (msg.includes("duplicate_answer_conflict")) {
        setError("A different answer is already saved for this question. End the interview to see your report.");
        setPhase("error");
      } else if (msg.includes("not the current question")) {
        setError("The interview has already moved past that question. Retry the question or end the interview.");
        setPhase("error");
      } else if (msg.includes("409")) {
        setError("Session out of sync. Retry the question, or end the interview to keep what you've answered.");
        setPhase("error");
      } else if (msg.includes("Timed out")) {
        // Recovery path: the SAME answer can be retried — the backend
        // persisted it before evaluating, so nothing is lost.
        setError("The interview service is taking too long. Your answer is saved — you can retry.");
        setPhase("recoverable_error");
      } else {
        setError(msg);
        setPhase("error");
      }
    }
  }, [speakOnce, speakThenListen, startListening, stopMedia, onCompleted]);

  // ---- Wire silence → submitAnswer ----
  const submitCapturedAnswer = useCallback(async (browserTranscript: string) => {
    if (transcriptionBusyRef.current || isSubmittingRef.current) return;
    transcriptionBusyRef.current = true;
    setPhase("processing");
    let transcript = browserTranscript.trim();
    setSubmittedTranscript(transcript);
    try {
      const audio = await audioCapture.stop();
      if (audio && audio.size > 0) {
        try {
          const result = await transcribeInterviewAudio(audio, sessionRef.current?.session_id, currentQuestionRef.current?.id);
          if (result.text.trim()) {
            transcript = result.text.trim();
            setSubmittedTranscript(transcript);
          }
        } catch { /* browser STT remains the immediate fallback */ }
      }
      const words = transcript.split(/\s+/).filter(Boolean);
      if (words.length < 3 || transcript.replace(/\s/g, "").length < 12) {
        setError("Couldn't catch that clearly. Please try that answer again.");
        startListening();
        return;
      }
      // Speech recognition writes technical names phonetically ("fast api"); the
      // grader reads the words, so tidy them before the answer is sent.
      const cleaned = normalizeTechnicalTerms(transcript);
      setSubmittedTranscript(cleaned);
      await submitAnswer(cleaned);
    } finally {
      transcriptionBusyRef.current = false;
    }
  }, [audioCapture, startListening, submitAnswer]);

  useEffect(() => {
    speech.setOnSilence((transcript: string) => {
      if (phaseRef.current === "listening" && !isSubmittingRef.current) {
        void submitCapturedAnswer(transcript);
      }
    });
  }, [speech, submitCapturedAnswer]);

  // ---- Start the interview ----
  const beginInterview = useCallback(async () => {
    if (interviewActiveRef.current) return;
    interviewActiveRef.current = true;
    turnRef.current += 1;
    isSubmittingRef.current = false;
    setLoading(true);
    setError(null);
    // Immediately leave the intro screen to the live call screen
    setPhase("initializing");

    const mediaRes = await requestMedia();
    if (!interviewActiveRef.current) {
      setLoading(false);
      return;
    }

    if (!mediaRes.usable) {
      setError("Camera and microphone access are both unavailable. Please grant browser permissions to continue.");
      setPhase("device_error");
      setLoading(false);
      interviewActiveRef.current = false;
      return;
    }

    if (mediaRes.microphone !== "live") {
      setError("Microphone is required for the live interview. Please grant microphone permission.");
      setPhase("device_error");
      setLoading(false);
      interviewActiveRef.current = false;
      return;
    }

    try {
      // Device retries and browser recovery reuse the existing backend session.
      // Only the first successful start is allowed to create one. Whether this
      // attempt is a resume has to be read BEFORE the session is stored below,
      // or the greeting can never play.
      const resuming = sessionRef.current !== null;
      const data = sessionRef.current ?? await startSkillInterview(skill);
      if (!interviewActiveRef.current) {
        setLoading(false);
        return;
      }
      // Keep the authoritative session in a ref immediately. React state is
      // intentionally asynchronous and must not decide whether this attempt
      // creates a second session or which question is current.
      sessionRef.current = data;
      setSession(data);

      const questions = data.plan?.questions || [];
      // Server-authoritative count: the initial plan intentionally holds only
      // Q1 (floor of 1 so the indicator never shows 0/0 once started). The
      // total grows from res.total_questions as Gemini generates questions.
      setTotalQuestions(Math.max(questions.length, 1));
      setAnsweredCount(0);

      if (questions.length === 0) {
        setError("No questions generated for this skill.");
        setPhase("error");
        setLoading(false);
        interviewActiveRef.current = false;
        return;
      }

      const firstQ = questions[0];
      setCurrentQuestion(firstQ);
      setLoading(false);
      speechRef.current.reset();

      const greeting = resuming
        ? firstQ.prompt
        : `Hi! I'm ${INTERVIEWER_NAME}, your technical interviewer. I've reviewed your profile and we'll focus on ${skill} today. Let's begin. ${firstQ.prompt}`;
      await speakThenListen(greeting);
    } catch (e) {
      if (!interviewActiveRef.current) return;
      setError(e instanceof Error ? e.message : "Could not start the interview");
      setPhase("error");
      setLoading(false);
      interviewActiveRef.current = false;
    }
  }, [skill, requestMedia, speakThenListen]);

  // ---- Retry the last submitted answer after a recoverable failure ----
  // The backend persists the raw answer before evaluating, so resubmitting
  // the SAME transcript is idempotent — the candidate never repeats it.
  const retryLastSubmit = useCallback(() => {
    const transcript = lastTranscriptRef.current.trim();
    if (!transcript || !interviewActiveRef.current) return;
    setError(null);
    setPhase("processing");
    void submitAnswer(transcript);
  }, [submitAnswer]);

  // ---- Manual typed submit (accessibility fallback) ----
  const submitTyped = useCallback(() => {
    if (typedAnswer.trim()) {
      speech.stop();
      void audioCapture.stop();
      void submitAnswer(typedAnswer);
      setTypedAnswer("");
    }
  }, [typedAnswer, speech, audioCapture, submitAnswer]);

  // ---- End interview ----
  const endInterview = useCallback(async () => {
    if (phaseRef.current === "processing" || phaseRef.current === "completing") return;
    interviewActiveRef.current = false;
    turnRef.current += 1;
    isSubmittingRef.current = false;
    tts.stop();
    speech.stop();
    speech.reset();
    stopMedia();
    const sess = sessionRef.current;
    if (sess) {
      try {
        setPhase("completing");
        const graded = await completeSkillInterview(sess.session_id);
        setResult(graded);
        setPhase("completed");
        onCompleted?.(graded);
      } catch {
        setPhase("completed");
      }
    } else {
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
    isSubmittingRef.current = false;
    turnRef.current += 1;
    void speakThenListen(`Let me repeat the question. ${q.prompt}`);
  }, [tts, speech, speakThenListen]);

  const retryVoice = useCallback(() => {
    const q = currentQuestionRef.current;
    if (!q) return;
    interviewActiveRef.current = true;
    isSubmittingRef.current = false;
    setError(null);
    tts.stop();
    speech.stop();
    speech.reset();
    turnRef.current += 1;
    void speakThenListen(q.prompt);
  }, [tts, speech, speakThenListen]);

  // ---- Retry devices ----
  const recheckCamera = useCallback(async () => {
    setError(null);
    const res = await requestCamera();
    if (res === "live" && phaseRef.current === "device_error") {
      if (micState === "live") {
        void beginInterview();
      }
    }
  }, [requestCamera, micState, beginInterview]);

  const recheckMicrophone = useCallback(async () => {
    setError(null);
    const res = await requestMicrophone();
    if (res === "live" && phaseRef.current === "device_error") {
      void beginInterview();
    }
  }, [requestMicrophone, beginInterview]);

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
        <div className="dark iv__intro">
          <div className="iv__intro-card">
            <div className="iv__intro-icon">🎙</div>
            <h1 className="iv__intro-title">INAURA AI Interview</h1>
            <p className="iv__intro-skill">{skill}</p>
            <p className="iv__intro-desc">
              This is a live AI interview. The interviewer will speak directly to you
              and adapt questions based on your technical responses.
            </p>
            <p className="iv__intro-req">
              Camera + microphone will be requested when you begin.
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
        <div className="dark iv__call">
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
                {phase === "initializing" && "Connecting camera and microphone..."}
                {phase === "ai_speaking" && "AI is speaking"}
                {phase === "listening" && "Listening..."}
                {phase === "processing" && "Analyzing your response..."}
                {phase === "completing" && "Building your report..."}
                {phase === "device_error" && "Device error"}
                {phase === "recoverable_error" && "Connection issue — retry available"}
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

          {phase === "device_error" && (
            <div className="iv__device-banner iv__device-banner--warn" style={{ flexWrap: "wrap", justifyContent: "center", padding: "12px 20px" }}>
              <span>{error || "Media device error"}</span>
              <Button onClick={() => void recheckMicrophone()} variant="primary" size="sm">Recheck mic</Button>
              <Button onClick={() => void recheckCamera()} variant="secondary" size="sm">Recheck camera</Button>
              <Button onClick={() => void beginInterview()} variant="secondary" size="sm">Retry call</Button>
            </div>
          )}

          {phase === "error" && (
            <div className="iv__device-banner iv__device-banner--warn" style={{ flexWrap: "wrap", justifyContent: "center", padding: "12px 20px" }}>
              <span>{error || "An error occurred during the interview"}</span>
              {currentQuestion && <Button onClick={retryVoice} variant="secondary" size="sm">Retry voice</Button>}
              <Button onClick={() => void beginInterview()} variant="primary" size="sm">Retry</Button>
              <Button onClick={() => void endInterview()} variant="ghost" size="sm">End</Button>
            </div>
          )}

          {phase === "recoverable_error" && (
            <div className="iv__device-banner iv__device-banner--warn" style={{ flexWrap: "wrap", justifyContent: "center", padding: "12px 20px" }}>
              <span>{error || "A temporary connection issue occurred. Your answer is saved."}</span>
              <Button onClick={retryLastSubmit} variant="primary" size="sm">Retry</Button>
              <Button onClick={() => void endInterview()} variant="ghost" size="sm">End</Button>
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
                  <span className="iv__avatar-icon" role="img" aria-label="Funny duck interviewer">🦆</span>
                </div>
              </div>
              <div className="iv__call-panel-label">{INTERVIEWER_NAME}</div>
              {/* The question stays visible while listening when voice failed,
                  so it can still be read and answered. Cleared on success. */}
              {(phase === "ai_speaking" || phase === "listening") && aiText && (
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
                <video
                  ref={setVideoRef}
                  autoPlay
                  muted
                  playsInline
                  className="iv__call-video"
                  aria-label="Your camera preview"
                />
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
              <span className="iv__call-caption-text">You said: {submittedTranscript}</span>
            )}
          </div>

          {(!speech.isSupported || speech.state === "error") && phase === "listening" && (
            <div className="iv__call-typed">
              {speech.state === "error" && (
                <p className="iv__error" style={{ margin: "0 0 8px 0" }}>
                  Microphone transcription had an issue — you can type your answer instead.
                </p>
              )}
              <input
                className="iv__call-typed-input"
                value={typedAnswer}
                onChange={(e) => setTypedAnswer(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    submitTyped();
                  }
                }}
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

            <Button
              onClick={toggleMic}
              variant={micEnabled ? "secondary" : "accent"}
              size="md"
              disabled={micState === "denied" || micState === "unavailable"}
              aria-label={micEnabled ? "Mute microphone" : "Unmute microphone"}
            >
              {micEnabled ? "🎙 Mic" : "🔇 Mic off"}
            </Button>
            <Button
              onClick={toggleCamera}
              variant={cameraEnabled ? "secondary" : "accent"}
              size="md"
              disabled={camState === "denied" || camState === "unavailable"}
              aria-label={cameraEnabled ? "Turn off camera" : "Turn on camera"}
            >
              {cameraEnabled ? "📷 Camera" : "📷 Camera off"}
            </Button>
            <Button
              onClick={repeatQuestion}
              variant="secondary"
              size="md"
              disabled={phase === "initializing" || phase === "processing" || phase === "completing"}
            >
              ↻ Repeat
            </Button>
            <Button
              onClick={() => void endInterview()}
              variant="ghost"
              size="md"
              disabled={phase === "processing" || phase === "completing"}
            >
              ⛔ End
            </Button>
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
