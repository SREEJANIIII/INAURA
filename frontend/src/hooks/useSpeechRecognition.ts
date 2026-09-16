import { useCallback, useEffect, useRef, useState } from "react";

export type SpeechState = "idle" | "listening" | "error" | "unsupported";

export type UseSpeechRecognitionOptions = {
  /** Ms of silence before auto-stopping. 0 = disabled. */
  silenceTimeout?: number;
};

export type UseSpeechRecognitionResult = {
  state: SpeechState;
  interimTranscript: string;
  finalTranscript: string;
  /** Combined final + interim for live display. */
  liveTranscript: string;
  start: () => void;
  stop: () => string;
  reset: () => void;
  isSupported: boolean;
  /** Wire the silence callback. Call this to connect your handler. */
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
  const { silenceTimeout = 0 } = opts;
  const [state, setState] = useState<SpeechState>("idle");
  const [interimTranscript, setInterimTranscript] = useState("");
  const [finalTranscript, setFinalTranscript] = useState("");
  const recogRef = useRef<SpeechRecognitionInstance | null>(null);
  const activeRef = useRef(false);
  const silenceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onSilenceRef = useRef<((t: string) => void) | null>(null);
  const finalTranscriptRef = useRef("");
  const lastSubmittedRef = useRef("");

  const isSupported =
    typeof window !== "undefined" &&
    Boolean(window.SpeechRecognition || window.webkitSpeechRecognition);

  const clearSilenceTimer = useCallback(() => {
    if (silenceTimerRef.current !== null) {
      clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = null;
    }
  }, []);

  const submitTranscript = useCallback((transcript: string) => {
    const trimmed = transcript.trim();
    if (!trimmed || trimmed === lastSubmittedRef.current) return;
    lastSubmittedRef.current = trimmed;
    onSilenceRef.current?.(trimmed);
  }, []);

  const resetSilenceTimer = useCallback(
    (currentFinal: string) => {
      if (silenceTimeout <= 0) return;
      clearSilenceTimer();
      silenceTimerRef.current = setTimeout(() => {
        if (activeRef.current) {
          try { recogRef.current?.stop(); } catch { /* ignore */ }
          activeRef.current = false;
          setState("idle");
          setInterimTranscript("");
          submitTranscript(currentFinal);
        }
      }, silenceTimeout);
    },
    [silenceTimeout, clearSilenceTimer, submitTranscript]
  );

  const cleanup = useCallback(() => {
    clearSilenceTimer();
    if (recogRef.current) {
      try { recogRef.current.abort(); } catch { /* ignore */ }
      recogRef.current = null;
    }
    activeRef.current = false;
  }, [clearSilenceTimer]);

  useEffect(() => cleanup, [cleanup]);

  const start = useCallback(() => {
    if (!isSupported) {
      setState("unsupported");
      return;
    }
    if (activeRef.current) return;

    try {
      const Impl = window.SpeechRecognition || window.webkitSpeechRecognition;
      if (!Impl) { setState("unsupported"); return; }
      const recog = new Impl();
      recogRef.current = recog;
      recog.lang = "en-US";
      recog.interimResults = true;
      recog.continuous = true;
      recog.maxAlternatives = 1;

      recog.onresult = (ev: SpeechRecognitionEvent) => {
        let interim = "";
        let final_ = "";
        for (let i = ev.resultIndex; i < ev.results.length; i++) {
          const t = ev.results[i][0].transcript;
          if (ev.results[i].isFinal) {
            final_ += t;
          } else {
            interim += t;
          }
        }
        if (final_) {
          setFinalTranscript((prev) => {
            const next = prev ? `${prev} ${final_}`.trim() : final_.trim();
            finalTranscriptRef.current = next;
            return next;
          });
        }
        setInterimTranscript(interim);
        // Reset silence timer on any speech activity
        if (interim || final_) {
          setFinalTranscript((prev) => {
            const combined = [prev, interim].filter(Boolean).join(" ").trim();
            resetSilenceTimer(combined);
            return prev;
          });
        }
      };

      recog.onend = () => {
        if (!activeRef.current) return;
        activeRef.current = false;
        clearSilenceTimer();
        const transcript = finalTranscriptRef.current.trim();
        setInterimTranscript("");
        // If recognition ended with meaningful content, submit it
        if (transcript && transcript !== lastSubmittedRef.current) {
          setState("idle");
          submitTranscript(transcript);
        } else {
          setState("idle");
        }
      };

      recog.onerror = (ev: SpeechRecognitionErrorEvent) => {
        if (ev.error === "no-speech" || ev.error === "aborted") {
          activeRef.current = false;
          clearSilenceTimer();
          setState("idle");
          setInterimTranscript("");
          return;
        }
        console.warn("Speech recognition error:", ev.error);
        activeRef.current = false;
        clearSilenceTimer();
        setState("error");
        setInterimTranscript("");
      };

      recog.start();
      activeRef.current = true;
      setState("listening");
      resetSilenceTimer("");
    } catch {
      setState("error");
    }
  }, [isSupported, resetSilenceTimer, clearSilenceTimer, submitTranscript]);

  const stop = useCallback(() => {
    clearSilenceTimer();
    if (recogRef.current && activeRef.current) {
      try { recogRef.current.stop(); } catch { /* ignore */ }
    }
    activeRef.current = false;
    setInterimTranscript("");
    const combined = finalTranscriptRef.current.trim();
    return combined;
  }, [clearSilenceTimer]);

  const reset = useCallback(() => {
    cleanup();
    setInterimTranscript("");
    setFinalTranscript("");
    finalTranscriptRef.current = "";
    lastSubmittedRef.current = "";
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
