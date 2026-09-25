import { useEffect, useState, type ReactNode } from "react";
import Button from "./app-button";

type Props = {
  onConfirm: () => void;
  /** What the button says before it's pressed */
  children?: ReactNode;
  /** What pressing it again will do, said plainly */
  confirmLabel?: string;
  busy?: boolean;
  busyLabel?: string;
  disabled?: boolean;
  /** Read out with the confirm step, e.g. "Remove your GitHub profile" */
  label?: string;
  size?: "sm" | "md";
};

/**
 * A destructive action that asks once, in place.
 *
 * The first press turns the button into "Yes, remove" and "Cancel"; if nothing is pressed the
 * question goes away by itself. Lighter than a dialog for something as small as removing one
 * item, but it still takes two deliberate presses to lose anything.
 */
export default function ConfirmButton({
  onConfirm,
  children = "Remove",
  confirmLabel = "Yes, remove",
  busy = false,
  busyLabel = "Removing…",
  disabled = false,
  label,
  size = "sm",
}: Props) {
  const [asking, setAsking] = useState(false);

  useEffect(() => {
    if (!asking) return;
    const timer = window.setTimeout(() => setAsking(false), 6000);
    return () => window.clearTimeout(timer);
  }, [asking]);

  if (asking && !busy) {
    return (
      <span className="confirm-inline" role="group" aria-label={label ? `${label}?` : "Are you sure?"}>
        <Button
          variant="secondary"
          size={size}
          className="ib--danger"
          autoFocus
          onClick={() => {
            setAsking(false);
            onConfirm();
          }}
        >
          {confirmLabel}
        </Button>
        <Button variant="ghost" size={size} onClick={() => setAsking(false)}>
          Cancel
        </Button>
      </span>
    );
  }

  return (
    <Button variant="ghost" size={size} onClick={() => setAsking(true)} disabled={disabled || busy} aria-label={label}>
      {busy ? busyLabel : children}
    </Button>
  );
}
