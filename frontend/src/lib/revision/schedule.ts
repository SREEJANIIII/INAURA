/**
 * When a card should come back.
 *
 * A Leitner ladder: every card sits in a box, and getting it right moves it up one, so it
 * returns later and later. Getting it wrong drops it to the bottom, so it returns today.
 * This is the part that makes revision work — without it a deck is just a slideshow.
 *
 * Pure and clock-injected, so the behaviour can be tested rather than waited for.
 */

/** Days until a card in each box comes back. Box 0 is "still learning — later today". */
export const BOX_DAYS = [0, 1, 3, 7, 16, 35] as const;
export const TOP_BOX = BOX_DAYS.length - 1;

export const DAY_MS = 24 * 60 * 60 * 1000;

/**
 * How it went.
 *
 *   again  — you didn't have it. Back to the bottom, and back before this sitting ends.
 *   almost — you nearly had it. You keep your place on the ladder but don't climb.
 *   got    — you had it. Up a rung, and away for longer.
 */
export type Answer = "again" | "almost" | "got";

export type CardProgress = {
  /** How far up the ladder, 0 (new or just missed) to TOP_BOX */
  box: number;
  /** When it next counts as due, as a timestamp */
  dueAt: number;
  /** Times answered, ever */
  seen: number;
  /** Times answered right, ever */
  right: number;
  /** Last answered, as a timestamp */
  lastAt: number;
};

export const newProgress = (): CardProgress => ({ box: 0, dueAt: 0, seen: 0, right: 0, lastAt: 0 });

/** The local calendar day a moment falls in, as YYYY-MM-DD */
export function dayKey(at: number | Date): string {
  const d = at instanceof Date ? at : new Date(at);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** Midnight at the start of the day after this one, so "due tomorrow" means "from tomorrow" */
function startOfNextDays(now: number, days: number): number {
  const d = new Date(now);
  d.setHours(0, 0, 0, 0);
  return d.getTime() + days * DAY_MS;
}

/** Where an answer puts a card on the ladder */
export function boxAfter(box: number, answer: Answer): number {
  if (answer === "again") return 0;
  // Keeping your place is the point of "almost": no climb, but no fall either
  if (answer === "almost") return Math.max(1, box);
  return Math.min(TOP_BOX, box + 1);
}

/** Record an answer and work out when the card should return */
export function grade(progress: CardProgress, answer: Answer, now: number): CardProgress {
  const box = boxAfter(progress.box, answer);
  return {
    box,
    // A card you didn't have is due right now, so it comes round again this sitting
    dueAt: answer === "again" ? now : startOfNextDays(now, BOX_DAYS[box]),
    seen: progress.seen + 1,
    right: progress.right + (answer === "got" ? 1 : 0),
    lastAt: now,
  };
}

export const isDue = (progress: CardProgress | undefined, now: number): boolean =>
  !!progress && progress.dueAt <= now;

/** A card never answered is new rather than due — new ones are rationed, due ones are not */
export const isNew = (progress: CardProgress | undefined): boolean => !progress || progress.seen === 0;

/** Plain English for when a card will be back, for the summary at the end of a session */
export function whenBack(progress: CardProgress, now: number): string {
  const days = Math.round((progress.dueAt - now) / DAY_MS);
  if (days <= 0) return "later today";
  if (days === 1) return "tomorrow";
  if (days < 7) return `in ${days} days`;
  if (days < 14) return "in a week";
  if (days < 31) return `in ${Math.round(days / 7)} weeks`;
  return "in a month";
}

/**
 * How many days in a row up to today, given the days studied.
 * Yesterday still counts, so a streak isn't lost until a whole day is missed.
 */
export function streakFrom(days: Iterable<string>, now: number): number {
  const set = new Set(days);
  if (!set.size) return 0;
  const today = dayKey(now);
  const yesterday = dayKey(now - DAY_MS);
  if (!set.has(today) && !set.has(yesterday)) return 0;

  let count = 0;
  let cursor = set.has(today) ? now : now - DAY_MS;
  while (set.has(dayKey(cursor))) {
    count += 1;
    cursor -= DAY_MS;
  }
  return count;
}
