import { useEffect, useState } from "react";
import { advance, DEFAULT_TIMING, delayFor, initialState, type TypewriterState, type TypewriterTiming } from "./typewriter";

const prefersReducedMotion = () =>
  typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/**
 * Runs the placeholder typewriter while `active` is true, and freezes it (without resetting) otherwise.
 * People who ask for reduced motion get the first word, static.
 */
export function useTypewriter(words: readonly string[], active: boolean, timing: TypewriterTiming = DEFAULT_TIMING) {
  const [state, setState] = useState<TypewriterState>(() => initialState(words));
  const [reducedMotion] = useState(prefersReducedMotion);
  const running = active && !reducedMotion && words.length > 1;

  useEffect(() => {
    if (!running) return;
    // A few ms of variation per keystroke keeps the typing from feeling mechanical
    const jitter = state.phase === "typing" || state.phase === "deleting" ? Math.round((Math.random() - 0.5) * 24) : 0;
    const id = window.setTimeout(() => setState((s) => advance(s, words)), delayFor(state, timing) + jitter);
    return () => window.clearTimeout(id);
  }, [running, state, words, timing]);

  return { state, animating: running && (state.phase === "typing" || state.phase === "deleting") };
}
