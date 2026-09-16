import { useCallback, useEffect, useRef, useState } from "react";
import { fetchTtsAudio } from "../services/tts";

export type TTSState = "idle" | "speaking" | "error";

export type UseTextToSpeechResult = {
  state: TTSState;
  speak: (text: string) => Promise<void>;
  stop: () => void;
  isSupported: boolean;
};

/**
 * NVIDIA voice via our FastAPI backend (`/interview/tts` → audio bytes →
 * browser Audio). Resolves when playback ends so the modal transitions
 * SPEAKING → LISTENING from completion; rejects on failure so the fallback
 * UI appears. The browser never contacts NVIDIA directly.
 */
export function useTextToSpeech(): UseTextToSpeechResult {
  const [state, setState] = useState<TTSState>("idle");
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const urlRef = useRef<string | null>(null);
  const requestRef = useRef(0);
  const stopRef = useRef(false);
  const pendingTextRef = useRef<string | null>(null);
  const pendingDoneRef = useRef<(() => void) | null>(null);
  const isSupported = typeof window !== "undefined" && typeof Audio !== "undefined";

  const release = useCallback(() => {
    const audio = audioRef.current;
    if (audio) {
      audio.onended = null;
      audio.onerror = null;
      try {
        audio.pause();
      } catch {
        /* ignore */
      }
      try {
        audio.src = "";
      } catch {
        /* ignore */
      }
    }
    audioRef.current = null;
    if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    urlRef.current = null;
  }, []);

  const stop = useCallback(() => {
    stopRef.current = true;
    requestRef.current += 1;
    pendingTextRef.current = null;
    pendingDoneRef.current?.();
    pendingDoneRef.current = null;
    release();
    setState("idle");
  }, [release]);

  useEffect(() => stop, [stop]);

  const speak = useCallback(
    async (text: string) => {
      if (!text.trim()) return;
      if (!isSupported) throw new Error("Audio playback is not supported in this browser.");
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
      stopRef.current = false;
      const requestId = ++requestRef.current;
      release();
      setState("speaking");
      try {
        const blob = await fetchTtsAudio({ text });
        if (stopRef.current || requestId !== requestRef.current) return;
        const url = URL.createObjectURL(blob);
        urlRef.current = url;
        const audio = new Audio(url);
        audioRef.current = audio;
        await new Promise<void>((resolve, reject) => {
          audio.onended = () => resolve();
          audio.onerror = () => reject(new Error("AI voice playback failed."));
          void audio.play().catch(reject);
        });
        if (requestId === requestRef.current) setState("idle");
      } catch (error) {
        if (!stopRef.current && requestId === requestRef.current) setState("error");
        if (!stopRef.current) throw (error instanceof Error ? error : new Error("AI voice could not be generated."));
      } finally {
        if (pendingTextRef.current === text) {
          pendingTextRef.current = null;
          const done = pendingDoneRef.current as (() => void) | null;
          pendingDoneRef.current = null;
          done?.();
        }
        if (requestId === requestRef.current) release();
      }
    }, [isSupported, release]
  );

  return { state, speak, stop, isSupported };
}
