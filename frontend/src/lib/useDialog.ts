import { useEffect, useRef } from "react";

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * What every pop-up panel owes a keyboard and screen-reader user, in one place.
 *
 * While `open`: focus moves into the panel (to an element marked `data-autofocus`, or the
 * panel itself), Tab cycles inside it, Escape calls `onClose`, and the page behind stops
 * scrolling. On close, focus goes back to whatever opened it. Put the returned ref on the
 * panel, and give the panel tabIndex={-1} so it can take focus itself.
 */
export function useDialog<T extends HTMLElement>(open: boolean, onClose: () => void) {
  const ref = useRef<T>(null);
  const closeRef = useRef(onClose);

  useEffect(() => {
    closeRef.current = onClose;
  });

  useEffect(() => {
    if (!open) return;
    const node = ref.current;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    (node?.querySelector<HTMLElement>("[data-autofocus]") ?? node)?.focus({ preventScroll: true });

    const { overflow } = document.body.style;
    document.body.style.overflow = "hidden";

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        closeRef.current();
        return;
      }
      if (e.key !== "Tab" || !node) return;
      const items = Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((el) => el.getClientRects().length > 0);
      if (!items.length) {
        e.preventDefault();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      const at = document.activeElement;
      if (e.shiftKey && (at === first || at === node || !node.contains(at))) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && (at === last || !node.contains(at))) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey);

    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
      if (opener?.isConnected) opener.focus({ preventScroll: true });
    };
  }, [open]);

  return ref;
}
