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
<<<<<<< HEAD
  const utteranceRef = useRef<SpeechSynthesisUtterance | null>(null);
=======
  const speakingRef = useRef(false);
  const activeUtteranceRef = useRef<SpeechSynthesisUtterance | null>(null);
  const watchdogTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
>>>>>>> cd816cd7af05b78146197492a0c4f6a7d6cd19d9

  const isSupported = typeof window !== "undefined" && Boolean(window.speechSynthesis);

<<<<<<< HEAD
  const stop = useCallback(() => {
    const synth = getSynthesis();
    if (synth) {
      try {
        synth.cancel();
      } catch {
        /* ignore */
      }
    }
    utteranceRef.current = null;
    setState("idle");
    if (resolveRef.current) {
      const r = resolveRef.current;
      resolveRef.current = null;
      r();
=======
  const clearWatchdog = useCallback(() => {
    if (watchdogTimerRef.current !== null) {
      clearTimeout(watchdogTimerRef.current);
      watchdogTimerRef.current = null;
>>>>>>> cd816cd7af05b78146197492a0c4f6a7d6cd19d9
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
<<<<<<< HEAD
        const trimmed = text.trim();
        if (!synth || !trimmed) {
=======
        if (!synth || !text.trim()) {
>>>>>>> cd816cd7af05b78146197492a0c4f6a7d6cd19d9
          if (!synth) setState("unsupported");
          resolve();
          return;
        }

<<<<<<< HEAD
        // Cancel any ongoing speech
        try {
          synth.cancel();
        } catch {
          /* ignore */
=======
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
>>>>>>> cd816cd7af05b78146197492a0c4f6a7d6cd19d9
        }

        // Wait a tick for cancel to take effect (some browsers need it)
        setTimeout(() => {
          const utterance = new SpeechSynthesisUtterance(trimmed);
          utteranceRef.current = utterance;
          utterance.lang = "en-US";
          utterance.rate = 1.0;
          utterance.pitch = 1.0;
          utterance.volume = 1.0;

          try {
            const voices = synth.getVoices?.() || [];
            const preferred = voices.find(
              (v) =>
                v.lang.startsWith("en") &&
                (v.name.includes("Google") || v.name.includes("Natural") || v.name.includes("Samantha") || v.default)
            );
            if (preferred) utterance.voice = preferred;
          } catch {
            /* voice selection is best-effort */
          }

          setState("speaking");
          resolveRef.current = () => {
            resolveRef.current = null;
            resolve();
          };

          utterance.onend = () => {
            utteranceRef.current = null;
            setState("idle");
            if (resolveRef.current) {
              const r = resolveRef.current;
              resolveRef.current = null;
              r();
            } else {
              resolve();
            }
          };

          utterance.onerror = (ev: SpeechSynthesisErrorEvent) => {
            utteranceRef.current = null;
            // 'canceled' / 'interrupted' are not errors when stop() is called
            const err = (ev as unknown as { error: string }).error;
            if (err === "canceled" || err === "interrupted") {
              setState("idle");
              if (resolveRef.current) {
                const r = resolveRef.current;
                resolveRef.current = null;
                r();
              } else {
                resolve();
              }
              return;
            }
            console.warn("Speech synthesis error:", err);
            setState("error");
            if (resolveRef.current) {
              const r = resolveRef.current;
              resolveRef.current = null;
              r();
            } else {
              resolve();
            }
          };

          try {
            synth.speak(utterance);
            // Some browsers require resume if paused
            if (synth.paused) {
              try {
                synth.resume();
              } catch {
                /* ignore */
              }
            }
          } catch {
            utteranceRef.current = null;
            setState("error");
            if (resolveRef.current) {
              const r = resolveRef.current;
              resolveRef.current = null;
              r();
            } else {
              resolve();
            }
          }
        }, 50);
      });
    },
    [clearWatchdog]
  );

  return { state, speak, stop, isSupported };
}
