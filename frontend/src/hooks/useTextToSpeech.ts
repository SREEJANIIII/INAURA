import { useCallback, useEffect, useRef, useState } from "react";
import { fetchTtsAudio, SpeechAudioPlayer, type AudioLike } from "../services/tts";

export type TTSState = "idle" | "speaking" | "error";

export type UseTextToSpeechResult = {
  state: TTSState;
  speak: (text: string) => Promise<void>;
  stop: () => void;
  isSupported: boolean;
};

/**
 * NVIDIA voice via our FastAPI backend (`/interview/tts` → audio bytes →
 * browser Audio). Playback runs through SpeechAudioPlayer: the ONLY normal
 * completion signal is audio.onended (no timers), which is when the modal
 * transitions SPEAKING → LISTENING. Rejections surface the fallback UI.
 * The browser never contacts NVIDIA directly.
 */
export function useTextToSpeech(): UseTextToSpeechResult {
  const [state, setState] = useState<TTSState>("idle");
  const playerRef = useRef<SpeechAudioPlayer | null>(null);
  const requestRef = useRef(0);
  const pendingTextRef = useRef<string | null>(null);
  const pendingDoneRef = useRef<(() => void) | null>(null);
  if (playerRef.current == null) {
    playerRef.current = new SpeechAudioPlayer(
      (url) => new Audio(url) as unknown as AudioLike
    );
  }
  const isSupported = typeof window !== "undefined" && typeof Audio !== "undefined";

  const stop = useCallback(() => {
    requestRef.current += 1;
    pendingTextRef.current = null;
    pendingDoneRef.current?.();
    pendingDoneRef.current = null;
    playerRef.current?.stop();
    setState("idle");
  }, []);

  useEffect(() => stop, [stop]);

  const speak = useCallback(
    async (text: string) => {
      if (!text.trim()) return;
      const player = playerRef.current;
      if (!isSupported || !player) {
        throw new Error("Audio playback is not supported in this browser.");
      }
      // React re-renders can re-enter the same logical transition: an
      // identical in-flight request joins instead of fetching/playing twice.
      // An intentional Repeat after completion still creates a new request.
      // NOTE: no frontend retry — the backend owns the single controlled
      // retry; rate-limit/auth failures fail fast.
      if (pendingTextRef.current === text) {
        return new Promise<void>((resolve) => {
          const previous = pendingDoneRef.current;
          pendingDoneRef.current = () => {
            previous?.();
            resolve();
          };
        });
      }
      pendingTextRef.current = text;
      pendingDoneRef.current = null;
      const requestId = ++requestRef.current;
      setState("speaking");
      try {
        const blob = await fetchTtsAudio({ text });
        // Stopped or superseded while fetching: never start stale playback.
        if (requestId !== requestRef.current || !playerRef.current) return;
        await playerRef.current.play(blob);
        if (requestId === requestRef.current) setState("idle");
      } catch (error) {
        if (requestId === requestRef.current) {
          setState("error");
          throw error instanceof Error ? error : new Error("AI voice could not be generated.");
        }
        // Stale after stop(): settled silently already — swallow.
      } finally {
        if (pendingTextRef.current === text) {
          pendingTextRef.current = null;
          const done = pendingDoneRef.current as (() => void) | null;
          pendingDoneRef.current = null;
          done?.();
        }
      }
    }, [isSupported]
  );

  return { state, speak, stop, isSupported };
}
