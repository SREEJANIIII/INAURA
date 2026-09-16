import { useCallback, useEffect, useRef, useState } from "react";

export type SpeechState = "idle" | "listening" | "error" | "unsupported";

export type UseSpeechRecognitionOptions = {
<<<<<<< HEAD
  /** Ms of silence after meaningful speech before auto-submitting. 0 = disabled. */
=======
  /** Ms of silence after speech before auto-stopping. Defaults to 2800ms. */
>>>>>>> cd816cd7af05b78146197492a0c4f6a7d6cd19d9
  silenceTimeout?: number;
  /** Minimum characters to consider speech meaningful */
  minChars?: number;
};

export type UseSpeechRecognitionResult = {
  state: SpeechState;
  interimTranscript: string;
  finalTranscript: string;
  liveTranscript: string;
  start: () => void;
  stop: () => string;
  reset: () => void;
  isSupported: boolean;
<<<<<<< HEAD
=======
  hasSpoken: boolean;
  /** Wire the silence callback. Call this to connect your handler. */
>>>>>>> cd816cd7af05b78146197492a0c4f6a7d6cd19d9
  setOnSilence: (cb: (transcript: string) => void) => void;
};

interface SpeechRecognitionEvent extends Event {
  resultIndex: number;
  results: SpeechRecognitionResultList;
}

interface SpeechRecognitionErrorEvent extends Event {
  error: string;
}

interface SpeechRecognitionInstance extends EventTarget {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  maxAlternatives: number;
  onresult: ((ev: SpeechRecognitionEvent) => void) | null;
  onend: (() => void) | null;
  onerror: ((ev: SpeechRecognitionErrorEvent) => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}

declare global {
  interface Window {
    SpeechRecognition?: new () => SpeechRecognitionInstance;
    webkitSpeechRecognition?: new () => SpeechRecognitionInstance;
  }
}

/**
 * Normalizes common casing/formatting for technical terms from speech recognition
 * without altering candidate meaning or inventing words.
 */
function normalizeTechnicalTerms(text: string): string {
  if (!text) return "";
  let s = text;
  const terms: Array<[RegExp, string]> = [
    [/\b(fast\s*api|fastapi)\b/gi, "FastAPI"],
    [/\b(post\s*gres|postgres|postgresql)\b/gi, "PostgreSQL"],
    [/\b(pg\s*vector|pgvector)\b/gi, "pgvector"],
    [/\b(type\s*script|typescript)\b/gi, "TypeScript"],
    [/\b(java\s*script|javascript)\b/gi, "JavaScript"],
    [/\b(rest\s*api|restful\s*api)\b/gi, "REST API"],
    [/\b(rag)\b/gi, "RAG"],
    [/\b(gemini)\b/gi, "Gemini"],
    [/\b(docker)\b/gi, "Docker"],
    [/\b(kubernetes|k8s)\b/gi, "Kubernetes"],
    [/\b(oop)\b/gi, "OOP"],
    [/\b(sql)\b/gi, "SQL"],
    [/\b(lang\s*chain|langchain)\b/gi, "LangChain"],
    [/\b(supabase)\b/gi, "Supabase"],
    [/\b(react)\b/gi, "React"],
    [/\b(graphql)\b/gi, "GraphQL"],
    [/\b(mongodb|mongo)\b/gi, "MongoDB"],
    [/\b(redis)\b/gi, "Redis"],
    [/\b(pytorch)\b/gi, "PyTorch"],
  ];
  for (const [regex, replacement] of terms) {
    s = s.replace(regex, replacement);
  }
  return s;
}

export function useSpeechRecognition(
  opts: UseSpeechRecognitionOptions = {}
): UseSpeechRecognitionResult {
<<<<<<< HEAD
  const { silenceTimeout = 2600, minChars = 2 } = opts;
  const [state, setState] = useState<SpeechState>("idle");
  const [interimTranscript, setInterimTranscript] = useState("");
  const [finalTranscript, setFinalTranscript] = useState("");
=======
  const { silenceTimeout = 2800 } = opts;
  const [state, setState] = useState<SpeechState>("idle");
  const [interimTranscript, setInterimTranscript] = useState("");
  const [finalTranscript, setFinalTranscript] = useState("");
  const [hasSpoken, setHasSpoken] = useState(false);
>>>>>>> cd816cd7af05b78146197492a0c4f6a7d6cd19d9

  const recogRef = useRef<SpeechRecognitionInstance | null>(null);
  const activeRef = useRef(false);
  const hasSpokenRef = useRef(false);
  const silenceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onSilenceRef = useRef<((t: string) => void) | null>(null);
  const finalTranscriptRef = useRef("");
<<<<<<< HEAD
  const interimRef = useRef("");
  const lastSubmittedRef = useRef("");
  const submittedRef = useRef(false);
=======
  const interimTranscriptRef = useRef("");
  const isSubmittedRef = useRef(false);
  const restartAttemptsRef = useRef(0);
>>>>>>> cd816cd7af05b78146197492a0c4f6a7d6cd19d9

  const isSupported =
    typeof window !== "undefined" &&
    Boolean(window.SpeechRecognition || window.webkitSpeechRecognition);

  const clearSilenceTimer = useCallback(() => {
    if (silenceTimerRef.current !== null) {
      clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = null;
    }
  }, []);

<<<<<<< HEAD
  const submitIfNeeded = useCallback((transcript: string) => {
    const trimmed = transcript.trim();
    if (!trimmed) return false;
    if (trimmed.length < minChars) return false;
    if (submittedRef.current) return false;
    if (trimmed === lastSubmittedRef.current) return false;
    if (trimmed.split(/\s+/).filter(Boolean).length === 0) return false;
    submittedRef.current = true;
    lastSubmittedRef.current = trimmed;
    onSilenceRef.current?.(trimmed);
    return true;
  }, [minChars]);

  const resetSilenceTimer = useCallback((currentCombined: string) => {
    if (silenceTimeout <= 0) return;
    if (!hasSpokenRef.current) return;
    clearSilenceTimer();
    const snapshot = currentCombined.trim();
    if (!snapshot) return;
    silenceTimerRef.current = setTimeout(() => {
      if (!activeRef.current || submittedRef.current) return;
      // Stop recognition first to get final flush, then submit
      try {
        recogRef.current?.stop();
      } catch {
        /* ignore */
      }
      // Give onend a moment to fire, but also submit directly with snapshot as fallback
      // Use finalTranscriptRef as source of truth
      setTimeout(() => {
        if (submittedRef.current) return;
        const final = finalTranscriptRef.current.trim() || snapshot;
        if (final && hasSpokenRef.current) {
          activeRef.current = false;
          setState("idle");
          setInterimTranscript("");
          submitIfNeeded(final);
        }
      }, 250);
    }, silenceTimeout);
  }, [silenceTimeout, clearSilenceTimer, submitIfNeeded]);
=======
  const submitTranscript = useCallback((transcript: string) => {
    const cleaned = normalizeTechnicalTerms(transcript.trim());
    if (!cleaned || isSubmittedRef.current) return;
    isSubmittedRef.current = true;
    clearSilenceTimer();
    activeRef.current = false;
    try {
      recogRef.current?.stop();
    } catch {
      /* ignore */
    }
    setState("idle");
    onSilenceRef.current?.(cleaned);
  }, [clearSilenceTimer]);

  const scheduleSilenceTimer = useCallback(() => {
    if (silenceTimeout <= 0) return;
    clearSilenceTimer();
    silenceTimerRef.current = setTimeout(() => {
      if (activeRef.current && hasSpokenRef.current && !isSubmittedRef.current) {
        const full = [finalTranscriptRef.current, interimTranscriptRef.current]
          .filter(Boolean)
          .join(" ")
          .trim();
        if (full) {
          submitTranscript(full);
        }
      }
    }, silenceTimeout);
  }, [silenceTimeout, clearSilenceTimer, submitTranscript]);
>>>>>>> cd816cd7af05b78146197492a0c4f6a7d6cd19d9

  const cleanup = useCallback(() => {
    clearSilenceTimer();
    if (recogRef.current) {
      try {
        recogRef.current.abort();
      } catch {
        /* ignore */
      }
<<<<<<< HEAD
      recogRef.current.onresult = null;
      recogRef.current.onend = null;
      recogRef.current.onerror = null;
=======
>>>>>>> cd816cd7af05b78146197492a0c4f6a7d6cd19d9
      recogRef.current = null;
    }
    activeRef.current = false;
    hasSpokenRef.current = false;
  }, [clearSilenceTimer]);

  useEffect(() => cleanup, [cleanup]);

  const start = useCallback(() => {
    if (!isSupported) {
      setState("unsupported");
      return;
    }
    if (activeRef.current) return;

<<<<<<< HEAD
    // Reset per-question state BEFORE starting new recognition
    clearSilenceTimer();
    hasSpokenRef.current = false;
    submittedRef.current = false;
    finalTranscriptRef.current = "";
    interimRef.current = "";
    setFinalTranscript("");
    setInterimTranscript("");
=======
    // Reset cycle tracking
    clearSilenceTimer();
    isSubmittedRef.current = false;
    hasSpokenRef.current = false;
    setHasSpoken(false);
    setInterimTranscript("");
    interimTranscriptRef.current = "";
    // Note: finalTranscriptRef is preserved unless reset() was called,
    // but in normal question cycle reset() is called before start().
>>>>>>> cd816cd7af05b78146197492a0c4f6a7d6cd19d9

    try {
      const Impl = window.SpeechRecognition || window.webkitSpeechRecognition;
      if (!Impl) {
        setState("unsupported");
        return;
      }
      const recog = new Impl();
      recogRef.current = recog;
      recog.lang = "en-US";
      recog.interimResults = true;
      recog.continuous = true;
      recog.maxAlternatives = 1;

      recog.onresult = (ev: SpeechRecognitionEvent) => {
<<<<<<< HEAD
        // Rebuild full final transcript from all results (prevents duplication)
        let fullFinal = "";
        let currentInterim = "";
        for (let i = 0; i < ev.results.length; i++) {
          const res = ev.results[i];
          const txt = res[0]?.transcript || "";
          if (res.isFinal) {
            fullFinal += txt + " ";
=======
        let interim = "";
        let newFinal = "";
        for (let i = ev.resultIndex; i < ev.results.length; i++) {
          const res = ev.results[i];
          const t = res[0].transcript;
          if (res.isFinal) {
            newFinal += t;
>>>>>>> cd816cd7af05b78146197492a0c4f6a7d6cd19d9
          } else {
            currentInterim += txt + " ";
          }
        }
<<<<<<< HEAD
        fullFinal = fullFinal.trim();
        currentInterim = currentInterim.trim();

        // Update refs and state
        finalTranscriptRef.current = fullFinal;
        interimRef.current = currentInterim;
        setFinalTranscript(fullFinal);
        setInterimTranscript(currentInterim);

        const combined = [fullFinal, currentInterim].filter(Boolean).join(" ").trim();

        // Detect meaningful speech
        if (combined && combined.length >= minChars && !hasSpokenRef.current) {
          hasSpokenRef.current = true;
        }

        // Only start/refresh silence timer after meaningful speech
        if (hasSpokenRef.current && combined) {
          resetSilenceTimer(combined);
=======

        if (newFinal) {
          const updated = finalTranscriptRef.current
            ? `${finalTranscriptRef.current} ${newFinal}`.trim()
            : newFinal.trim();
          finalTranscriptRef.current = updated;
          setFinalTranscript(updated);
        }

        interimTranscriptRef.current = interim;
        setInterimTranscript(interim);

        const currentCombined = [finalTranscriptRef.current, interim]
          .filter(Boolean)
          .join(" ")
          .trim();

        // Speech detected: ONLY start silence timer if candidate actually spoke
        if (currentCombined.length > 0) {
          hasSpokenRef.current = true;
          setHasSpoken(true);
          scheduleSilenceTimer();
>>>>>>> cd816cd7af05b78146197492a0c4f6a7d6cd19d9
        }
      };

      recog.onend = () => {
<<<<<<< HEAD
        clearSilenceTimer();
        if (!activeRef.current) {
          // Already handled via silence timer or manual stop
          setState("idle");
          return;
        }
        activeRef.current = false;
        const transcript = finalTranscriptRef.current.trim() || interimRef.current.trim();
        setInterimTranscript("");
        if (transcript && hasSpokenRef.current && !submittedRef.current) {
          setState("idle");
          submitIfNeeded(transcript);
        } else {
          // No meaningful speech: don't submit, just idle. InterviewModal will handle empty prompt.
          setState("idle");
          if (!transcript || !hasSpokenRef.current) {
            // Signal empty via onSilence with empty? No, let modal detect idle with no submission and reprompt
            // We do not auto-submit empty
          }
=======
        // If intentionally stopped or submitted, exit
        if (!activeRef.current || isSubmittedRef.current) {
          setState("idle");
          return;
>>>>>>> cd816cd7af05b78146197492a0c4f6a7d6cd19d9
        }

        // If candidate spoke and browser closed recognition before silence timer:
        if (hasSpokenRef.current) {
          const full = [finalTranscriptRef.current, interimTranscriptRef.current]
            .filter(Boolean)
            .join(" ")
            .trim();
          if (full && !isSubmittedRef.current) {
            submitTranscript(full);
            return;
          }
        }

        // If recognition closed unexpectedly (e.g. Chrome 15s idle timeout) without speech,
        // automatically restart continuous listening up to 5 times.
        if (activeRef.current && !isSubmittedRef.current && restartAttemptsRef.current < 5) {
          restartAttemptsRef.current += 1;
          try {
            recog.start();
            return;
          } catch {
            /* ignore restart failure */
          }
        }

        activeRef.current = false;
        setState("idle");
      };

      recog.onerror = (ev: SpeechRecognitionErrorEvent) => {
<<<<<<< HEAD
        const err = ev.error;
        if (err === "no-speech") {
          // No speech detected for a while – treat as idle, not error. Modal will reprompt if needed.
          clearSilenceTimer();
          // Keep activeRef true? No, recognition ends on no-speech, we should go idle
          activeRef.current = false;
          setState("idle");
          setInterimTranscript("");
          return;
        }
        if (err === "aborted") {
          clearSilenceTimer();
          activeRef.current = false;
          setState("idle");
          setInterimTranscript("");
          return;
        }
        if (err === "not-allowed" || err === "service-not-allowed") {
          clearSilenceTimer();
          activeRef.current = false;
          setState("error");
          setInterimTranscript("");
          return;
        }
        console.warn("Speech recognition error:", err);
        clearSilenceTimer();
        activeRef.current = false;
        setState("error");
        setInterimTranscript("");
=======
        if (ev.error === "no-speech") {
          // Normal: user was quiet. If candidate hasn't spoken, keep listening!
          if (activeRef.current && !hasSpokenRef.current && !isSubmittedRef.current) {
            return;
          }
        }
        if (ev.error === "aborted") {
          return;
        }
        console.warn("Speech recognition error:", ev.error);
        if (ev.error === "not-allowed" || ev.error === "service-not-allowed") {
          activeRef.current = false;
          clearSilenceTimer();
          setState("error");
        }
>>>>>>> cd816cd7af05b78146197492a0c4f6a7d6cd19d9
      };

      recog.start();
      activeRef.current = true;
      restartAttemptsRef.current = 0;
      setState("listening");
<<<<<<< HEAD
      // Do NOT start silence timer here – wait for hasSpoken
    } catch {
      setState("error");
    }
  }, [isSupported, minChars, clearSilenceTimer, resetSilenceTimer, submitIfNeeded]);

  const stop = useCallback(() => {
    clearSilenceTimer();
    if (recogRef.current && activeRef.current) {
      try {
        recogRef.current.stop();
      } catch {
        /* ignore */
      }
    }
=======
      // CRITICAL: Do NOT start silence timer here! We wait until candidate actually speaks!
    } catch {
      setState("error");
    }
  }, [isSupported, scheduleSilenceTimer, clearSilenceTimer, submitTranscript]);

  const stop = useCallback(() => {
    clearSilenceTimer();
>>>>>>> cd816cd7af05b78146197492a0c4f6a7d6cd19d9
    activeRef.current = false;
    if (recogRef.current) {
      try {
        recogRef.current.stop();
      } catch {
        /* ignore */
      }
    }
    setInterimTranscript("");
<<<<<<< HEAD
    const combined = finalTranscriptRef.current.trim() || interimRef.current.trim();
    // Do not auto-submit via stop() – caller decides. Just return transcript.
    return combined;
=======
    interimTranscriptRef.current = "";
    const combined = [finalTranscriptRef.current, interimTranscriptRef.current]
      .filter(Boolean)
      .join(" ")
      .trim();
    setState("idle");
    return normalizeTechnicalTerms(combined);
>>>>>>> cd816cd7af05b78146197492a0c4f6a7d6cd19d9
  }, [clearSilenceTimer]);

  const reset = useCallback(() => {
    cleanup();
    setInterimTranscript("");
    setFinalTranscript("");
    setHasSpoken(false);
    finalTranscriptRef.current = "";
<<<<<<< HEAD
    interimRef.current = "";
    lastSubmittedRef.current = "";
    submittedRef.current = false;
    hasSpokenRef.current = false;
=======
    interimTranscriptRef.current = "";
    hasSpokenRef.current = false;
    isSubmittedRef.current = false;
    restartAttemptsRef.current = 0;
>>>>>>> cd816cd7af05b78146197492a0c4f6a7d6cd19d9
    setState("idle");
  }, [cleanup]);

  const setOnSilence = useCallback((cb: (transcript: string) => void) => {
    onSilenceRef.current = cb;
  }, []);

  const liveTranscript = [finalTranscript, interimTranscript]
    .filter(Boolean)
    .join(" ")
    .trim();

  return {
    state,
    interimTranscript,
    finalTranscript,
    liveTranscript,
    hasSpoken,
    start,
    stop,
    reset,
    isSupported,
    setOnSilence,
  };
}
