import { useCallback, useEffect, useRef } from "react";

/** Captures one answer from the already-authorized interview microphone. */
export function useInterviewAudioCapture() {
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);

  const start = useCallback((stream: MediaStream | null) => {
    if (!stream || typeof MediaRecorder === "undefined") return false;
    const trackStream = new MediaStream(stream.getAudioTracks());
    if (!trackStream.getAudioTracks().length) return false;
    try {
      const preferred = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"]
        .find((type) => MediaRecorder.isTypeSupported(type));
      const recorder = preferred ? new MediaRecorder(trackStream, { mimeType: preferred }) : new MediaRecorder(trackStream);
      chunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data);
      };
      recorder.start();
      recorderRef.current = recorder;
      return true;
    } catch {
      return false;
    }
  }, []);

  const stop = useCallback((): Promise<Blob | null> => {
    const recorder = recorderRef.current;
    if (!recorder || recorder.state === "inactive") {
      recorderRef.current = null;
      return Promise.resolve(null);
    }
    return new Promise((resolve) => {
      const mimeType = recorder.mimeType || "audio/webm";
      recorder.onstop = () => {
        const blob = chunksRef.current.length ? new Blob(chunksRef.current, { type: mimeType }) : null;
        chunksRef.current = [];
        recorderRef.current = null;
        resolve(blob);
      };
      try { recorder.stop(); } catch { recorderRef.current = null; resolve(null); }
    });
  }, []);

  useEffect(() => () => {
    try { recorderRef.current?.stop(); } catch { /* ignore */ }
    recorderRef.current = null;
  }, []);

  return { start, stop };
}
