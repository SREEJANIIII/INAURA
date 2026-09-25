/**
 * What the placeholder offers to search for.
 *
 * Every one of these is something INAURA actually holds and the search below can find, so the
 * bar advertises what it can do rather than naming three things at random.
 */
export const SEARCH_SUGGESTIONS = [
  "skills",
  "roles",
  "resources",
  "projects",
  "certificates",
  "skill gaps",
  "roadmap tasks",
  "mock interviews",
  "DSA problems",
  "flashcards",
  "assessments",
  "career tracks",
] as const;

/**
 * A different order every time the bar loads, so you don't see the same few words on every visit.
 * Takes its randomness as an argument so a test can pin it down.
 */
export function shuffled<T>(items: readonly T[], random: () => number = Math.random): T[] {
  const out = [...items];
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(random() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}
