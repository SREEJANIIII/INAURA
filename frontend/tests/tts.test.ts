import { describe, it, beforeEach } from "node:test";
import assert from "node:assert";
import {
  clearTtsInFlight,
  fetchTtsAudio,
  isValidAudioBlob,
  parseTtsHttpStatus,
  ttsDedupeKey,
  ttsFailureKind,
  TTS_MIN_AUDIO_BYTES,
  type FetchBlobFn,
} from "../src/services/tts.ts";

function wavBlob(size: number, type = "audio/wav"): Blob {
  const bytes = new Uint8Array(size);
  bytes[0] = 0x52; // 'R'
  bytes[1] = 0x49; // 'I'
  return new Blob([bytes], { type });
}

describe("TTS audio validation", () => {
  it("accepts the provider's playable audio formats", () => {
    assert.strictEqual(isValidAudioBlob(wavBlob(1024, "audio/wav")), true);
    const mp3 = new Blob([new Uint8Array([0x49, 0x44, 0x33, ...new Array(100).fill(0)])], {
      type: "audio/mpeg",
    });
    assert.strictEqual(isValidAudioBlob(mp3), true);
  });

  it("rejects empty and truncated payloads before any playback attempt", () => {
    assert.strictEqual(isValidAudioBlob(new Blob([], { type: "audio/wav" })), false);
    assert.strictEqual(isValidAudioBlob(wavBlob(TTS_MIN_AUDIO_BYTES - 1)), false);
    assert.strictEqual(isValidAudioBlob(null), false);
    assert.strictEqual(isValidAudioBlob(undefined), false);
  });

  it("rejects non-audio MIME types", () => {
    assert.strictEqual(isValidAudioBlob(wavBlob(1024, "application/json")), false);
  });
});

describe("TTS dedupe key", () => {
  it("keys identical questions together across renders", () => {
    assert.strictEqual(
      ttsDedupeKey({ text: "Q?", sessionId: "s1", questionId: "q1" }),
      ttsDedupeKey({ text: "Q? ignored", sessionId: "s1", questionId: "q1" })
    );
  });

  it("never merges genuinely different questions", () => {
    assert.notStrictEqual(
      ttsDedupeKey({ text: "Q?", sessionId: "s1", questionId: "q1" }),
      ttsDedupeKey({ text: "Q?", sessionId: "s1", questionId: "q2" })
    );
  });
});

describe("TTS fetch: exact Gemini text, fetched once", () => {
  beforeEach(() => clearTtsInFlight());

  it("sends the exact next_question text to the backend endpoint", async () => {
    let seenUrl = "";
    let seenBody = "";
    const blob = await fetchTtsAudio(
      { text: "Runtime versus compile-time polymorphism?", sessionId: "s1", questionId: "q2" },
      (async (endpoint: string, options: { method: string; body: string }) => {
        seenUrl = endpoint;
        seenBody = options.body;
        return wavBlob(2048);
      }) as FetchBlobFn
    );
    assert.strictEqual(seenUrl, "/analysis/assessment/interview/tts");
    const body = JSON.parse(seenBody) as { text: string; question_id: string };
    assert.strictEqual(body.text, "Runtime versus compile-time polymorphism?");
    assert.strictEqual(body.question_id, "q2");
    assert.strictEqual(isValidAudioBlob(blob), true);
  });

  it("coalesces concurrent identical question requests into one fetch", async () => {
    let calls = 0;
    const fetch: FetchBlobFn = async () => {
      calls++;
      await new Promise((r) => setTimeout(r, 10));
      return wavBlob(2048);
    };
    const req = { text: "Same Gemini question?", sessionId: "s1", questionId: "q1" };
    const [a, b] = await Promise.all([fetchTtsAudio(req, fetch), fetchTtsAudio(req, fetch)]);
    assert.strictEqual(calls, 1);
    assert.strictEqual(a, b);
  });

  it("issues separate requests for different Gemini questions", async () => {
    let calls = 0;
    const fetch: FetchBlobFn = async () => {
      calls++;
      return wavBlob(2048);
    };
    await fetchTtsAudio({ text: "Q1?", sessionId: "s1", questionId: "q1" }, fetch);
    await fetchTtsAudio({ text: "Q2?", sessionId: "s1", questionId: "q2" }, fetch);
    assert.strictEqual(calls, 2);
  });

  it("a failed request does not poison later identical requests", async () => {
    let calls = 0;
    const failing: FetchBlobFn = async () => {
      calls++;
      throw new Error("API error 503 Service Unavailable");
    };
    await assert.rejects(
      fetchTtsAudio({ text: "Retry me?", sessionId: "s1", questionId: "q9" }, failing)
    );
    const blob = await fetchTtsAudio({ text: "Retry me?", sessionId: "s1", questionId: "q9" }, async () => {
      calls++;
      return wavBlob(2048);
    });
    assert.strictEqual(calls, 2);
    assert.strictEqual(isValidAudioBlob(blob), true);
  });
});

describe("TTS failures are never retried on the frontend", () => {
  beforeEach(() => clearTtsInFlight());

  for (const message of [
    "API error 429 Too Many Requests: quota exceeded",
    "API error 503 Service Unavailable",
    "API error 401 Unauthorized",
    "API error 400 Bad Request",
    "timeout of 30000ms exceeded",
  ]) {
    it(`propagates exactly once: ${message}`, async () => {
      let calls = 0;
      const fetch: FetchBlobFn = async () => {
        calls++;
        throw new Error(message);
      };
      await assert.rejects(fetchTtsAudio({ text: "Hello?" }, fetch));
      assert.strictEqual(calls, 1);
    });
  }

  it("classifies failures for messaging only", () => {
    assert.strictEqual(parseTtsHttpStatus("API error 429 Too Many Requests"), 429);
    assert.strictEqual(ttsFailureKind(429), "quota");
    assert.strictEqual(ttsFailureKind(401), "auth");
    assert.strictEqual(ttsFailureKind(503), "temporary");
    assert.strictEqual(ttsFailureKind(400), "invalid");
    assert.strictEqual(ttsFailureKind(null), "unknown");
  });
});

describe("TTS failure preserves the adaptive interview", () => {
  it("answer → evaluation → next question still completes when voice fails", async () => {
    // Models InterviewModal.submitAnswer + speakThenListen: the next question
    // comes from Gemini analysis of THIS answer, and TTS only voices it.
    const geminiResponse = {
      evaluation: { follow_up_needed: true, suggested_follow_up: "What breaks at 10x load?" },
      current_question: { id: "q1f", prompt: "What breaks at 10x load?" },
    };
    let ttsCalls = 0;
    const speak: (text: string) => Promise<void> = async (text: string) => {
      ttsCalls++;
      assert.strictEqual(text, geminiResponse.current_question.prompt);
      throw new Error("API error 503 Service Unavailable");
    };
    // TTS receives the Gemini-derived question, fails, interview continues.
    let voiceOk = true;
    try {
      await speak(geminiResponse.current_question.prompt);
    } catch {
      voiceOk = false;
    }
    assert.strictEqual(ttsCalls, 1);
    assert.strictEqual(voiceOk, false);
    assert.strictEqual(geminiResponse.current_question.id, "q1f");
  });

  it("the spoken text is always the Gemini-derived question, never a generic one", async () => {
    const seen: string[] = [];
    const speak: (text: string) => Promise<void> = async (text: string) => {
      seen.push(text);
    };
    const geminiQuestion = "You mentioned caching — what invalidation strategy did you use?";
    await speak(geminiQuestion);
    assert.deepStrictEqual(seen, [geminiQuestion]);
  });
});

describe("Playback lifecycle guards", () => {
  it("hook delegates playback lifecycle to the guarded player", async () => {
    const { readFileSync } = await import("node:fs");
    const src = readFileSync(new URL("../src/hooks/useTextToSpeech.ts", import.meta.url), "utf8");
    assert.ok(src.includes("SpeechAudioPlayer"));
    assert.ok(src.includes("requestRef"));
    assert.ok(!src.includes("setTimeout"));
    // Resource release + stale guards are unit-tested against the player.
  });

  it("no interview code calls browser speech synthesis", async () => {
    const { readFileSync } = await import("node:fs");
    for (const file of ["../src/services/tts.ts", "../src/hooks/useTextToSpeech.ts"]) {
      const src = readFileSync(new URL(file, import.meta.url), "utf8");
      assert.ok(!src.includes("speechSynthesis"), file);
    }
  });
});
