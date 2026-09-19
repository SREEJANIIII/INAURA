/**
 * Shares "which section of a long page is on screen" between that page and the sidebar,
 * without putting it in the URL (which would re-trigger scrolling).
 */
let current: string | null = null;
const listeners = new Set<() => void>();

export function setActiveSection(id: string | null) {
  if (id === current) return;
  current = id;
  listeners.forEach((l) => l());
}

export const getActiveSection = () => current;

export function subscribeActiveSection(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Section ids on the analysis page that the sidebar links to */
export const ANALYSIS_SECTION_IDS = ["priority-gaps", "evidence-gaps", "skill-quadrants", "skill-overview", "evidence-sources"];
