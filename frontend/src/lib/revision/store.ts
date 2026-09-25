/**
 * Where revision progress is kept.
 *
 * In this browser, for now. That is a real limit and worth saying plainly: study this on your
 * laptop and your phone won't know about it, and clearing site data forgets it. Everything
 * goes through this one file so moving it to your account later is a change in one place,
 * not a change everywhere.
 *
 * Every read and write is guarded: storage throws in a private window and returns nothing
 * with site data blocked, and neither should cost you a revision session.
 */
import { dayKey, type CardProgress } from "./schedule";

const PROGRESS_KEY = "inaura-revision-progress";
const DAYS_KEY = "inaura-revision-days";
/** A streak longer than this is history, not motivation */
const KEEP_DAYS = 400;

export type ProgressMap = Record<string, CardProgress>;

function read<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function write(key: string, value: unknown): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Out of room, or storage is blocked — the session still works, it just won't be remembered
  }
}

export const loadProgress = (): ProgressMap => read<ProgressMap>(PROGRESS_KEY, {});

export const saveProgress = (progress: ProgressMap): void => write(PROGRESS_KEY, progress);

export const loadStudyDays = (): string[] => read<string[]>(DAYS_KEY, []);

/** Mark today as studied, for the streak. Returns the full list. */
export function recordStudyDay(now: number): string[] {
  const today = dayKey(now);
  const days = loadStudyDays();
  if (days.includes(today)) return days;
  const next = [...days, today].sort().slice(-KEEP_DAYS);
  write(DAYS_KEY, next);
  return next;
}

/** Forget everything, for the "start over" action */
export function clearRevision(): void {
  try {
    window.localStorage.removeItem(PROGRESS_KEY);
    window.localStorage.removeItem(DAYS_KEY);
  } catch {
    // Nothing to clear if it was never stored
  }
}
