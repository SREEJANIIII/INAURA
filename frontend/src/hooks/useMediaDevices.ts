import { useCallback, useEffect, useRef, useState } from "react";

export type MediaDeviceState = "idle" | "requesting" | "live" | "denied" | "unavailable" | "off" | "muted" | "skipped";

export type MediaResult = {
  camera: "live" | "denied" | "unavailable";
  microphone: "live" | "denied" | "unavailable";
  /** At least one device is usable for the interview. */
  usable: boolean;
};

export type UseMediaDevicesResult = {
  videoRef: React.RefObject<HTMLVideoElement | null>;
  setVideoRef: (el: HTMLVideoElement | null) => void;
  camState: MediaDeviceState;
  micState: MediaDeviceState;
  micLevel: number;
  cameraEnabled: boolean;
  micEnabled: boolean;
  /** Request both camera + mic. Returns structured result. */
  requestMedia: () => Promise<MediaResult>;
  /** Retry only the camera. */
  requestCamera: () => Promise<"live" | "denied" | "unavailable">;
  /** Retry only the microphone. */
  requestMicrophone: () => Promise<"live" | "denied" | "unavailable">;
  /** Current microphone-bearing stream for optional server-side transcription. */
  getAudioStream: () => MediaStream | null;
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

function kindFromError(e: unknown): "denied" | "unavailable" {
  const name = e instanceof DOMException ? e.name : "";
  return name === "NotAllowedError" || name === "SecurityError" ? "denied" : "unavailable";
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
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
      try { audioCtxRef.current?.close(); } catch { /* ignore */ }
      audioCtxRef.current = null;
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

  const attachVideo = useCallback(async (stream: MediaStream) => {
    const el = videoRef.current;
    if (!el) return;
    const hasVideo = stream.getVideoTracks().length > 0;
    if (hasVideo) {
      el.srcObject = stream;
      try { await el.play(); } catch { /* autoplay blocked */ }
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
    setCamState("idle");
    setMicState("idle");
    setCameraEnabled(true);
    setMicEnabled(true);
  }, []);

  // Cleanup on unmount
  useEffect(() => stopAll, [stopAll]);

  const mergeStream = useCallback((existing: MediaStream | null, patch: MediaStream | null): MediaStream => {
    // Replace tracks by kind so a retry cannot leave a stopped track in the preview.
    const tracks = existing ? [...existing.getTracks()] : [];
    for (const nextTrack of patch?.getTracks() ?? []) {
      for (const oldTrack of tracks.filter((track) => track.kind === nextTrack.kind)) {
        oldTrack.stop();
        const index = tracks.indexOf(oldTrack);
        if (index >= 0) tracks.splice(index, 1);
      }
      tracks.push(nextTrack);
    }
    return new MediaStream(tracks);
  }, []);

  const requestMedia = useCallback(async (): Promise<MediaResult> => {
    setError(null);
    setCamState("requesting");
    setMicState("requesting");

    if (!navigator.mediaDevices?.getUserMedia) {
      setCamState("unavailable");
      setMicState("unavailable");
      setError("This browser does not support camera/microphone access.");
      return { camera: "unavailable", microphone: "unavailable", usable: false };
    }

    let camResult: "live" | "denied" | "unavailable";
    let micResult: "live" | "denied" | "unavailable";

    // Request both together first
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
      const hasVideo = stream.getVideoTracks().length > 0;
      const hasAudio = stream.getAudioTracks().length > 0;
      camResult = hasVideo ? "live" : "unavailable";
      micResult = hasAudio ? "live" : "unavailable";

      // Merge with existing tracks
      const merged = mergeStream(streamRef.current, stream);
      // Stop the old tracks we just replaced
      if (streamRef.current) {
        for (const old of streamRef.current.getTracks()) {
          if (!merged.getTracks().includes(old)) old.stop();
        }
      }
      streamRef.current = merged;
      setCamState(camResult === "live" ? "live" : "unavailable");
      setMicState(micResult === "live" ? "live" : "unavailable");
      if (micResult === "live") startMicMeter(merged);
      await attachVideo(merged);
    } catch (jointErr) {
      // Joint request failed — try individually
      camResult = kindFromError(jointErr);
      micResult = kindFromError(jointErr);
      setCamState(camResult === "denied" ? "denied" : "unavailable");
      setMicState(micResult === "denied" ? "denied" : "unavailable");
    }

    // If mic specifically failed, try mic alone (camera may be working from old stream)
    if (micResult !== "live") {
      try {
        const micStream = await navigator.mediaDevices.getUserMedia({ video: false, audio: true });
        micResult = micStream.getAudioTracks().length > 0 ? "live" : "unavailable";
        if (micResult === "live") {
          const merged = mergeStream(streamRef.current, micStream);
          streamRef.current = merged;
          setMicState("live");
          startMicMeter(merged);
        }
      } catch (micErr) {
        micResult = kindFromError(micErr);
        setMicState(micResult === "denied" ? "denied" : "unavailable");
      }
    }

    // If cam specifically failed, try camera alone
    if (camResult !== "live") {
      try {
        const camStream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
        camResult = camStream.getVideoTracks().length > 0 ? "live" : "unavailable";
        if (camResult === "live") {
          const merged = mergeStream(streamRef.current, camStream);
          streamRef.current = merged;
          setCamState("live");
          await attachVideo(merged);
        }
      } catch (camErr) {
        camResult = kindFromError(camErr);
        setCamState(camResult === "denied" ? "denied" : "unavailable");
      }
    }

    const usable = camResult === "live" || micResult === "live";
    if (!usable) {
      setError("Camera and microphone are both unavailable. Please check your browser permissions.");
    } else if (camResult !== "live") {
      setError("Camera unavailable — continuing with microphone only.");
    } else if (micResult !== "live") {
      setError("Microphone unavailable — you can still see the interviewer but may need to type answers.");
    }

    return { camera: camResult, microphone: micResult, usable };
  }, [mergeStream, attachVideo, startMicMeter]);

  const requestCamera = useCallback(async (): Promise<"live" | "denied" | "unavailable"> => {
    if (!navigator.mediaDevices?.getUserMedia) return "unavailable";
    setCamState("requesting");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
      const hasVideo = stream.getVideoTracks().length > 0;
      if (!hasVideo) { setCamState("unavailable"); return "unavailable"; }
      const merged = mergeStream(streamRef.current, stream);
      if (streamRef.current) {
        for (const old of streamRef.current.getVideoTracks()) old.stop();
      }
      streamRef.current = merged;
      setCamState("live");
      await attachVideo(merged);
      return "live";
    } catch (e) {
      const r = kindFromError(e);
      setCamState(r === "denied" ? "denied" : "unavailable");
      return r;
    }
  }, [mergeStream, attachVideo]);

  const requestMicrophone = useCallback(async (): Promise<"live" | "denied" | "unavailable"> => {
    if (!navigator.mediaDevices?.getUserMedia) return "unavailable";
    setMicState("requesting");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: false, audio: true });
      const hasAudio = stream.getAudioTracks().length > 0;
      if (!hasAudio) { setMicState("unavailable"); return "unavailable"; }
      const merged = mergeStream(streamRef.current, stream);
      if (streamRef.current) {
        for (const old of streamRef.current.getAudioTracks()) old.stop();
      }
      streamRef.current = merged;
      setMicState("live");
      startMicMeter(merged);
      return "live";
    } catch (e) {
      const r = kindFromError(e);
      setMicState(r === "denied" ? "denied" : "unavailable");
      return r;
    }
  }, [mergeStream, startMicMeter]);

  const setVideoRef = useCallback((el: HTMLVideoElement | null) => {
    videoRef.current = el;
    if (el && streamRef.current && streamRef.current.getVideoTracks().length > 0) {
      el.srcObject = streamRef.current;
      el.play().catch(() => {});
    }
  }, []);

  const toggleCamera = useCallback(() => {
    const stream = streamRef.current;
    if (!stream) return;
    const videoTrack = stream.getVideoTracks()[0];
    if (!videoTrack) return;
    const next = !videoTrack.enabled;
    videoTrack.enabled = next;
    setCameraEnabled(next);
    setCamState(next ? "live" : "off");
  }, []);

  const toggleMic = useCallback(() => {
    const stream = streamRef.current;
    if (!stream) return;
    const audioTrack = stream.getAudioTracks()[0];
    if (!audioTrack) return;
    const next = !audioTrack.enabled;
    audioTrack.enabled = next;
    setMicEnabled(next);
    setMicState(next ? "live" : "muted");
    if (!next) setMicLevel(0);
  }, []);

  const getAudioStream = useCallback(() => streamRef.current, []);

  // Sync video element when camState changes
  useEffect(() => {
    if ((camState === "live" || camState === "off") && videoRef.current && streamRef.current) {
      if (videoRef.current.srcObject !== streamRef.current) {
        videoRef.current.srcObject = streamRef.current;
        videoRef.current.play().catch(() => {});
      }
    }
  }, [camState]);

  return {
    videoRef,
    setVideoRef,
    camState,
    micState,
    micLevel,
    cameraEnabled,
    micEnabled,
    requestMedia,
    requestCamera,
    requestMicrophone,
    getAudioStream,
    toggleCamera,
    toggleMic,
    stopAll,
    error,
  };
}
