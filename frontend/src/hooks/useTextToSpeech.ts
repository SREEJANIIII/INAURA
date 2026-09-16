import { useCallback, useEffect, useRef, useState } from "react";

export type TTSState = "idle" | "speaking" | "unsupported" | "error";

export type UseTextToSpeechResult = {
  state: TTSState;
  speak: (text: string) => Promise<void>;
  stop: () => void;
  isSupported: boolean;
};

interface SpeechSynthesisVoice {
  lang: string;
  name: string;
  localService: boolean;
  default: boolean;
}

interface SpeechSynthesisUtteranceEvent extends Event {
  error: string;
}

interface SpeechSynthesisWithWebkit extends SpeechSynthesis {
  getVoices(): SpeechSynthesisVoice[];
}

function getSynthesis(): SpeechSynthesisWithWebkit | null {
  if (typeof window === "undefined") return null;
  return (window.speechSynthesis as SpeechSynthesisWithWebkit) || null;
}

export function useTextToSpeech(): UseTextToSpeechResult {
  const [state, setState] = useState<TTSState>("idle");
  const resolveRef = useRef<(() => void) | null>(null);
  const speakingRef = useRef(false);

  const isSupported =
    typeof window !== "undefined" && Boolean(window.speechSynthesis);

  const stop = useCallback(() => {
    const synth = getSynthesis();
    if (synth) {
      try { synth.cancel(); } catch { /* ignore */ }
    }
    speakingRef.current = false;
    setState("idle");
    if (resolveRef.current) {
      resolveRef.current();
      resolveRef.current = null;
    }
  }, []);

  useEffect(() => stop, [stop]);

  const speak = useCallback(
    (text: string): Promise<void> => {
      return new Promise((resolve) => {
        const synth = getSynthesis();
        if (!synth || !text.trim()) {
          setState("unsupported");
          resolve();
          return;
        }

        try { synth.cancel(); } catch { /* ignore */ }

        const utterance = new SpeechSynthesisUtterance(text);
        utterance.lang = "en-US";
        utterance.rate = 1.0;
        utterance.pitch = 1.0;

        const voices = synth.getVoices?.() || [];
        const preferred = voices.find(
          (v) =>
            v.lang === "en-US" && (v.name.includes("Google") || v.name.includes("Natural") || v.name.includes("Samantha"))
        );
        if (preferred) utterance.voice = preferred;

        speakingRef.current = true;
        setState("speaking");
        resolveRef.current = () => { resolve(); resolveRef.current = null; };

        utterance.onend = () => {
          speakingRef.current = false;
          setState("idle");
          resolve();
          resolveRef.current = null;
        };

        utterance.onerror = (ev: SpeechSynthesisUtteranceEvent) => {
          if (ev.error === "canceled" || ev.error === "interrupted") {
            speakingRef.current = false;
            setState("idle");
            resolve();
            resolveRef.current = null;
            return;
          }
          console.warn("Speech synthesis error:", ev.error);
          speakingRef.current = false;
          setState("error");
          resolve();
          resolveRef.current = null;
        };

        try {
          synth.speak(utterance);
        } catch {
          speakingRef.current = false;
          setState("error");
          resolve();
          resolveRef.current = null;
        }
      });
    },
    []
  );

  return { state, speak, stop, isSupported };
}
