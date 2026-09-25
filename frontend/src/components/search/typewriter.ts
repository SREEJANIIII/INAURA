/**
 * Placeholder typewriter as a tiny state machine, kept free of React and timers so it's easy to test.
 *
 *   hold (phrase shown) → deleting (one char at a time) → pause ("Search for") → typing next phrase → hold …
 *
 * A phrase is the word plus its trailing dots, so the dots are erased and written along with it
 * rather than sitting there on their own while the word is gone.
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

/** The word with its trailing dots attached, so both are typed and erased as one */
export const phrasesFor = (words: readonly string[], suffix = "...") => words.map((w) => `${w}${suffix}`);

/** "Search for" + " skills.." — the prefix never changes, only the phrase is written and erased */
export function renderText(prefix: string, state: TypewriterState, phrases: readonly string[]): string {
  const visible = phrases[state.wordIndex]?.slice(0, state.chars) ?? "";
  return `${prefix}${visible ? ` ${visible}` : ""}`;
}
