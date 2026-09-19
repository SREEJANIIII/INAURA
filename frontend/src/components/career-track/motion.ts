import { useEffect, useRef, useState, type MouseEvent } from "react";
import { flushSync } from "react-dom";
import { useNavigate, type NavigateFunction } from "react-router-dom";

const reducedMotion = () =>
  typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/** True once the element has scrolled into view (never flips back), so entry animations play once */
export function useInViewOnce<T extends Element>(rootMargin = "0px 0px -8% 0px") {
  const ref = useRef<T>(null);
  const [inView, setInView] = useState(() => typeof IntersectionObserver === "undefined");

  useEffect(() => {
    const el = ref.current;
    if (!el || inView) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setInView(true);
          observer.disconnect();
        }
      },
      { rootMargin }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [inView, rootMargin]);

  return [ref, inView] as const;
}

/** Counts from 0 to `target` with an ease-out curve once `active` is true */
export function useCountUp(target: number, active: boolean, duration = 900) {
  const [value, setValue] = useState(0);

  useEffect(() => {
    if (!active) return;
    if (reducedMotion()) {
      const id = requestAnimationFrame(() => setValue(target));
      return () => cancelAnimationFrame(id);
    }
    let frame = 0;
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      setValue(Math.round(target * eased));
      if (t < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [target, active, duration]);

  return value;
}

type ViewTransitionDocument = Document & { startViewTransition?: (update: () => void) => unknown };

/**
 * Navigate inside a browser view transition (a cross-fade, plus shared elements with a
 * view-transition-name). INAURA uses BrowserRouter, where React Router's own viewTransition
 * option has no effect, so this calls the browser API directly and falls back to a plain navigation.
 */
export function navigateWithTransition(navigate: NavigateFunction, to: string, options?: { replace?: boolean }) {
  const doc = document as ViewTransitionDocument;
  if (!doc.startViewTransition || reducedMotion()) {
    navigate(to, options);
    return;
  }
  doc.startViewTransition(() => {
    flushSync(() => navigate(to, options));
  });
}

/** Press, then move to the skill page with a shared-element transition where the browser supports it */
export function useSkillNavigation() {
  const navigate = useNavigate();
  return (e: MouseEvent<HTMLAnchorElement>, to: string, markEl: HTMLElement | null, onPress?: () => void) => {
    // Let people open in a new tab or window as usual
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    onPress?.();
    if (markEl) markEl.style.viewTransitionName = "ct-skill-mark";
    window.setTimeout(() => navigateWithTransition(navigate, to), 130);
  };
}
