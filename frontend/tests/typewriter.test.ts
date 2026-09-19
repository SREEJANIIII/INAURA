import { describe, it } from "node:test";
import assert from "node:assert";
import {
  advance,
  DEFAULT_TIMING,
  delayFor,
  initialState,
  renderText,
  type TypewriterState,
} from "../src/components/search/typewriter.ts";

const WORDS = ["skills", "roles", "resources"];
const text = (s: TypewriterState) => renderText("Search for", "...", s, WORDS);

/** Runs the machine and records every distinct placeholder text, in order */
function run(steps: number) {
  let s = initialState(WORDS);
  const seen = [text(s)];
  for (let i = 0; i < steps; i++) {
    s = advance(s, WORDS);
    if (text(s) !== seen[seen.length - 1]) seen.push(text(s));
  }
  return { seen, state: s };
}

describe("typewriter placeholder", () => {
  it("starts with the first word fully written", () => {
    assert.equal(text(initialState(WORDS)), "Search for skills...");
  });

  it("erases only the word, one character at a time, never the prefix", () => {
    const { seen } = run(9);
    assert.deepEqual(seen.slice(0, 8), [
      "Search for skills...",
      "Search for skill...",
      "Search for skil...",
      "Search for ski...",
      "Search for sk...",
      "Search for s...",
      "Search for...",
      "Search for r...",
    ]);
  });

  it("cycles skills → roles → resources → skills", () => {
    const { seen } = run(200);
    const fullWords = seen.filter((t) => ["Search for skills...", "Search for roles...", "Search for resources..."].includes(t));
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

  it("shows 'Search for...' during the pause between words", () => {
    let s = initialState(WORDS);
    while (s.phase !== "pause") s = advance(s, WORDS);
    assert.equal(text(s), "Search for...");
    assert.equal(advance(s, WORDS).wordIndex, 1);
  });
});
