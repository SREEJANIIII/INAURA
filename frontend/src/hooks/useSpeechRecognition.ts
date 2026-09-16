import { useCallback, useEffect, useRef, useState } from "react";

export type SpeechState = "idle" | "listening" | "error" | "unsupported";

export type UseSpeechRecognitionOptions = {
  /** Ms of silence after meaningful speech before auto-submitting. 0 = disabled. */
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

export function useSpeechRecognition(
  opts: UseSpeechRecognitionOptions = {}
): UseSpeechRecognitionResult {
  const { silenceTimeout = 2600, minChars = 2 } = opts;
  const [state, setState] = useState<SpeechState>("idle");
  const [interimTranscript, setInterimTranscript] = useState("");
  const [finalTranscript, setFinalTranscript] = useState("");

  const recogRef = useRef<SpeechRecognitionInstance | null>(null);
  const activeRef = useRef(false);
  const hasSpokenRef = useRef(false);
  const silenceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onSilenceRef = useRef<((t: string) => void) | null>(null);
  const finalTranscriptRef = useRef("");
  const interimRef = useRef("");
  const lastSubmittedRef = useRef("");
  const submittedRef = useRef(false);

  const isSupported =
    typeof window !== "undefined" &&
    Boolean(window.SpeechRecognition || window.webkitSpeechRecognition);

  const clearSilenceTimer = useCallback(() => {
    if (silenceTimerRef.current !== null) {
      clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = null;
    }
  }, []);

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

  const cleanup = useCallback(() => {
    clearSilenceTimer();
    if (recogRef.current) {
      try {
        recogRef.current.abort();
      } catch {
        /* ignore */
      }
      recogRef.current.onresult = null;
      recogRef.current.onend = null;
      recogRef.current.onerror = null;
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

    // Reset per-question state BEFORE starting new recognition
    clearSilenceTimer();
    hasSpokenRef.current = false;
    submittedRef.current = false;
    finalTranscriptRef.current = "";
    interimRef.current = "";
    setFinalTranscript("");
    setInterimTranscript("");

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
        // Rebuild full final transcript from all results (prevents duplication)
        let fullFinal = "";
        let currentInterim = "";
        for (let i = 0; i < ev.results.length; i++) {
          const res = ev.results[i];
          const txt = res[0]?.transcript || "";
          if (res.isFinal) {
            fullFinal += txt + " ";
          } else {
            currentInterim += txt + " ";
          }
        }
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
        }
      };

      recog.onend = () => {
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
        }
      };

      recog.onerror = (ev: SpeechRecognitionErrorEvent) => {
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
      };

      recog.start();
      activeRef.current = true;
      setState("listening");
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
    activeRef.current = false;
    setInterimTranscript("");
    const combined = finalTranscriptRef.current.trim() || interimRef.current.trim();
    // Do not auto-submit via stop() – caller decides. Just return transcript.
    return combined;
  }, [clearSilenceTimer]);

  const reset = useCallback(() => {
    cleanup();
    setInterimTranscript("");
    setFinalTranscript("");
    finalTranscriptRef.current = "";
    interimRef.current = "";
    lastSubmittedRef.current = "";
    submittedRef.current = false;
    hasSpokenRef.current = false;
    setState("idle");
  }, [cleanup]);

  const setOnSilence = useCallback((cb: (transcript: string) => void) => {
    onSilenceRef.current = cb;
  }, []);

  const liveTranscript = [finalTranscript, interimTranscript].filter(Boolean).join(" ").trim();

  return {
    state,
    interimTranscript,
    finalTranscript,
    liveTranscript,
    start,
    stop,
    reset,
    isSupported,
    setOnSilence,
  };
}
