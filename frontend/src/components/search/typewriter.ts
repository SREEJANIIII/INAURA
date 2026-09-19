/**
 * Placeholder typewriter as a tiny state machine, kept free of React and timers so it's easy to test.
 *
 *   hold (word shown) → deleting (one char at a time) → pause ("Search for...") → typing next word → hold …
 */

export type TypewriterPhase = "hold" | "deleting" | "pause" | "typing";

export type TypewriterState = {
  wordIndex: number;
  /** How many characters of the current word are visible */
  chars: number;
  phase: TypewriterPhase;
};

export type TypewriterTiming = {
  holdMs: number;
  deleteMs: number;
  pauseMs: number;
  typeMs: number;
};

export const DEFAULT_TIMING: TypewriterTiming = {
  holdMs: 2600,
  deleteMs: 55,
  pauseMs: 420,
  typeMs: 85,
};

/** Starts with the first word fully written, as if it had just been typed */
export const initialState = (words: readonly string[]): TypewriterState => ({
  wordIndex: 0,
  chars: words[0]?.length ?? 0,
  phase: "hold",
});

/** How long to stay in this state before advancing */
export function delayFor(state: TypewriterState, timing: TypewriterTiming = DEFAULT_TIMING): number {
  switch (state.phase) {
    case "hold":
      return timing.holdMs;
    case "deleting":
      return timing.deleteMs;
    case "pause":
      return timing.pauseMs;
    case "typing":
      return timing.typeMs;
  }
}

export function advance(state: TypewriterState, words: readonly string[]): TypewriterState {
  if (words.length === 0) return state;
  switch (state.phase) {
    case "hold":
      return { ...state, phase: "deleting" };
    case "deleting": {
      const chars = Math.max(0, state.chars - 1);
      return { ...state, chars, phase: chars === 0 ? "pause" : "deleting" };
    }
    case "pause":
      return { wordIndex: (state.wordIndex + 1) % words.length, chars: 0, phase: "typing" };
    case "typing": {
      const target = words[state.wordIndex].length;
      const chars = Math.min(target, state.chars + 1);
      return { ...state, chars, phase: chars === target ? "hold" : "typing" };
    }
  }
}

/** "Search for" + " skil" + "..." — the prefix never changes, only the word is written and erased */
export function renderText(prefix: string, suffix: string, state: TypewriterState, words: readonly string[]): string {
  const visible = words[state.wordIndex]?.slice(0, state.chars) ?? "";
  return `${prefix}${visible ? ` ${visible}` : ""}${suffix}`;
}
