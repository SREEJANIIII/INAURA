import { useCallback, useEffect, useRef, useState } from "react";

export type MediaDeviceState = "idle" | "requesting" | "live" | "denied" | "unavailable" | "skipped";

export type UseMediaDevicesResult = {
  videoRef: React.RefObject<HTMLVideoElement | null>;
  camState: MediaDeviceState;
  micState: MediaDeviceState;
  micLevel: number;
  cameraEnabled: boolean;
  micEnabled: boolean;
  requestMedia: () => Promise<void>;
  toggleCamera: () => void;
  toggleMic: () => void;
  stopAll: () => void;
  error: string | null;
};

function stopTracks(stream: MediaStream | null) {
  stream?.getTracks().forEach((t) => {
    try { t.stop(); } catch { /* ignore */ }
  });
}

export function useMediaDevices(): UseMediaDevicesResult {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const rafRef = useRef<number | null>(null);

  const [camState, setCamState] = useState<MediaDeviceState>("idle");
  const [micState, setMicState] = useState<MediaDeviceState>("idle");
  const [micLevel, setMicLevel] = useState(0);
  const [cameraEnabled, setCameraEnabled] = useState(true);
  const [micEnabled, setMicEnabled] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const startMicMeter = useCallback((stream: MediaStream) => {
    try {
      const Ctx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      if (!Ctx) return;
      const ctx: AudioContext = new Ctx();
      audioCtxRef.current = ctx;
      const src = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 256;
      src.connect(analyser);
      const buf = new Uint8Array(analyser.frequencyBinCount);
      const tick = () => {
        analyser.getByteTimeDomainData(buf);
        let sum = 0;
        for (let i = 0; i < buf.length; i++) {
          const v = (buf[i] - 128) / 128;
          sum += v * v;
        }
        setMicLevel(Math.min(1, Math.sqrt(sum / buf.length) * 3));
        rafRef.current = requestAnimationFrame(tick);
      };
      tick();
    } catch {
      /* meter is best-effort */
    }
  }, []);

  const stopAll = useCallback(() => {
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
    try { audioCtxRef.current?.close(); } catch { /* ignore */ }
    audioCtxRef.current = null;
    stopTracks(streamRef.current);
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    setMicLevel(0);
  }, []);

  // Cleanup on unmount
  useEffect(() => stopAll, [stopAll]);

  const requestMedia = useCallback(async () => {
    setError(null);
    setCamState("requesting");
    setMicState("requesting");

    if (!navigator.mediaDevices?.getUserMedia) {
      setCamState("unavailable");
      setMicState("unavailable");
      setError("This browser does not support camera/microphone access.");
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
      stopTracks(streamRef.current);
      streamRef.current = stream;

      const hasVideo = stream.getVideoTracks().length > 0;
      const hasAudio = stream.getAudioTracks().length > 0;

      setCamState(hasVideo ? "live" : "unavailable");
      setMicState(hasAudio ? "live" : "unavailable");

      if (videoRef.current && hasVideo) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play().catch(() => undefined);
      }
      if (hasAudio) startMicMeter(stream);
    } catch (e) {
      const name = e instanceof DOMException ? e.name : "";
      const denied = name === "NotAllowedError" || name === "SecurityError";
      setCamState(denied ? "denied" : "unavailable");
      setMicState(denied ? "denied" : "unavailable");
      setError(
        denied
          ? "Camera/microphone permission was denied. You can continue without them."
          : "Camera/microphone are unavailable. You can continue without them."
      );
    }
  }, [startMicMeter]);

  const toggleCamera = useCallback(() => {
    const stream = streamRef.current;
    if (!stream) return;
    const videoTrack = stream.getVideoTracks()[0];
    if (!videoTrack) return;
    videoTrack.enabled = !videoTrack.enabled;
    setCameraEnabled(videoTrack.enabled);
  }, []);

  const toggleMic = useCallback(() => {
    const stream = streamRef.current;
    if (!stream) return;
    const audioTrack = stream.getAudioTracks()[0];
    if (!audioTrack) return;
    audioTrack.enabled = !audioTrack.enabled;
    setMicEnabled(audioTrack.enabled);
    if (!audioTrack.enabled) setMicLevel(0);
  }, []);

  // Sync video element when camState changes
  useEffect(() => {
    if (camState === "live" && videoRef.current && streamRef.current) {
      videoRef.current.srcObject = streamRef.current;
    }
  }, [camState]);

  return {
    videoRef,
    camState,
    micState,
    micLevel,
    cameraEnabled,
    micEnabled,
    requestMedia,
    toggleCamera,
    toggleMic,
    stopAll,
    error,
  };
}
