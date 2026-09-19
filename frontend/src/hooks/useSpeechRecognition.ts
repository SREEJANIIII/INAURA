import { useCallback, useEffect, useRef, useState } from "react";

export type SpeechState = "idle" | "listening" | "error" | "unsupported";

export type UseSpeechRecognitionOptions = {
  /** Ms of silence after speech before auto-stopping. Defaults to 2800ms. */
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
  hasSpoken: boolean;
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

/**
 * Normalizes common casing/formatting for technical terms from speech recognition
 * without altering candidate meaning or inventing words.
 */
export function normalizeTechnicalTerms(text: string): string {
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
    [/\b(git\s*hub)\b/gi, "GitHub"],
    [/\b(node\s*\.??\s*js)\b/gi, "Node.js"],
    [/\b(spring\s*boot)\b/gi, "Spring Boot"],
    [/\b(mongo\s*db|mongo)\b/gi, "MongoDB"],
    [/\b(j\s*w\s*t)\b/gi, "JWT"],
    [/\b(o\s*auth)\b/gi, "OAuth"],
    [/\b(ci\s*\/?\s*cd)\b/gi, "CI/CD"],
    [/\b(nvidia)\b/gi, "NVIDIA"],
    [/\b(groq)\b/gi, "Groq"],
  ];
  for (const [regex, replacement] of terms) {
    s = s.replace(regex, replacement);
  }
  return s;
}

/** The shape of one recognition result this module reads. */
type RecognitionResultLike = {
  readonly isFinal: boolean;
  readonly [index: number]: { readonly transcript: string };
};

/**
 * Split one recognition event into settled text and the browser's running guess.
 *
 * Only `final` results are settled. Interim results are re-delivered, reworded and
 * extended as the browser hears more, so anything that appends them verbatim ends
 * up repeating every half-finished phrase.
 */
export function splitRecognitionResults(event: {
  resultIndex: number;
  results: ArrayLike<RecognitionResultLike>;
}): { final: string; interim: string } {
  let final = "";
  let interim = "";
  for (let i = event.resultIndex; i < event.results.length; i++) {
    const result = event.results[i];
    if (!result) continue;
    if (result.isFinal) final += result[0].transcript;
    else interim += result[0].transcript;
  }
  return { final, interim };
}

/**
 * Append a newly finalized transcript chunk, guarding against browsers that
 * re-deliver the same final result (which would otherwise duplicate text).
 * Genuinely new content (different words) is always appended.
 */
export function mergeFinalTranscript(existing: string, chunk: string): string {
  const clean = chunk.trim();
  if (!clean) return existing;
  const base = existing.trim();
  if (!base) return clean;
  if (base === clean || base.endsWith(` ${clean}`)) return base;
  const baseWords = base.split(/\s+/);
  const chunkWords = clean.split(/\s+/);
  for (let size = Math.min(baseWords.length, chunkWords.length); size >= 2; size--) {
    if (baseWords.slice(-size).join(" ").toLowerCase() === chunkWords.slice(0, size).join(" ").toLowerCase()) {
      return `${base} ${chunkWords.slice(size).join(" ")}`.trim();
    }
  }
  return `${base} ${clean}`;
}

export function useSpeechRecognition(
  opts: UseSpeechRecognitionOptions = {}
): UseSpeechRecognitionResult {
  const { silenceTimeout = 2800 } = opts;
  const [state, setState] = useState<SpeechState>("idle");
  const [interimTranscript, setInterimTranscript] = useState("");
  const [finalTranscript, setFinalTranscript] = useState("");
  const [hasSpoken, setHasSpoken] = useState(false);

  const recogRef = useRef<SpeechRecognitionInstance | null>(null);
  const activeRef = useRef(false);
  const hasSpokenRef = useRef(false);
  const silenceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onSilenceRef = useRef<((t: string) => void) | null>(null);
  const finalTranscriptRef = useRef("");
  const interimTranscriptRef = useRef("");
  const isSubmittedRef = useRef(false);
  const restartAttemptsRef = useRef(0);

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
    const raw = transcript.trim();
    if (!raw || isSubmittedRef.current) return;
    isSubmittedRef.current = true;
    clearSilenceTimer();
    activeRef.current = false;
    try {
      recogRef.current?.stop();
    } catch {
      /* ignore */
    }
    setState("idle");
    onSilenceRef.current?.(raw);
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

  const cleanup = useCallback(() => {
    clearSilenceTimer();
    if (recogRef.current) {
      try {
        recogRef.current.abort();
      } catch {
        /* ignore */
      }
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

    // Reset cycle tracking
    clearSilenceTimer();
    isSubmittedRef.current = false;
    hasSpokenRef.current = false;
    setHasSpoken(false);
    setInterimTranscript("");
    interimTranscriptRef.current = "";
    // Note: finalTranscriptRef is preserved unless reset() was called,
    // but in normal question cycle reset() is called before start().

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
        const { final: newFinal, interim } = splitRecognitionResults(ev);

        if (newFinal) {
          const updated = mergeFinalTranscript(finalTranscriptRef.current, newFinal);
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
        }
      };

      recog.onend = () => {
        // If intentionally stopped or submitted, exit
        if (!activeRef.current || isSubmittedRef.current) {
          setState("idle");
          return;
        }

        // Recognition can end after a final result. Give the silence timer the
        // configured window to collect any last interim words instead of
        // submitting immediately from onend.
        if (hasSpokenRef.current) {
          scheduleSilenceTimer();
          return;
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
        if (ev.error === "not-allowed" || ev.error === "service-not-allowed" || ev.error === "audio-capture" || ev.error === "network") {
          activeRef.current = false;
          clearSilenceTimer();
          setState("error");
        }
      };

      activeRef.current = true;
      restartAttemptsRef.current = 0;
      try {
        recog.start();
      } catch {
        activeRef.current = false;
        setState("error");
        return;
      }
      setState("listening");
      // CRITICAL: Do NOT start silence timer here! We wait until candidate actually speaks!
    } catch {
      setState("error");
    }
  }, [isSupported, scheduleSilenceTimer, clearSilenceTimer]);

  const stop = useCallback(() => {
    clearSilenceTimer();
    activeRef.current = false;
    const combined = [finalTranscriptRef.current, interimTranscriptRef.current]
      .filter(Boolean)
      .join(" ")
      .trim();
    if (recogRef.current) {
      try {
        recogRef.current.stop();
      } catch {
        /* ignore */
      }
    }
    setInterimTranscript("");
    interimTranscriptRef.current = "";
    setState("idle");
    return combined;
  }, [clearSilenceTimer]);

  const reset = useCallback(() => {
    cleanup();
    setInterimTranscript("");
    setFinalTranscript("");
    setHasSpoken(false);
    finalTranscriptRef.current = "";
    interimTranscriptRef.current = "";
    hasSpokenRef.current = false;
    isSubmittedRef.current = false;
    restartAttemptsRef.current = 0;
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
