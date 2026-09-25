/**
 * The remembering behind pageData: one copy of each page's data, shared by every page that
 * shows it, reused while it's still current, and forgotten on logout.
 *
 * Kept apart from pageData so it can be tested on its own, without the services it loads from.
 */

const store = new Map<string, unknown>();
const loadedAt = new Map<string, number>();
const inflight = new Map<string, Promise<unknown>>();
const listeners = new Set<() => void>();
const notify = () => listeners.forEach((l) => l());

/** Lets components (e.g. the top bar name) update when remembered data changes. */
export function subscribeRemembered(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** How long a remembered copy counts as current before it's worth asking the server again. */
export const FRESH_MS = 60_000;

export type Remembered<T> = {
  /** The copy we already have, if any — never asks the server. */
  peek: () => T | undefined;
  /** The copy we already have if it's current, otherwise a fresh one from the server. */
  fetch: (force?: boolean) => Promise<T>;
};

/**
 * Remembers what `load` returns under `key`.
 *
 * Callers asking at the same time share one request, and a caller asking again while the
 * copy is still fresh gets it back without the server being troubled — otherwise every
 * visit to a page re-asks for data it already has.
 *
 * Pass force=true after saving something, so neither the remembered copy nor an older
 * in-progress request is reused.
 */
export function remember<T>(key: string, load: () => Promise<T>, freshMs = FRESH_MS): Remembered<T> {
  const peek = () => store.get(key) as T | undefined;
  const fetch = (force = false): Promise<T> => {
    if (!force) {
      const running = inflight.get(key) as Promise<T> | undefined;
      if (running) return running;
      const at = loadedAt.get(key);
      if (at !== undefined && Date.now() - at < freshMs && store.has(key)) {
        return Promise.resolve(store.get(key) as T);
      }
    }
    const request: Promise<T> = load()
      .then((data) => {
        // Ignore an older request finishing after a newer one started (or after logout)
        if (inflight.get(key) === request) {
          store.set(key, data);
          loadedAt.set(key, Date.now());
          notify();
        }
        return data;
      })
      .finally(() => {
        if (inflight.get(key) === request) inflight.delete(key);
      });
    inflight.set(key, request);
    return request;
  };
  return { peek, fetch };
}

/** One remembered copy per key, e.g. per role — same sharing and logout clearing as above */
export function rememberByKey<T>(prefix: string, load: (key: string) => Promise<T>, freshMs = FRESH_MS) {
  const made = new Map<string, Remembered<T>>();
  const entryFor = (key: string) => {
    let entry = made.get(key);
    if (!entry) {
      entry = remember(`${prefix}:${key}`, () => load(key), freshMs);
      made.set(key, entry);
    }
    return entry;
  };
  // Re-fetch every key asked for so far, for when the data behind all of them changes
  const refreshAll = () => {
    for (const entry of made.values()) entry.fetch(true).catch(() => undefined);
  };
  return Object.assign(entryFor, { refreshAll });
}

/** Forget everything — call on logout so the next user never sees old data. */
export function forgetAll() {
  store.clear();
  loadedAt.clear();
  inflight.clear();
  notify();
}
