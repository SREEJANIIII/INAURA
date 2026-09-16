import { useCallback, useEffect, useRef, useState } from "react";

<<<<<<< HEAD
export type MediaDeviceState = "idle" | "requesting" | "live" | "denied" | "unavailable" | "off" | "muted";
=======
export type MediaDeviceState = "idle" | "requesting" | "live" | "denied" | "unavailable" | "off" | "muted" | "skipped";
>>>>>>> cd816cd7af05b78146197492a0c4f6a7d6cd19d9

export type MediaResult = {
  camera: "live" | "denied" | "unavailable";
  microphone: "live" | "denied" | "unavailable";
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
  stream: MediaStream | null;
  requestMedia: () => Promise<MediaResult>;
  requestCamera: () => Promise<"live" | "denied" | "unavailable">;
  requestMicrophone: () => Promise<"live" | "denied" | "unavailable">;
  toggleCamera: () => void;
  toggleMic: () => void;
  stopAll: () => void;
  error: string | null;
};

function stopTracks(stream: MediaStream | null) {
  stream?.getTracks().forEach((t) => {
    try {
      t.stop();
    } catch {
      /* ignore */
    }
  });
}

function kindFromError(e: unknown): "denied" | "unavailable" {
  const name = e instanceof DOMException ? e.name : (e as Error)?.name || "";
  if (name === "NotAllowedError" || name === "SecurityError" || name === "PermissionDeniedError") return "denied";
  return "unavailable";
}

export function useMediaDevices(): UseMediaDevicesResult {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const rafRef = useRef<number | null>(null);
  const attachedStreamRef = useRef<MediaStream | null>(null);

  const [camState, setCamState] = useState<MediaDeviceState>("idle");
  const [micState, setMicState] = useState<MediaDeviceState>("idle");
  const [micLevel, setMicLevel] = useState(0);
  const [cameraEnabled, setCameraEnabled] = useState(true);
  const [micEnabled, setMicEnabled] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [streamVersion, setStreamVersion] = useState(0);
  const [stream, setStream] = useState<MediaStream | null>(null);

  const startMicMeter = useCallback((stream: MediaStream) => {
    try {
      if (audioCtxRef.current) {
        try {
          audioCtxRef.current.close();
        } catch {
          /* ignore */
        }
        audioCtxRef.current = null;
      }
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
      const hasAudio = stream.getAudioTracks().length > 0 && stream.getAudioTracks().some((t) => t.enabled);
      if (!hasAudio) {
        setMicLevel(0);
        return;
      }
      const Ctx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      if (!Ctx) return;
      const ctx: AudioContext = new Ctx();
      audioCtxRef.current = ctx;
      const src = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 256;
      analyserRef.current = analyser;
      src.connect(analyser);
      const buf = new Uint8Array(analyser.frequencyBinCount);
      const tick = () => {
        if (!audioCtxRef.current || !analyserRef.current) return;
        analyser.getByteTimeDomainData(buf);
        let sum = 0;
        for (let i = 0; i < buf.length; i++) {
          const v = (buf[i] - 128) / 128;
          sum += v * v;
        }
        const level = Math.min(1, Math.sqrt(sum / buf.length) * 3.5);
        setMicLevel(level);
        rafRef.current = requestAnimationFrame(tick);
      };
      tick();
    } catch {
      /* meter is best-effort */
    }
  }, []);

  const stopMicMeter = useCallback(() => {
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
    try {
      audioCtxRef.current?.close();
    } catch {
      /* ignore */
    }
    audioCtxRef.current = null;
    analyserRef.current = null;
    setMicLevel(0);
    setCamState("idle");
    setMicState("idle");
    setCameraEnabled(true);
    setMicEnabled(true);
  }, []);

  const attachVideo = useCallback(async (stream: MediaStream | null) => {
    const el = videoRef.current;
    if (!el || !stream) return;
    const hasVideo = stream.getVideoTracks().length > 0;
    if (!hasVideo) return;
    if (attachedStreamRef.current === stream && el.srcObject === stream) return;
    try {
      el.srcObject = stream;
      attachedStreamRef.current = stream;
      // playsInline + muted + autoPlay are set in JSX
      const playPromise = el.play();
      if (playPromise) await playPromise.catch(() => {});
    } catch {
      /* autoplay blocked is ok, still attached */
    }
  }, []);

  // Keep video attached when stream changes or when video element mounts
  // This effect handles the case where stream is acquired before <video> exists
  useEffect(() => {
    if (streamRef.current && videoRef.current) {
      void attachVideo(streamRef.current);
    }
  }, [streamVersion, camState, attachVideo]);

  const stopAll = useCallback(() => {
    stopMicMeter();
    stopTracks(streamRef.current);
    streamRef.current = null;
    setStream(null);
    attachedStreamRef.current = null;
    if (videoRef.current) {
      try {
        videoRef.current.srcObject = null;
      } catch {
        /* ignore */
      }
    }
    setStreamVersion((v) => v + 1);
  }, [stopMicMeter]);

  useEffect(() => {
    return () => {
      stopAll();
    };
  }, [stopAll]);

  const mergeTracks = useCallback((existing: MediaStream | null, incoming: MediaStream): MediaStream => {
    if (!existing) return incoming;
    // Create a new stream that contains latest tracks for each kind
    const existingTracks = existing.getTracks();
    const incomingTracks = incoming.getTracks();

    // Map incoming by kind
    const incomingByKind = new Map<string, MediaStreamTrack>();
    incomingTracks.forEach((t) => incomingByKind.set(t.kind, t));

    const finalTracks: MediaStreamTrack[] = [];

    // For each kind, prefer incoming if present, else keep existing
    const kinds = new Set<string>([...existingTracks.map((t) => t.kind), ...incomingTracks.map((t) => t.kind)]);
    kinds.forEach((kind) => {
      const incomingTrack = incomingByKind.get(kind);
      if (incomingTrack) {
        // Stop old track of same kind
        existingTracks
          .filter((t) => t.kind === kind)
          .forEach((t) => {
            try {
              t.stop();
            } catch {
              /* ignore */
            }
          });
        finalTracks.push(incomingTrack);
      } else {
        // Keep existing tracks of this kind
        existingTracks
          .filter((t) => t.kind === kind)
          .forEach((t) => finalTracks.push(t));
      }
    });

    return new MediaStream(finalTracks);
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
    let combinedStream: MediaStream | null = streamRef.current;

    // Try joint request first (user gesture)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
      const hasVideo = stream.getVideoTracks().length > 0;
      const hasAudio = stream.getAudioTracks().length > 0;
      camResult = hasVideo ? "live" : "unavailable";
      micResult = hasAudio ? "live" : "unavailable";

      if (combinedStream) {
        // Merge existing with new joint stream
        combinedStream = mergeTracks(combinedStream, stream);
        // If merge created a new stream, the old joint stream's tracks that were not merged are already stopped inside mergeTracks
        // But if we didn't use mergeTracks correctly for joint, we need to handle
        // For joint, we just replace entirely to avoid duplication
        // Actually for joint success, we can just use the new stream plus any existing that wasn't in new?
        // Simpler: if we had existing, merge; else use new
      } else {
        combinedStream = stream;
      }

      // If joint succeeded but had only one kind, we still have that kind
      if (camResult === "live") setCamState("live");
      else setCamState("unavailable");
      if (micResult === "live") setMicState("live");
      else setMicState("unavailable");
    } catch (jointErr) {
      const jointKind = kindFromError(jointErr);
      camResult = jointKind;
      micResult = jointKind;
      // Don't set states yet, will try individually
    }

    // If joint didn't give us both, try individually
    if (camResult !== "live") {
      try {
        const camStream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
        const hasVideo = camStream.getVideoTracks().length > 0;
        if (hasVideo) {
          camResult = "live";
          if (combinedStream) {
            combinedStream = mergeTracks(combinedStream, camStream);
          } else {
            combinedStream = camStream;
          }
          setCamState("live");
        } else {
          camResult = "unavailable";
          setCamState("unavailable");
          camStream.getTracks().forEach((t) => t.stop());
        }
      } catch (e) {
        camResult = kindFromError(e);
        setCamState(camResult);
      }
    }

    if (micResult !== "live") {
      try {
        const micStream = await navigator.mediaDevices.getUserMedia({ video: false, audio: true });
        const hasAudio = micStream.getAudioTracks().length > 0;
        if (hasAudio) {
          micResult = "live";
          if (combinedStream) {
            combinedStream = mergeTracks(combinedStream, micStream);
          } else {
            combinedStream = micStream;
          }
          setMicState("live");
        } else {
          micResult = "unavailable";
          setMicState("unavailable");
          micStream.getTracks().forEach((t) => t.stop());
        }
      } catch (e) {
        micResult = kindFromError(e);
        setMicState(micResult);
      }
    }

    // Update stream ref
    if (combinedStream) {
      streamRef.current = combinedStream;
      setStream(combinedStream);
      // Sync enabled flags
      const vTrack = combinedStream.getVideoTracks()[0];
      const aTrack = combinedStream.getAudioTracks()[0];
      setCameraEnabled(vTrack ? vTrack.enabled : false);
      setMicEnabled(aTrack ? aTrack.enabled : false);
      if (micResult === "live") startMicMeter(combinedStream);
      await attachVideo(combinedStream);
      setStreamVersion((v) => v + 1);
    }

    const usable = camResult === "live" || micResult === "live";
    if (!usable) {
      if (camResult === "denied" || micResult === "denied") {
        setError("Camera and microphone permission denied. Please allow access in your browser and try again.");
      } else {
        setError("Camera and microphone are both unavailable. Please check your devices and browser permissions.");
      }
    } else if (camResult !== "live" && micResult === "live") {
      setError("Camera unavailable — continuing with microphone only. You can recheck camera anytime.");
      // Keep error but allow interview
      setTimeout(() => setError(null), 4000);
    } else if (micResult !== "live" && camResult === "live") {
      setError("Microphone unavailable — interview will continue with camera only. You can recheck microphone or type answers.");
      setTimeout(() => setError(null), 4000);
    } else {
      setError(null);
    }

    return { camera: camResult, microphone: micResult, usable };
  }, [attachVideo, mergeTracks, startMicMeter]);

  const requestCamera = useCallback(async (): Promise<"live" | "denied" | "unavailable"> => {
    if (!navigator.mediaDevices?.getUserMedia) {
      setCamState("unavailable");
      return "unavailable";
    }
    setCamState("requesting");
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
      const hasVideo = stream.getVideoTracks().length > 0;
      if (!hasVideo) {
        setCamState("unavailable");
        stream.getTracks().forEach((t) => t.stop());
        setError("No camera found on this device.");
        return "unavailable";
      }
      const merged = streamRef.current ? mergeTracks(streamRef.current, stream) : stream;
      streamRef.current = merged;
      setStream(merged);
      const vTrack = merged.getVideoTracks()[0];
      setCameraEnabled(vTrack ? vTrack.enabled : true);
      setCamState("live");
      await attachVideo(merged);
      setStreamVersion((v) => v + 1);
      setError(null);
      return "live";
    } catch (e) {
      const r = kindFromError(e);
      setCamState(r);
      if (r === "denied") setError("Camera permission denied. Please allow camera access in your browser settings and try again.");
      else setError("Camera unavailable — no camera found or it is in use by another app.");
      return r;
    }
  }, [attachVideo, mergeTracks]);

  const requestMicrophone = useCallback(async (): Promise<"live" | "denied" | "unavailable"> => {
    if (!navigator.mediaDevices?.getUserMedia) {
      setMicState("unavailable");
      return "unavailable";
    }
    setMicState("requesting");
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: false, audio: true });
      const hasAudio = stream.getAudioTracks().length > 0;
      if (!hasAudio) {
        setMicState("unavailable");
        stream.getTracks().forEach((t) => t.stop());
        setError("No microphone found on this device.");
        return "unavailable";
      }
      const merged = streamRef.current ? mergeTracks(streamRef.current, stream) : stream;
      streamRef.current = merged;
      setStream(merged);
      const aTrack = merged.getAudioTracks()[0];
      setMicEnabled(aTrack ? aTrack.enabled : true);
      setMicState("live");
      startMicMeter(merged);
      setStreamVersion((v) => v + 1);
      setError(null);
      return "live";
    } catch (e) {
      const r = kindFromError(e);
      setMicState(r);
      if (r === "denied") setError("Microphone permission denied. Please allow microphone access and try again.");
      else setError("Microphone unavailable — no microphone found or it is in use.");
      return r;
    }
  }, [mergeTracks, startMicMeter]);

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
<<<<<<< HEAD
    if (!videoTrack) {
      // Try to request camera if none exists
      void requestCamera();
      return;
    }
    videoTrack.enabled = !videoTrack.enabled;
    setCameraEnabled(videoTrack.enabled);
    setCamState(videoTrack.enabled ? "live" : "off");
    if (videoTrack.enabled) {
      void attachVideo(stream);
    }
  }, [requestCamera, attachVideo]);
=======
    if (!videoTrack) return;
    const next = !videoTrack.enabled;
    videoTrack.enabled = next;
    setCameraEnabled(next);
    setCamState(next ? "live" : "off");
  }, []);
>>>>>>> cd816cd7af05b78146197492a0c4f6a7d6cd19d9

  const toggleMic = useCallback(() => {
    const stream = streamRef.current;
    if (!stream) return;
    const audioTrack = stream.getAudioTracks()[0];
<<<<<<< HEAD
    if (!audioTrack) {
      void requestMicrophone();
      return;
    }
    audioTrack.enabled = !audioTrack.enabled;
    setMicEnabled(audioTrack.enabled);
    setMicState(audioTrack.enabled ? "live" : "muted");
    if (audioTrack.enabled) {
      startMicMeter(stream);
    } else {
      setMicLevel(0);
      stopMicMeter();
      // Restart meter after? No, muted means disabled
=======
    if (!audioTrack) return;
    const next = !audioTrack.enabled;
    audioTrack.enabled = next;
    setMicEnabled(next);
    setMicState(next ? "live" : "muted");
    if (!next) setMicLevel(0);
  }, []);

  // Sync video element when camState changes
  useEffect(() => {
    if ((camState === "live" || camState === "off") && videoRef.current && streamRef.current) {
      if (videoRef.current.srcObject !== streamRef.current) {
        videoRef.current.srcObject = streamRef.current;
        videoRef.current.play().catch(() => {});
      }
>>>>>>> cd816cd7af05b78146197492a0c4f6a7d6cd19d9
    }
  }, [requestMicrophone, startMicMeter, stopMicMeter]);

  // Attach video when camState becomes live or stream changes
  useEffect(() => {
    if (camState === "live" && streamRef.current && videoRef.current) {
      void attachVideo(streamRef.current);
    }
  }, [camState, streamVersion, attachVideo]);

  // Polling fallback: stream may be acquired before video element mounts (core Let's Begin bug)
  // This ensures attachment once video element exists, even if camState hasn't changed
  useEffect(() => {
    if (camState !== "live") return;
    const interval = setInterval(() => {
      if (videoRef.current && streamRef.current && videoRef.current.srcObject !== streamRef.current) {
        const hasVideo = streamRef.current.getVideoTracks().length > 0;
        if (hasVideo) void attachVideo(streamRef.current);
      }
    }, 150);
    return () => clearInterval(interval);
  }, [camState, attachVideo]);

  return {
    videoRef,
    setVideoRef,
    camState,
    micState,
    micLevel,
    cameraEnabled,
    micEnabled,
    stream,
    requestMedia,
    requestCamera,
    requestMicrophone,
    toggleCamera,
    toggleMic,
    stopAll,
    error,
  };
}
