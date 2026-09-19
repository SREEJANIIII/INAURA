import type { ReactNode } from "react";
import { useCountUp, useInViewOnce } from "./motion";

type BarProps = {
  value: number;
  /** Optional marker for the required level */
  target?: number;
  tone?: "accent" | "done" | "muted";
  size?: "sm" | "md" | "lg";
  label?: string;
};

/** Fills from 0 to `value` when it scrolls into view */
export function ProgressBar({ value, target, tone = "accent", size = "md", label }: BarProps) {
  const [ref, inView] = useInViewOnce<HTMLSpanElement>();
  return (
    <span
      ref={ref}
      className={`ct-bar ct-bar--${size} ct-bar--${tone}`}
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={value}
      aria-label={label}
    >
      <span className="ct-bar__fill" style={{ width: inView ? `${value}%` : "0%" }} />
      {target !== undefined && target > 0 && (
        <span className="ct-bar__target" style={{ left: `${target}%` }} aria-hidden="true" />
      )}
    </span>
  );
}

type RingProps = {
  value: number;
  target?: number;
  size?: number;
  stroke?: number;
  tone?: "accent" | "done";
  children?: ReactNode;
};

/** Circular progress that draws itself and counts up when it enters the viewport */
export function ProgressRing({ value, target, size = 168, stroke = 12, tone = "accent", children }: RingProps) {
  const [ref, inView] = useInViewOnce<HTMLDivElement>();
  const shown = useCountUp(value, inView, 1100);
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const offset = c * (1 - (inView ? value : 0) / 100);
  const targetAngle = target ? (target / 100) * 360 - 90 : null;

  return (
    <div ref={ref} className={`ct-ring ct-ring--${tone}`} style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true">
        <circle className="ct-ring__track" cx={size / 2} cy={size / 2} r={r} strokeWidth={stroke} fill="none" />
        <circle
          className="ct-ring__value"
          cx={size / 2}
          cy={size / 2}
          r={r}
          strokeWidth={stroke}
          fill="none"
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={offset}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
        {targetAngle !== null && (
          <line
            className="ct-ring__target"
            x1={size / 2 + (r - stroke / 2 - 3) * Math.cos((targetAngle * Math.PI) / 180)}
            y1={size / 2 + (r - stroke / 2 - 3) * Math.sin((targetAngle * Math.PI) / 180)}
            x2={size / 2 + (r + stroke / 2 + 3) * Math.cos((targetAngle * Math.PI) / 180)}
            y2={size / 2 + (r + stroke / 2 + 3) * Math.sin((targetAngle * Math.PI) / 180)}
          />
        )}
      </svg>
      <div className="ct-ring__center">
        <span className="ct-ring__num">
          {shown}
          <span className="ct-ring__unit">%</span>
        </span>
        {children}
      </div>
    </div>
  );
}

/** A short monogram mark for a skill, tinted by learning phase — no icon library needed */
export function SkillMark({ name, phase, size = "md" }: { name: string; phase: string; size?: "md" | "lg" }) {
  const words = name.replace(/[^A-Za-z0-9+#.& ]/g, " ").split(/\s+/).filter(Boolean);
  const known: Record<string, string> = {
    javascript: "JS",
    typescript: "TS",
    python: "Py",
    "html & css": "</>",
    "html/css": "</>",
    react: "Re",
    "node.js": "No",
    sql: "SQL",
    git: "Git",
    docker: "Dk",
    kubernetes: "K8s",
    linux: "Lx",
    java: "Jv",
  };
  const mark =
    known[name.toLowerCase()] ??
    (words.length > 1 ? (words[0][0] + words[1][0]).toUpperCase() : (words[0] ?? "?").slice(0, 2));
  return (
    <span className={`ct-mark ct-mark--${phase} ct-mark--${size}`} aria-hidden="true">
      {mark}
    </span>
  );
}
