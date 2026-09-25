/**
 * Where revision progress is kept.
 *
 * In this browser, for now. That is a real limit and worth saying plainly: study this on your
 * laptop and your phone won't know about it, and clearing site data forgets it. Everything
 * goes through this one file so moving it to your account later is a change in one place,
 * not a change everywhere.
 *
 * Kept per account: a college lab computer is shared, and one student's streak and cards must
 * never show up for the next person who logs in there. Progress saved before it was per account
 * (under the bare keys) is handed once to the first account that opens Revision, then removed.
 *
 * Every read and write is guarded: storage throws in a private window and returns nothing
 * with site data blocked, and neither should cost you a revision session.
 */
import { dayKey, isDue, type CardProgress } from "./schedule";

const PROGRESS_KEY = "inaura-revision-progress";
const DAYS_KEY = "inaura-revision-days";
/** A streak longer than this is history, not motivation */
const KEEP_DAYS = 400;

export type ProgressMap = Record<string, CardProgress>;

const keyFor = (base: string, owner: string) => `${base}:${owner}`;

function read<T>(base: string, owner: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(keyFor(base, owner));
    if (raw) return JSON.parse(raw) as T;
    // Saved before progress was per account: adopt it once, then stop sharing it
    const legacy = window.localStorage.getItem(base);
    if (legacy) {
      window.localStorage.setItem(keyFor(base, owner), legacy);
      window.localStorage.removeItem(base);
      return JSON.parse(legacy) as T;
    }
    return fallback;
  } catch {
    return fallback;
  }
}

function write(base: string, owner: string, value: unknown): void {
  try {
    window.localStorage.setItem(keyFor(base, owner), JSON.stringify(value));
  } catch {
    // Out of room, or storage is blocked — the session still works, it just won't be remembered
  }
}

export const loadProgress = (owner: string): ProgressMap => read<ProgressMap>(PROGRESS_KEY, owner, {});

export const saveProgress = (owner: string, progress: ProgressMap): void => write(PROGRESS_KEY, owner, progress);

export const loadStudyDays = (owner: string): string[] => read<string[]>(DAYS_KEY, owner, []);

/** Mark today as studied, for the streak. Returns the full list. */
export function recordStudyDay(owner: string, now: number): string[] {
  const today = dayKey(now);
  const days = loadStudyDays(owner);
  if (days.includes(today)) return days;
  const next = [...days, today].sort().slice(-KEEP_DAYS);
  write(DAYS_KEY, owner, next);
  return next;
}

/** Cards seen before that have come round again — a cheap count for reminders elsewhere */
export function dueCount(owner: string, now: number): number {
  return Object.values(loadProgress(owner)).filter((p) => p.seen > 0 && isDue(p, now)).length;
}

/** Forget everything, for the "start over" action */
export function clearRevision(owner: string): void {
  try {
    window.localStorage.removeItem(keyFor(PROGRESS_KEY, owner));
    window.localStorage.removeItem(keyFor(DAYS_KEY, owner));
  } catch {
    // Nothing to clear if it was never stored
  }
}
