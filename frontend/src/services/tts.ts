/**
 * Interview TTS boundary (NVIDIA voice via our FastAPI backend).
 *
 * The browser NEVER talks to NVIDIA: it POSTs the exact Gemini-generated
 * question text to `/analysis/assessment/interview/tts` and plays the
 * returned audio bytes. No API keys, voices, or provider details leak here.
 *
 * Interview *evaluation* lives in `services/assessment.ts` and never touches
 * this module. Voice failures must never block answering or grading.
 *
 * Retry policy: the frontend never retries TTS. The backend performs at most
 * one controlled retry for transient failures; rate-limit/auth failures
 * fail fast.
 */

export const TTS_ENDPOINT = "/analysis/assessment/interview/tts";

/** Minimum plausible payload: a 44-byte WAV header. Anything smaller is not audio. */
export const TTS_MIN_AUDIO_BYTES = 44;

export type TtsRequestKey = {
  text: string;
  sessionId?: string;
  questionId?: string;
};

export function ttsDedupeKey(req: TtsRequestKey): string {
  const stable = req.questionId?.trim() || req.text;
  return `${req.sessionId?.trim() || ""}|${stable}`;
}

export function isValidAudioBlob(blob: Blob | null | undefined): boolean {
  if (!blob || typeof blob.size !== "number" || blob.size < TTS_MIN_AUDIO_BYTES) {
    return false;
  }
  const type = (blob.type || "").toLowerCase();
  // Some intermediaries strip the MIME type; the size check already passed.
  if (!type) return true;
  return type.includes("audio") || type.includes("wav") || type.includes("octet-stream");
}

/** Extract the HTTP status from an `apiFetch*` error message, if present. */
export function parseTtsHttpStatus(message: unknown): number | null {
  const text = typeof message === "string" ? message : String(message ?? "");
  const match = /API error (\d{3})\b/.exec(text);
  return match ? Number(match[1]) : null;
}

export type TtsFailureKind = "quota" | "auth" | "temporary" | "invalid" | "unknown";

/** Classify for messaging only — the frontend never retries on any kind. */
export function ttsFailureKind(status: number | null): TtsFailureKind {
  if (status === 429) return "quota";
  if (status === 401 || status === 403) return "auth";
  if (status === 400 || status === 422) return "invalid";
  if (status === 502 || status === 503 || status === 504 || status === 408) {
    return "temporary";
  }
  return "unknown";
}

export type FetchBlobFn = (
  endpoint: string,
  options: { method: string; body: string }
) => Promise<Blob>;

// Lazily bound so unit tests can inject a fake without pulling the
// Supabase-backed API client at import time.
async function defaultFetchBlob(endpoint: string, options: { method: string; body: string }): Promise<Blob> {
  const { apiFetchBlob } = await import("./api.ts");
  return apiFetchBlob(endpoint, options);
}

/**
 * One logical AI message => at most one network request while in flight.
 * Keyed by session + question (falls back to exact text) so React re-renders
 * never duplicate speech, while genuinely different questions always fetch.
 */
const inFlight = new Map<string, Promise<Blob>>();

export function fetchTtsAudio(
  req: TtsRequestKey,
  fetchBlob: FetchBlobFn = defaultFetchBlob
): Promise<Blob> {
  const text = (req.text || "").trim();
  if (!text) return Promise.reject(new Error("Cannot synthesize empty text."));
  const key = ttsDedupeKey({ text, sessionId: req.sessionId, questionId: req.questionId });
  const existing = inFlight.get(key);
  if (existing) return existing;
  const task = (async () => {
    const blob = await fetchBlob(TTS_ENDPOINT, {
      method: "POST",
      body: JSON.stringify({
        text,
        session_id: req.sessionId?.trim() || undefined,
        question_id: req.questionId?.trim() || undefined,
      }),
    });
    if (!isValidAudioBlob(blob)) {
      throw new Error("AI voice playback failed: invalid audio response.");
    }
    return blob;
  })();
  inFlight.set(key, task);
  const cleanup = () => {
    if (inFlight.get(key) === task) inFlight.delete(key);
  };
  task.then(cleanup, cleanup);
  return task;
}

export function clearTtsInFlight(): void {
  inFlight.clear();
}

/**
 * Race a promise against a timeout. Rejects with Error("Timed out") and
 * always clears the timer. Used so no interview phase can wedge forever
 * waiting on릿 network/audio/provider work.
 */
export function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<T>((_, reject) => {
    timer = setTimeout(() => reject(new Error("Timed out")), ms);
  });
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}

// ---------------------------------------------------------------------------
// Playback lifecycle (PARTs 15-17): exactly ONE completion signal —
// audio.onended. No timers, no guessed durations, no render-driven stops.
// ---------------------------------------------------------------------------

export type AudioLike = {
  play(): Promise<void> | void;
  pause(): void;
  src: string;
  onended: (() => void) | null;
  onerror: (() => void) | null;
};

export type AudioFactory = (url: string) => AudioLike;

export type ObjectUrlFactory = {
  create(blob: Blob): string;
  revoke(url: string): void;
};

const defaultUrls: ObjectUrlFactory = {
  create: (blob) => URL.createObjectURL(blob),
  revoke: (url) => URL.revokeObjectURL(url),
};

/**
 * Stable playback controller. One generation per play() call: only the
 * current generation's events can settle its promise or touch shared refs.
 * stop() resolves (never rejects, never hangs) the active playback and
 * tears it down. Object URLs are revoked only after their playback ends
 * or is superseded — never mid-playback.
 */
export class SpeechAudioPlayer {
  private generation = 0;
  private audio: AudioLike | null = null;
  private url: string | null = null;
  private activeResolve: (() => void) | null = null;
  private readonly createAudio: AudioFactory;
  private readonly urls: ObjectUrlFactory;

  constructor(createAudio: AudioFactory, urls: ObjectUrlFactory = defaultUrls) {
    this.createAudio = createAudio;
    this.urls = urls;
  }

  play(blob: Blob): Promise<void> {
    // A genuinely new playback supersedes any current one.
    this.stop();
    const gen = ++this.generation;
    return new Promise<void>((resolve, reject) => {
      this.activeResolve = resolve;
      let audio: AudioLike;
      try {
        const url = this.urls.create(blob);
        this.url = url;
        audio = this.createAudio(url);
      } catch {
        this.settle(gen, null);
        reject(new Error("AI voice playback failed."));
        return;
      }
      this.audio = audio;
      audio.onended = () => {
        if (this.settle(gen, audio)) resolve();
      };
      audio.onerror = () => {
        if (this.settle(gen, audio)) reject(new Error("AI voice playback failed."));
      };
      try {
        const started = audio.play();
        if (started && typeof (started as Promise<void>).catch === "function") {
          (started as Promise<void>).catch((error: unknown) => {
            if (this.settle(gen, audio)) {
              reject(error instanceof Error ? error : new Error("AI voice playback failed."));
            }
          });
        }
      } catch (error: unknown) {
        if (this.settle(gen, audio)) {
          reject(error instanceof Error ? error : new Error("AI voice playback failed."));
        }
      }
    });
  }

  stop(): void {
    this.generation += 1;
    const resolve = this.activeResolve;
    this.activeResolve = null;
    this.teardown();
    // Settle superseded playback silently so awaiting callers continue into
    // their lifecycle guards instead of hanging forever.
    if (resolve) {
      try {
        resolve();
      } catch {
        /* ignore */
      }
    }
  }

  /** Detach + pause + revoke. Only the owning generation may settle. */
  private settle(gen: number, audio: AudioLike | null): boolean {
    if (gen !== this.generation) return false;
    if (audio !== null && this.audio !== null && this.audio !== audio) return false;
    this.activeResolve = null;
    this.teardown();
    return true;
  }

  private teardown(): void {
    const audio = this.audio;
    this.audio = null;
    if (audio) {
      audio.onended = null;
      audio.onerror = null;
      try {
        audio.pause();
      } catch {
        /* ignore */
      }
    }
    if (this.url !== null) {
      try {
        this.urls.revoke(this.url);
      } catch {
        /* ignore */
      }
      this.url = null;
    }
  }
}
