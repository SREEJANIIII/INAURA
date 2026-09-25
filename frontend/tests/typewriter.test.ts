import { describe, it } from "node:test";
import assert from "node:assert";
import {
  advance,
  DEFAULT_TIMING,
  delayFor,
  initialState,
  phrasesFor,
  renderText,
  type TypewriterState,
} from "../src/components/search/typewriter.ts";

const WORDS = ["skills", "roles", "resources"];
const PHRASES = phrasesFor(WORDS);
const text = (s: TypewriterState) => renderText("Search for", s, PHRASES);

/** Runs the machine and records every distinct placeholder text, in order */
function run(steps: number) {
  let s = initialState(PHRASES);
  const seen = [text(s)];
  for (let i = 0; i < steps; i++) {
    s = advance(s, PHRASES);
    if (text(s) !== seen[seen.length - 1]) seen.push(text(s));
  }
  return { seen, state: s };
}

describe("typewriter placeholder", () => {
  it("starts with the first word fully written, dots and all", () => {
    assert.equal(text(initialState(PHRASES)), "Search for skills...");
  });

  it("erases the dots along with the word, one character at a time", () => {
    const { seen } = run(12);
    assert.deepEqual(seen.slice(0, 10), [
      "Search for skills...",
      "Search for skills..",
      "Search for skills.",
      "Search for skills",
      "Search for skill",
      "Search for skil",
      "Search for ski",
      "Search for sk",
      "Search for s",
      "Search for",
    ]);
  });

  it("writes the word back before the dots return", () => {
    let s = initialState(PHRASES);
    while (s.phase !== "pause") s = advance(s, PHRASES);
    // Seeded with the paused text, so only what changes after it is recorded
    const seen: string[] = [text(s)];
    for (let i = 0; i < 12; i++) {
      s = advance(s, PHRASES);
      if (seen[seen.length - 1] !== text(s)) seen.push(text(s));
    }
    assert.deepEqual(seen.slice(1, 9), [
      "Search for r",
      "Search for ro",
      "Search for rol",
      "Search for role",
      "Search for roles",
      "Search for roles.",
      "Search for roles..",
      "Search for roles...",
    ]);
  });

  it("never leaves the dots on their own once the word is gone", () => {
    let s = initialState(PHRASES);
    for (let i = 0; i < 400; i++) {
      s = advance(s, PHRASES);
      const t = text(s);
      const tail = t.slice("Search for".length).trim();
      // Dots only ever sit directly after some of the word
      assert.ok(!/^\.+$/.test(tail), `dots shown with no word: "${t}"`);
    }
  });

  it("shows only the prefix during the pause between words", () => {
    let s = initialState(PHRASES);
    while (s.phase !== "pause") s = advance(s, PHRASES);
    assert.equal(text(s), "Search for");
    assert.equal(advance(s, PHRASES).wordIndex, 1);
  });

  it("cycles skills → roles → resources → skills", () => {
    const { seen } = run(400);
    const full = ["Search for skills...", "Search for roles...", "Search for resources..."];
    const fullWords = seen.filter((t) => full.includes(t));
    assert.deepEqual(fullWords.slice(0, 4), [
      "Search for skills...",
      "Search for roles...",
      "Search for resources...",
      "Search for skills...",
    ]);
    assert.ok(seen.every((t) => t.startsWith("Search for")));
  });

  it("holds finished words for seconds, types slower than it deletes, and pauses between", () => {
    const hold = delayFor({ wordIndex: 0, chars: 6, phase: "hold" });
    const typing = delayFor({ wordIndex: 1, chars: 2, phase: "typing" });
    const deleting = delayFor({ wordIndex: 0, chars: 3, phase: "deleting" });
    const pause = delayFor({ wordIndex: 0, chars: 0, phase: "pause" });
    assert.ok(hold >= 2000 && hold <= 3000);
    assert.ok(typing >= 70 && typing <= 100);
    assert.ok(deleting >= 40 && deleting <= 70 && deleting < typing);
    assert.ok(pause > DEFAULT_TIMING.typeMs);
  });

  it("attaches the dots to every word", () => {
    assert.deepEqual(phrasesFor(["skills", "roles"]), ["skills...", "roles..."]);
    assert.deepEqual(phrasesFor(["skills"], "…"), ["skills…"]);
  });
});
