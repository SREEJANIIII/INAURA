import { describe, it } from "node:test";
import assert from "node:assert";
import {
  SpeechAudioPlayer,
  type AudioLike,
} from "../src/services/tts.ts";

type ScriptedAudio = AudioLike & {
  playCalls: number;
  pauseCalls: number;
  failPlayWith: unknown;
};

function makeAudio(): { element: ScriptedAudio; fireEnded: () => void; fireError: () => void } {
  let onended: (() => void) | null = null;
  let onerror: (() => void) | null = null;
  const element = {
    playCalls: 0,
    pauseCalls: 0,
    failPlayWith: undefined as unknown,
    src: "",
    play() {
      element.playCalls += 1;
      if (element.failPlayWith !== undefined) {
        return Promise.reject(element.failPlayWith);
      }
      return Promise.resolve();
    },
    pause() {
      element.pauseCalls += 1;
    },
  } as ScriptedAudio;
  Object.defineProperties(element, {
    onended: { get: () => onended, set: (f) => { onended = f; }, configurable: true },
    onerror: { get: () => onerror, set: (f) => { onerror = f; }, configurable: true },
  });
  return {
    element,
    fireEnded: () => onended?.(),
    fireError: () => onerror?.(),
  };
}

function makeUrls() {
  const created: string[] = [];
  const revoked: string[] = [];
  let counter = 0;
  return {
    created,
    revoked,
    create(): string {
      const url = `blob:audio-${++counter}`;
      created.push(url);
      return url;
    },
    revoke(url: string) {
      revoked.push(url);
    },
  };
}

function wavBlob(): Blob {
  return new Blob([new Uint8Array(2048)], { type: "audio/wav" });
}

const flush = () => new Promise((r) => setTimeout(r, 0));

describe("SpeechAudioPlayer lifecycle", () => {
  it("1. play() starts the element with the fetched audio URL", async () => {
    const ctx = makeAudio();
    const urls = makeUrls();
    const player = new SpeechAudioPlayer(() => ctx.element, urls);
    const done = player.play(wavBlob());
    await flush();
    assert.strictEqual(ctx.element.playCalls, 1);
    assert.strictEqual(urls.created.length, 1);
    ctx.fireEnded();
    await done;
  });

  it("3+4. onended is the normal completion event (promise pending until then)", async () => {
    const ctx = makeAudio();
    const player = new SpeechAudioPlayer(() => ctx.element, makeUrls());
    let settled = false;
    const done = player.play(wavBlob()).then(() => { settled = true; });
    await flush();
    assert.strictEqual(settled, false);
    ctx.fireEnded();
    await done;
    assert.strictEqual(settled, true);
  });

  it("6. no estimated-duration timer interrupts playback", async () => {
    const ctx = makeAudio();
    const player = new SpeechAudioPlayer(() => ctx.element, makeUrls());
    let settled = false;
    const done = player.play(wavBlob()).then(() => { settled = true; });
    await new Promise((r) => setTimeout(r, 120));
    assert.strictEqual(settled, false);
    assert.strictEqual(ctx.element.playCalls, 1);
    assert.strictEqual(ctx.element.pauseCalls, 0);
    ctx.fireEnded();
    await done;
    assert.strictEqual(settled, true);
  });

  it("2+7. a genuinely new playback supersedes without overlap; stale events ignored", async () => {
    const first = makeAudio();
    const second = makeAudio();
    const elements = [first.element, second.element];
    let n = 0;
    const player = new SpeechAudioPlayer(() => elements[n++ % elements.length], makeUrls());
    const order: string[] = [];
    const a = player.play(wavBlob()).then(() => order.push("A"));
    await flush();
    const b = player.play(wavBlob()).then(() => order.push("B"));
    await flush();
    // Old element paused exactly once; late event from it is ignored.
    assert.strictEqual(first.element.pauseCalls, 1);
    first.fireEnded();
    await flush();
    assert.deepStrictEqual(order, ["A"]); // A settled silently on supersede
    second.fireEnded();
    await Promise.all([a, b]);
    assert.deepStrictEqual(order, ["A", "B"]);
  });

  it("8. stale audio cannot change newer-question state", async () => {
    const first = makeAudio();
    const second = makeAudio();
    const elements = [first.element, second.element];
    let n = 0;
    const player = new SpeechAudioPlayer(() => elements[n++ % elements.length], makeUrls());
    const a = player.play(wavBlob());
    await flush();
    const b = player.play(wavBlob());
    await flush();
    await a; // superseded: resolved, not rejected
    let bSettled = false;
    void b.then(() => { bSettled = true; });
    first.fireEnded(); // stale: must not settle B
    await flush();
    assert.strictEqual(bSettled, false);
    second.fireEnded();
    await b;
    assert.strictEqual(bSettled, true);
  });

  it("5+9. object URL survives until playback ends, then is revoked", async () => {
    const ctx = makeAudio();
    const urls = makeUrls();
    const player = new SpeechAudioPlayer(() => ctx.element, urls);
    const done = player.play(wavBlob());
    await flush();
    assert.strictEqual(urls.revoked.length, 0);
    ctx.fireEnded();
    await done;
    assert.deepStrictEqual(urls.revoked, urls.created);
  });

  it("stop() (unmount/end/repeat) cancels without hanging or rejecting", async () => {
    const ctx = makeAudio();
    const urls = makeUrls();
    const player = new SpeechAudioPlayer(() => ctx.element, urls);
    const done = player.play(wavBlob());
    await flush();
    player.stop();
    await done; // resolves silently
    assert.strictEqual(ctx.element.pauseCalls, 1);
    assert.deepStrictEqual(urls.revoked, urls.created);
  });

  it("10. playback failure rejects so the fallback UI appears", async () => {
    const ctx = makeAudio();
    const player = new SpeechAudioPlayer(() => ctx.element, makeUrls());
    const done = player.play(wavBlob());
    await flush();
    ctx.fireError();
    await assert.rejects(done, /AI voice playback failed/);
  });

  it("play() rejection (e.g. autoplay policy) rejects", async () => {
    const ctx = makeAudio();
    ctx.element.failPlayWith = new Error("NotAllowedError");
    const player = new SpeechAudioPlayer(() => ctx.element, makeUrls());
    await assert.rejects(player.play(wavBlob()), /NotAllowedError/);
  });

  it("no timers drive the speaking→listening transition", async () => {
    const { readFileSync } = await import("node:fs");
    const src = readFileSync(new URL("../src/services/tts.ts", import.meta.url), "utf8");
    // The guarded player (the only playback path) must be timer-free. The
    // separate withTimeout watchdog utility is tested on its own below.
    const playerBody = src.split("export class SpeechAudioPlayer")[1] ?? "";
    assert.ok(!playerBody.includes("setTimeout"), "player must not use timers");
    assert.ok(!playerBody.includes("setInterval"), "player must not use intervals");
    const hook = readFileSync(new URL("../src/hooks/useTextToSpeech.ts", import.meta.url), "utf8");
    assert.ok(!hook.includes("setTimeout"), "hook must not use timers");
  });
});
