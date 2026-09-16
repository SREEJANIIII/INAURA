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
  const utteranceRef = useRef<SpeechSynthesisUtterance | null>(null);

  const isSupported = typeof window !== "undefined" && Boolean(window.speechSynthesis);

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
    }
  }, []);

  useEffect(() => stop, [stop]);

  const speak = useCallback(
    (text: string): Promise<void> => {
      return new Promise((resolve) => {
        const synth = getSynthesis();
        const trimmed = text.trim();
        if (!synth || !trimmed) {
          if (!synth) setState("unsupported");
          resolve();
          return;
        }

        // Cancel any ongoing speech
        try {
          synth.cancel();
        } catch {
          /* ignore */
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
    []
  );

  return { state, speak, stop, isSupported };
}
