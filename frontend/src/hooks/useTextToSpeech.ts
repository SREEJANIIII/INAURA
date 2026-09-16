import { useCallback, useEffect, useRef, useState } from "react";

export type TTSState = "idle" | "speaking" | "unsupported" | "error";

export type UseTextToSpeechResult = {
  state: TTSState;
  speak: (text: string) => Promise<void>;
  stop: () => void;
  isSupported: boolean;
};

function getSynthesis(): SpeechSynthesis | null {
  if (typeof window === "undefined") return null;
  return window.speechSynthesis || null;
}

export function useTextToSpeech(): UseTextToSpeechResult {
  const [state, setState] = useState<TTSState>("idle");
  const resolveRef = useRef<(() => void) | null>(null);
  const speakingRef = useRef(false);
  const activeUtteranceRef = useRef<SpeechSynthesisUtterance | null>(null);
  const watchdogTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const isSupported =
    typeof window !== "undefined" && Boolean(window.speechSynthesis);

  const clearWatchdog = useCallback(() => {
    if (watchdogTimerRef.current !== null) {
      clearTimeout(watchdogTimerRef.current);
      watchdogTimerRef.current = null;
    }
  }, []);

  const stop = useCallback(() => {
    clearWatchdog();
    const synth = getSynthesis();
    if (synth) {
      try {
        synth.cancel();
      } catch {
        /* ignore */
      }
    }
    speakingRef.current = false;
    activeUtteranceRef.current = null;
    setState("idle");
    if (resolveRef.current) {
      const r = resolveRef.current;
      resolveRef.current = null;
      r();
    }
  }, [clearWatchdog]);

  useEffect(() => stop, [stop]);

  const speak = useCallback(
    (text: string): Promise<void> => {
      return new Promise((resolve) => {
        clearWatchdog();
        const synth = getSynthesis();
        if (!synth || !text.trim()) {
          if (!synth) setState("unsupported");
          resolve();
          return;
        }

        try {
          synth.cancel();
        } catch {
          /* ignore */
        }

        const utterance = new SpeechSynthesisUtterance(text);
        activeUtteranceRef.current = utterance; // Prevent garbage collection in Chrome

        utterance.lang = "en-US";
        utterance.rate = 1.0;
        utterance.pitch = 1.0;

        try {
          const voices = synth.getVoices() || [];
          const preferred = voices.find(
            (v) =>
              v.lang.startsWith("en") &&
              (v.name.includes("Google") ||
                v.name.includes("Natural") ||
                v.name.includes("Samantha") ||
                v.name.includes("Karen") ||
                v.name.includes("Daniel"))
          );
          if (preferred) utterance.voice = preferred;
        } catch {
          /* best-effort voice selection */
        }

        speakingRef.current = true;
        setState("speaking");

        const finish = () => {
          clearWatchdog();
          speakingRef.current = false;
          activeUtteranceRef.current = null;
          setState("idle");
          if (resolveRef.current) {
            const r = resolveRef.current;
            resolveRef.current = null;
            r();
          }
        };

        resolveRef.current = resolve;

        utterance.onend = () => {
          finish();
        };

        utterance.onerror = (ev: SpeechSynthesisErrorEvent) => {
          if (ev.error === "canceled" || ev.error === "interrupted") {
            finish();
            return;
          }
          console.warn("Speech synthesis error:", ev.error);
          setState("error");
          finish();
        };

        // Watchdog: If browser drops onend or hangs, automatically finish
        const estimatedMs = Math.max(8000, text.length * 120);
        watchdogTimerRef.current = setTimeout(() => {
          if (speakingRef.current) {
            console.warn("Speech synthesis watchdog triggered after", estimatedMs, "ms");
            finish();
          }
        }, estimatedMs);

        try {
          if (synth.paused) {
            synth.resume();
          }
          synth.speak(utterance);
          if (synth.paused) {
            synth.resume();
          }
        } catch {
          speakingRef.current = false;
          activeUtteranceRef.current = null;
          setState("error");
          finish();
        }
      });
    },
    [clearWatchdog]
  );

  return { state, speak, stop, isSupported };
}