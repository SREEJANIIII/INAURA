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
  | "device_error"
  | "error";

type Question = {
  id: string;
  competency: string;
  prompt: string;
  follow_ups: string[];
};

<<<<<<< HEAD
const SILENCE_TIMEOUT_MS = 2600;
=======
const SILENCE_TIMEOUT_MS = 2800;
>>>>>>> cd816cd7af05b78146197492a0c4f6a7d6cd19d9

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
  const [sessionId, setSessionId] = useState<string | null>(() => sessionStorage.getItem("interview_session_id"));

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
    toggleMic,
    toggleCamera,
    stopAll: stopMedia,
  } = useMediaDevices();

  const tts = useTextToSpeech();
  const speech = useSpeechRecognition({ silenceTimeout: SILENCE_TIMEOUT_MS, minChars: 2 });

  const phaseRef = useRef(phase);
  const currentQuestionRef = useRef(currentQuestion);
  const sessionRef = useRef(session);
  const interviewActiveRef = useRef(false);
  const isSubmittingRef = useRef(false);
  const ttsRef = useRef(tts);
  const speechRef = useRef(speech);

  useEffect(() => {
    phaseRef.current = phase;
  }, [phase]);
  useEffect(() => {
    currentQuestionRef.current = currentQuestion;
  }, [currentQuestion]);
  useEffect(() => {
    sessionRef.current = session;
  }, [session]);
  useEffect(() => {
    ttsRef.current = tts;
  }, [tts]);
  useEffect(() => {
    speechRef.current = speech;
  }, [speech]);

<<<<<<< HEAD
  // Cleanup on unmount - full cleanup per Part 7
  useEffect(
    () => () => {
      interviewActiveRef.current = false;
      isSubmittingRef.current = false;
      tts.stop();
      speech.stop();
      speech.reset();
      stopMedia();
      // Don't remove session on unmount if still in_progress - keep for recovery
      // Only remove if completed
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    []
  );
=======
  // Cleanup on unmount
  useEffect(() => () => {
    interviewActiveRef.current = false;
    isSubmittingRef.current = false;
    tts.stop();
    speech.stop();
    stopMedia();
    sessionStorage.removeItem("interview_session_id");
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
>>>>>>> cd816cd7af05b78146197492a0c4f6a7d6cd19d9

  // Sync video element srcObject when mounted or camera state becomes active
  useEffect(() => {
    if (phase !== "intro" && phase !== "completed" && videoRef.current) {
      setVideoRef(videoRef.current);
    }
  }, [phase, camState, setVideoRef, videoRef]);

  // ---- Speak then listen: guarded async transition ----
  const speakThenListen = useCallback(async (text: string) => {
    if (!interviewActiveRef.current) return;
<<<<<<< HEAD
    // Reset transcript for new question BEFORE speaking (so previous answer doesn't leak)
    speechRef.current.reset();
=======
    speechRef.current.stop();
>>>>>>> cd816cd7af05b78146197492a0c4f6a7d6cd19d9
    setAiText(text);
    setPhase("ai_speaking");
    // Ensure recognition is stopped while AI speaks
    speechRef.current.stop();
    await ttsRef.current.speak(text);
    if (!interviewActiveRef.current) return;
    setAiText("");
    // Only transition to listening if still in ai_speaking and interview active
    if (phaseRef.current === "ai_speaking" && interviewActiveRef.current) {
      speechRef.current.reset();
      isSubmittingRef.current = false;
      setPhase("listening");
      // Small delay to avoid picking up TTS tail
      setTimeout(() => {
        if (!interviewActiveRef.current) return;
        if (phaseRef.current !== "listening") return;
        speechRef.current.reset();
        speechRef.current.start();
      }, 300);
    }
  }, []);

<<<<<<< HEAD
  // ---- Handle empty / too short answer ----
  const handleEmptyAnswer = useCallback(async () => {
    if (!interviewActiveRef.current) return;
    const prompt = "I didn't catch that. Take your time and explain it in your own words.";
    await speakThenListen(prompt);
    // speakThenListen will reset and start listening again
  }, [speakThenListen]);

  // ---- Submit answer to backend with guards ----
  const submitAnswer = useCallback(
    async (transcript: string) => {
=======
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

    try {
      const res = await answerInterviewQuestion(sess.session_id, q.id, trimmed);
>>>>>>> cd816cd7af05b78146197492a0c4f6a7d6cd19d9
      if (!interviewActiveRef.current) return;
      if (isSubmittingRef.current) return;
      const sess = sessionRef.current;
      const q = currentQuestionRef.current;
      if (!sess || !q) return;

<<<<<<< HEAD
      const trimmed = transcript.trim();
      // Empty check - don't submit to Gemini, reprompt
      if (!trimmed || trimmed.length < 2) {
        // Don't set processing, just reprompt
        await handleEmptyAnswer();
        return;
      }

      // Prevent duplicate submissions
      isSubmittingRef.current = true;
      setPhase("processing");
      speechRef.current.stop();

      try {
        const res = await answerInterviewQuestion(sess.session_id, q.id, trimmed);
        if (!interviewActiveRef.current) {
          isSubmittingRef.current = false;
          return;
        }
        setAnsweredCount(res.answered_count);
=======
      if (res.completed || res.next_action === "complete" || res.action === "COMPLETE" || !res.current_question) {
        const closing =
          res.spoken_response ||
          "Thank you. That concludes all questions for this interview. I am finalizing your evaluation now.";
        setPhase("ai_speaking");
        await ttsRef.current.speak(closing);
        if (!interviewActiveRef.current) return;

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
      setCurrentQuestion(nextQ);

      let spokenText = "";
      if (res.spoken_response) {
        // Natural transition: acknowledge previous answer, then state next question
        spokenText =
          (res.next_action === "next" || res.action === "NEXT") && nextQ
            ? `${res.spoken_response} ${nextQ.prompt}`
            : res.spoken_response;
      } else if (res.evaluation?.follow_up_needed && res.evaluation.suggested_follow_up) {
        spokenText = res.evaluation.suggested_follow_up;
      } else if (nextQ) {
        spokenText = nextQ.prompt;
      }

      await speakThenListen(spokenText);
    } catch (e) {
      if (!interviewActiveRef.current) return;
      isSubmittingRef.current = false;
      const msg = e instanceof Error ? e.message : "Could not submit answer";
      if (msg.includes("409") || msg.includes("not the current question")) {
        setError("Session out of sync. Recovering session...");
        setSessionId(sessionRef.current?.session_id || null);
      } else {
        setError(msg);
        setPhase("error");
      }
    }
  }, [speakThenListen, stopMedia, onCompleted]);
>>>>>>> cd816cd7af05b78146197492a0c4f6a7d6cd19d9

        if (res.completed || res.next_action === "complete" || !res.current_question) {
          setPhase("completing");
          const graded = await completeSkillInterview(sess.session_id);
          if (!interviewActiveRef.current) {
            isSubmittingRef.current = false;
            return;
          }
          sessionStorage.removeItem("interview_session_id");
          interviewActiveRef.current = false;
          isSubmittingRef.current = false;
          ttsRef.current.stop();
          speechRef.current.stop();
          speechRef.current.reset();
          stopMedia();
          setResult(graded);
          setPhase("completed");
          onCompleted?.(graded);
          return;
        }

        const nextQ = res.current_question;
        // Backend decides adaptive action - we just speak what it returns
        let spokenText = "";
        if (res.evaluation?.follow_up_needed && res.evaluation.suggested_follow_up) {
          spokenText = res.evaluation.suggested_follow_up;
        } else if (nextQ) {
          // For NEXT_QUESTION, NEXT_SKILL, etc., speak the next prompt
          // Add conversational acknowledgement if evaluation exists
          if (res.evaluation?.brief_explanation) {
            // Backend already provides natural follow-up via suggested_follow_up
            // If no follow-up, just ask next question directly (backend ensures natural tone)
            spokenText = nextQ.prompt;
          } else {
            spokenText = nextQ.prompt;
          }
        } else {
          spokenText = "Let's continue with the next question.";
        }

        setCurrentQuestion(nextQ);
        isSubmittingRef.current = false;
        await speakThenListen(spokenText);
      } catch (e) {
        isSubmittingRef.current = false;
        if (!interviewActiveRef.current) return;
        const msg = e instanceof Error ? e.message : "Could not submit answer";
        if (msg.includes("409") || msg.includes("not the current question")) {
          setError("Session out of sync. Recovering...");
          // Try to recover session
          setTimeout(() => {
            const sid = sessionRef.current?.session_id;
            if (sid) setSessionId(sid);
          }, 500);
        } else if (msg.includes("502") || msg.includes("503") || msg.toLowerCase().includes("ai") || msg.toLowerCase().includes("gemini")) {
          setError("AI interviewer temporarily unavailable. Please try again.");
          setPhase("error");
        } else if (msg.toLowerCase().includes("network") || msg.includes("Failed to fetch")) {
          setError("Network error. Please check your connection and try again.");
          setPhase("error");
        } else {
          setError(msg);
          setPhase("error");
        }
      }
    },
    [speakThenListen, handleEmptyAnswer, stopMedia, onCompleted]
  );

  // ---- Wire silence → submitAnswer (single submission lifecycle) ----
  useEffect(() => {
    speech.setOnSilence((transcript: string) => {
<<<<<<< HEAD
      // This is the sole owner of answer submission (not onend)
      // Guarded by isSubmittingRef inside submitAnswer
      void submitAnswer(transcript);
=======
      if (phaseRef.current === "listening" && !isSubmittingRef.current) {
        void submitAnswer(transcript);
      }
>>>>>>> cd816cd7af05b78146197492a0c4f6a7d6cd19d9
    });
  }, [speech, submitAnswer]);

  // ---- Start the interview ----
  const beginInterview = useCallback(async () => {
    if (interviewActiveRef.current) return;
    interviewActiveRef.current = true;
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
      const data = await startSkillInterview(skill);
      if (!interviewActiveRef.current) {
        setLoading(false);
        return;
      }
      setSession(data);
      sessionStorage.setItem("interview_session_id", data.session_id);
      setSessionId(data.session_id);

      const questions = data.plan?.questions || [];
      setTotalQuestions(questions.length);
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

      const greeting = `Hi! I'm your INAURA AI interviewer. I've reviewed your profile and we'll focus on ${skill} today. Let's begin. ${firstQ.prompt}`;
      await speakThenListen(greeting);
    } catch (e) {
      if (!interviewActiveRef.current) return;
      setError(e instanceof Error ? e.message : "Could not start the interview");
      setPhase("error");
      setLoading(false);
      interviewActiveRef.current = false;
    }
  }, [skill, requestMedia, speakThenListen]);

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
          if (active) {
            setResult(graded);
            setPhase("completed");
          }
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
        const idx = ((data as Record<string, unknown>).current_index as number) ?? 0;
        setTotalQuestions(questions.length);
        setAnsweredCount(
<<<<<<< HEAD
          ((data.transcript as Array<Record<string, unknown>> | undefined) || []).filter((t) => t.answer).length
=======
          ((data.transcript as Array<Record<string, unknown>> | undefined) || []).filter(
            (t) => t.answer
          ).length
>>>>>>> cd816cd7af05b78146197492a0c4f6a7d6cd19d9
        );
        if (questions[idx]) {
          setCurrentQuestion(questions[idx]);
          if (active) {
            // Recover to intro so user can re-start with Let's Begin (keeps session)
            setPhase("intro");
          }
        } else {
          const graded = await completeSkillInterview(sessionId);
          if (active) {
            setResult(graded);
            setPhase("completed");
          }
        }
      } catch {
        if (active) {
          sessionStorage.removeItem("interview_session_id");
          setSessionId(null);
        }
      }
    })();
    return () => {
      active = false;
    };
  }, [sessionId, skill]);

<<<<<<< HEAD
  // ---- Start the interview - FIXED Let's Begin bug ----
  const beginInterview = useCallback(async () => {
    if (interviewActiveRef.current) return;
    interviewActiveRef.current = true;
    isSubmittingRef.current = false;
    setLoading(true);
    setError(null);
    // CRITICAL: Transition to call screen IMMEDIATELY so video element mounts
    // before getUserMedia. This fixes the "nothing happened" bug where stream
    // was acquired before <video> existed and never attached.
    setPhase("initializing");

    // Small tick to let React mount the video element
    await new Promise((r) => setTimeout(r, 50));
    if (!interviewActiveRef.current) {
      setLoading(false);
      return;
    }

    // Request media as part of user gesture (still within Let's Begin call stack)
    const mediaResult = await requestMedia();
    if (!interviewActiveRef.current) {
      setLoading(false);
      return;
    }

    // Check if at least one device is usable
    if (!mediaResult.usable) {
      setError(
        mediaResult.camera === "denied" || mediaResult.microphone === "denied"
          ? "Camera and microphone permission denied. Please allow access and recheck."
          : "Camera and microphone unavailable. Please check your devices."
      );
      setPhase("error");
      setLoading(false);
      interviewActiveRef.current = false;
      return;
    }

    try {
      const data = await startSkillInterview(skill);
      if (!interviewActiveRef.current) {
        setLoading(false);
        return;
      }
      setSession(data);
      sessionStorage.setItem("interview_session_id", data.session_id);
      setSessionId(data.session_id);

      const questions = data.plan.questions || [];
      setTotalQuestions(questions.length);
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

      const greeting = `Hi! I'm your INAURA AI interviewer. I've reviewed your profile and we'll focus on ${skill} today. Let's begin. ${firstQ.prompt}`;
      await speakThenListen(greeting);
    } catch (e) {
      if (!interviewActiveRef.current) return;
      const msg = e instanceof Error ? e.message : "Could not start the interview";
      if (msg.includes("503") || msg.toLowerCase().includes("not configured")) {
        setError("AI interviewer unavailable. Please try again in a moment.");
      } else if (msg.toLowerCase().includes("network") || msg.includes("Failed to fetch")) {
        setError("Network error. Please check your connection and retry.");
      } else {
        setError(msg);
      }
      setPhase("error");
      setLoading(false);
      interviewActiveRef.current = false;
    }
  }, [skill, requestMedia, speakThenListen]);

  // ---- Manual typed submit (fallback when speech not supported) ----
=======
  // ---- Manual typed submit (accessibility fallback) ----
>>>>>>> cd816cd7af05b78146197492a0c4f6a7d6cd19d9
  const submitTyped = useCallback(() => {
    if (typedAnswer.trim()) {
      const toSubmit = typedAnswer;
      setTypedAnswer("");
      // Reset speech to clear any stale transcripts
      speech.stop();
      speech.reset();
      void submitAnswer(toSubmit);
    }
  }, [typedAnswer, speech, submitAnswer]);

  // ---- End interview - full cleanup per Part 7 ----
  const endInterview = useCallback(async () => {
    // Prevent stale callbacks
    interviewActiveRef.current = false;
    isSubmittingRef.current = false;
<<<<<<< HEAD
    // Stop all async work
    tts.stop();
    speech.stop();
    speech.reset();
    // Stop media tracks and clear timers
    stopMedia();
    // Clear any pending speech callbacks via refs
=======
    tts.stop();
    speech.stop();
    speech.reset();
    stopMedia();
>>>>>>> cd816cd7af05b78146197492a0c4f6a7d6cd19d9
    const sess = sessionRef.current;
    if (sess) {
      try {
        setPhase("completing");
        const graded = await completeSkillInterview(sess.session_id);
        sessionStorage.removeItem("interview_session_id");
<<<<<<< HEAD
        setResult(graded);
=======
>>>>>>> cd816cd7af05b78146197492a0c4f6a7d6cd19d9
        setPhase("completed");
        onCompleted?.(graded);
      } catch {
        sessionStorage.removeItem("interview_session_id");
        setPhase("completed");
        // Even if complete fails, show completed with note
        setResult({
          session_id: sess.session_id,
          skill: sess.skill,
          status: "completed",
          validity: "low_confidence",
          counts_as_evidence: false,
          completed_at: new Date().toISOString(),
          source_reliability: null,
          technical_scores: null,
          communication_scores: null,
          note: "Interview ended early. Partial answers were saved.",
        } as CompleteInterviewResponse);
      }
    } else {
      sessionStorage.removeItem("interview_session_id");
      setPhase("completed");
    }
  }, [tts, speech, stopMedia, onCompleted]);

  // ---- Repeat question ----
  const repeatQuestion = useCallback(() => {
    const q = currentQuestionRef.current;
    if (!q || !interviewActiveRef.current) return;
    // Stop current work
    isSubmittingRef.current = false;
    tts.stop();
    speech.stop();
    speech.reset();
<<<<<<< HEAD
    void speakThenListen(q.prompt);
  }, [speakThenListen, tts, speech]);
=======
    isSubmittingRef.current = false;
    void speakThenListen(`Let me repeat the question. ${q.prompt}`);
  }, [tts, speech, speakThenListen]);
>>>>>>> cd816cd7af05b78146197492a0c4f6a7d6cd19d9

  // ---- Retry devices ----
  const recheckCamera = useCallback(async () => {
    setError(null);
    const res = await requestCamera();
<<<<<<< HEAD
    if (res === "live") setError(null);
  }, [requestCamera]);
=======
    if (res === "live" && phaseRef.current === "device_error") {
      if (micState === "live") {
        void beginInterview();
      }
    }
  }, [requestCamera, micState, beginInterview]);
>>>>>>> cd816cd7af05b78146197492a0c4f6a7d6cd19d9

  const recheckMicrophone = useCallback(async () => {
    setError(null);
    const res = await requestMicrophone();
<<<<<<< HEAD
    if (res === "live") setError(null);
  }, [requestMicrophone]);
=======
    if (res === "live" && phaseRef.current === "device_error") {
      void beginInterview();
    }
  }, [requestMicrophone, beginInterview]);
>>>>>>> cd816cd7af05b78146197492a0c4f6a7d6cd19d9

  const liveCaption = phase === "listening" ? speech.liveTranscript : "";
  const progress = totalQuestions > 0 ? Math.round((answeredCount / totalQuestions) * 100) : 0;
  const skillDisplay = session?.skill || skill;
  const isActive = phase === "ai_speaking" || phase === "listening" || phase === "processing" || phase === "initializing";
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
<<<<<<< HEAD
              This is a live AI interview. The interviewer will ask questions verbally and adapt based on your answers.
=======
              This is a live AI interview. The interviewer will speak directly to you
              and adapt questions based on your technical responses.
            </p>
            <p className="iv__intro-req">
              Camera + microphone will be requested when you begin.
>>>>>>> cd816cd7af05b78146197492a0c4f6a7d6cd19d9
            </p>
            <p className="iv__intro-req">Camera + microphone are required for the live interview experience.</p>
            <Button
              onClick={() => void beginInterview()}
              variant="primary"
              size="lg"
              disabled={loading}
              aria-label="Let's begin the AI interview"
            >
              {loading ? "Starting..." : "Let's Begin"}
            </Button>
            {error && (
              <div className="iv__intro-error" role="alert">
                <div>{error}</div>
                <div style={{ display: "flex", gap: 8, justifyContent: "center", marginTop: 8 }}>
                  {(error.toLowerCase().includes("camera") || error.toLowerCase().includes("microphone") || error.toLowerCase().includes("permission")) && (
                    <>
                      <Button onClick={() => void recheckCamera()} variant="secondary" size="sm">
                        Recheck camera
                      </Button>
                      <Button onClick={() => void recheckMicrophone()} variant="secondary" size="sm">
                        Recheck microphone
                      </Button>
                    </>
                  )}
                  {(error.toLowerCase().includes("network") || error.toLowerCase().includes("ai") || error.toLowerCase().includes("unavailable")) && (
                    <Button onClick={() => void beginInterview()} variant="primary" size="sm">
                      Retry
                    </Button>
                  )}
                </div>
              </div>
            )}
            <p className="iv__intro-req" style={{ marginTop: 8, fontSize: "0.72rem", fontStyle: "italic" }}>
              Your camera stays on this device for preview only. Only your spoken answers are saved.
            </p>
          </div>
        </div>
      )}

      {/* ===== CALL SCREEN - visible as soon as initializing ===== */}
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
              {phase === "initializing" && <span className="iv__status-dot iv__status-dot--proc" />}
              <span className="iv__status-label">
                {phase === "initializing" && "Connecting camera and microphone..."}
                {phase === "ai_speaking" && "AI is speaking"}
                {phase === "listening" && "Listening..."}
                {phase === "processing" && "Analyzing your response..."}
                {phase === "completing" && "Building your report..."}
                {phase === "device_error" && "Device error"}
                {phase === "error" && "Error"}
              </span>
            </div>
            <div className="iv__call-progress">
              <div className="iv__call-progress-bar">
                <div className="iv__call-progress-fill" style={{ width: `${progress}%` }} />
              </div>
              <span className="iv__call-progress-text">
                {answeredCount}/{totalQuestions}
              </span>
            </div>
          </header>

          {error && (
            <div className="iv__error" role="alert">
              <span>{error}</span>
              <button className="iv__error-dismiss" onClick={() => setError(null)} aria-label="Dismiss">
                ×
              </button>
            </div>
          )}

<<<<<<< HEAD
          {/* Independent device banners */}
=======
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
              <Button onClick={() => void beginInterview()} variant="primary" size="sm">Retry</Button>
              <Button onClick={() => void endInterview()} variant="ghost" size="sm">End</Button>
            </div>
          )}

>>>>>>> cd816cd7af05b78146197492a0c4f6a7d6cd19d9
          {camFailed && isActive && (
            <div className="iv__device-banner iv__device-banner--warn">
              <span>{camState === "denied" ? "Camera permission denied" : "Camera unavailable"}</span>
              <Button onClick={() => void recheckCamera()} variant="secondary" size="sm">
                Recheck camera
              </Button>
              <span className="iv__device-banner-note">Continuing with audio only.</span>
            </div>
          )}
          {micFailed && isActive && (
            <div className="iv__device-banner iv__device-banner--warn">
              <span>{micState === "denied" ? "Microphone permission denied" : "Microphone unavailable"}</span>
              <Button onClick={() => void recheckMicrophone()} variant="secondary" size="sm">
                Recheck microphone
              </Button>
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
                <div className="iv__call-bubble iv__call-bubble--ai" aria-live="polite">
                  {aiText}
                </div>
              )}
              {phase === "processing" && (
                <div className="iv__call-bubble iv__call-bubble--ai iv__call-bubble--muted">
                  <div className="iv__call-dots">
                    <span />
                    <span />
                    <span />
                  </div>
                </div>
              )}
              {phase === "initializing" && (
                <div className="iv__call-bubble iv__call-bubble--ai iv__call-bubble--muted">Setting up your live interview...</div>
              )}
            </div>

            <div className="iv__call-panel iv__call-panel--user">
              <div className="iv__call-camera">
                <video
<<<<<<< HEAD
                  ref={videoRef}
=======
                  ref={setVideoRef}
>>>>>>> cd816cd7af05b78146197492a0c4f6a7d6cd19d9
                  autoPlay
                  muted
                  playsInline
                  className="iv__call-video"
                  aria-label="Your camera preview"
                />
<<<<<<< HEAD
                {camState !== "live" && camState !== "off" && (
=======
                {camState !== "live" && (
>>>>>>> cd816cd7af05b78146197492a0c4f6a7d6cd19d9
                  <div className="iv__call-camera-off">
                    <span>📹</span>
                    <span>
                      {camState === "requesting" ? "Starting camera..." : camFailed ? "Camera unavailable" : "Camera off"}
                    </span>
                  </div>
                )}
                {camState === "off" && (
                  <div className="iv__call-camera-off">
                    <span>📹</span>
                    <span>Camera off</span>
                  </div>
                )}
                {phase === "listening" && micState === "live" && micEnabled && (
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
            {phase === "listening" && liveCaption && <span className="iv__call-caption-text">{liveCaption}</span>}
            {phase === "listening" && !liveCaption && <span className="iv__call-caption-hint">Speak now — I&apos;m listening...</span>}
            {phase === "ai_speaking" && aiText && <span className="iv__call-caption-text iv__call-caption-text--ai">{aiText}</span>}
            {phase === "processing" && <span className="iv__call-caption-hint">Evaluating your response...</span>}
            {phase === "initializing" && <span className="iv__call-caption-hint">Preparing your interview...</span>}
            {phase === "error" && <span className="iv__call-caption-hint">Please recheck your devices or retry.</span>}
          </div>

          {/* Typed fallback - only when speech not supported, clearly marked as fallback */}
          {!speech.isSupported && phase === "listening" && (
            <div className="iv__call-typed">
              <div style={{ fontSize: "0.72rem", color: "#94a3b8", marginBottom: 4, width: "100%" }}>
                Speech recognition not supported in this browser — typed fallback (accessibility)
              </div>
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

<<<<<<< HEAD
            {(phase === "ai_speaking" || phase === "listening") && (
              <>
                <Button
                  onClick={toggleMic}
                  variant={micEnabled && micState === "live" ? "secondary" : "accent"}
                  size="md"
                  aria-label={micEnabled ? "Mute microphone" : "Unmute microphone"}
                >
                  {micEnabled && micState === "live" ? "🎙 Mute" : "🔇 Unmute"}
                </Button>
                <Button
                  onClick={toggleCamera}
                  variant={cameraEnabled && camState === "live" ? "secondary" : "accent"}
                  size="md"
                  aria-label={cameraEnabled ? "Turn off camera" : "Turn on camera"}
                >
                  {cameraEnabled && camState === "live" ? "📷 Camera" : "📷 Camera off"}
                </Button>
                <Button onClick={repeatQuestion} variant="secondary" size="md" aria-label="Repeat question">
                  ↻ Repeat
                </Button>
                <Button onClick={() => void endInterview()} variant="ghost" size="md" aria-label="End interview">
                  ⛔ End
                </Button>
              </>
            )}

            {phase === "processing" && (
              <>
                <Button onClick={toggleMic} variant="secondary" size="md" disabled>
                  🎙 Processing...
                </Button>
                <Button
                  onClick={toggleCamera}
                  variant={cameraEnabled && camState === "live" ? "secondary" : "accent"}
                  size="md"
                >
                  {cameraEnabled && camState === "live" ? "📷 Camera" : "📷 Camera off"}
                </Button>
                <Button onClick={repeatQuestion} variant="secondary" size="md" disabled>
                  ↻ Repeat
                </Button>
                <Button onClick={() => void endInterview()} variant="ghost" size="md">
                  ⛔ End
                </Button>
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
                <Button onClick={() => void recheckCamera()} variant="secondary" size="md">
                  Recheck camera
                </Button>
                <Button onClick={() => void recheckMicrophone()} variant="secondary" size="md">
                  Recheck microphone
                </Button>
                <Button onClick={() => void beginInterview()} variant="primary" size="md">
                  Retry
                </Button>
                <Button onClick={() => void endInterview()} variant="ghost" size="md">
                  End
                </Button>
              </>
            )}
=======
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
            >
              ⛔ End
            </Button>
>>>>>>> cd816cd7af05b78146197492a0c4f6a7d6cd19d9
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
                <p className="iv__report-note iv__report-note--ok">Assessment evidence has been added to your skill profile.</p>
              </>
            ) : (
              <p className="iv__report-note">
                {result.status === "awaiting_review"
                  ? "Your interview is saved and awaiting review."
                  : result.note || "INAURA found limited evidence of implementation understanding."}
              </p>
            )}
            <p className="iv__report-fine">
              Interview evidence combines with your GitHub, projects, and assessments through INAURA&apos;s existing evidence model. The
              deterministic skill engine decides how this evidence affects your profile — not Gemini directly.
            </p>
            <div className="iv__report-actions">
              <Button onClick={onClose} variant="primary" size="lg">
                Done
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

