/* eslint-disable react-refresh/only-export-components -- small kit: components plus the hooks they share */
/**
 * Scroll animation kit for the landing page (Apple-style: things rise in, words light up,
 * sections pin while their content plays). Only opacity and transform are animated, so it
 * stays smooth on phones. Everything goes still when the device asks for reduced motion.
 */
import { Component, useEffect, useRef, useState, type ReactNode } from "react";
import { MotionConfig, motion, useReducedMotionConfig, useScroll, useTransform, type MotionValue } from "framer-motion";
import "./scroll.css";

export const EASE = [0.16, 1, 0.3, 1] as const;

/**
 * Scroll mapping that changes between `from` and `to` (0–1) and holds `a` before, `b` after.
 * It always spans the whole 0–1 range: framer hands these to the browser's own scroll
 * animations, which reject ranges outside 0–1 and drift back outside a partial range.
 */
export function hold<T>(from: number, to: number, a: T, b: T): [number[], T[]] {
  const f = Math.min(Math.max(from, 0), 0.999);
  const t = Math.min(Math.max(to, f + 0.001), 1);
  const input = [0];
  const output = [a];
  if (f > 0) {
    input.push(f);
    output.push(a);
  }
  input.push(t);
  output.push(b);
  if (t < 1) {
    input.push(1);
    output.push(b);
  }
  return [input, output];
}

/** True when animations should stay still: the device asks for reduced motion, or
    <MotionSafe> switched them off after an animation failed */
export function useStill() {
  return !!useReducedMotionConfig();
}

/**
 * Safety net: if an animation ever fails in a visitor's browser, show the same content
 * without animation instead of letting the error blank the whole page.
 */
export class MotionSafe extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch(error: unknown) {
    console.warn("Landing animations turned off after an error:", error);
  }
  render() {
    // "user" follows the device's reduced-motion setting, so useStill() is true for those visitors
    return (
      <MotionConfig reducedMotion={this.state.failed ? "always" : "user"}>{this.props.children}</MotionConfig>
    );
  }
}

/** True on screens wide enough for pinned (sticky) scroll scenes */
export function useIsWide(query = "(min-width: 960px)") {
  const [wide, setWide] = useState(() => typeof window !== "undefined" && window.matchMedia(query).matches);
  useEffect(() => {
    const mq = window.matchMedia(query);
    const on = () => setWide(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, [query]);
  return wide;
}

/** Fades and rises into place the first time it scrolls into view */
export function Reveal({
  children,
  className,
  delay = 0,
  y = 36,
  amount = 0.35,
}: {
  children: ReactNode;
  className?: string;
  delay?: number;
  y?: number;
  amount?: number;
}) {
  const reduce = useStill();
  return (
    <motion.div
      className={className}
      initial={reduce ? false : { opacity: 0, y }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount }}
      transition={{ duration: 0.9, ease: EASE, delay }}
    >
      {children}
    </motion.div>
  );
}

/** Children marked <StaggerItem> rise in one after another */
export function Stagger({
  children,
  className,
  gap = 0.12,
  amount = 0.2,
  role,
}: {
  children: ReactNode;
  className?: string;
  gap?: number;
  amount?: number;
  role?: string;
}) {
  const reduce = useStill();
  return (
    <motion.div
      className={className}
      role={role}
      initial={reduce ? false : "hidden"}
      whileInView="show"
      viewport={{ once: true, amount }}
      variants={{ hidden: {}, show: { transition: { staggerChildren: gap } } }}
    >
      {children}
    </motion.div>
  );
}

export function StaggerItem({
  children,
  className,
  y = 44,
  role,
}: {
  children: ReactNode;
  className?: string;
  y?: number;
  role?: string;
}) {
  return (
    <motion.div
      className={className}
      role={role}
      variants={{
        hidden: { opacity: 0, y, scale: 0.97 },
        show: { opacity: 1, y: 0, scale: 1, transition: { duration: 0.85, ease: EASE } },
      }}
    >
      {children}
    </motion.div>
  );
}

/** A progress bar's fill that grows from the left the first time it's seen */
export function Grow({
  width,
  className,
  delay = 0,
}: {
  /** Percent of the track to fill */
  width: number;
  className?: string;
  delay?: number;
}) {
  const reduce = useStill();
  return (
    <motion.span
      className={className}
      style={{ width: `${width}%`, transformOrigin: "left center" }}
      initial={reduce ? false : { scaleX: 0 }}
      whileInView={{ scaleX: 1 }}
      viewport={{ once: true, amount: 1 }}
      transition={{ duration: 1.1, ease: EASE, delay }}
    />
  );
}

function Word({ word, i, count, progress }: { word: string; i: number; count: number; progress: MotionValue<number> }) {
  const start = i / count;
  const opacity = useTransform(progress, ...hold(start, start + 1.5 / count, 0.16, 1));
  return (
    <motion.span style={{ opacity }} className="lp-word">
      {word}{" "}
    </motion.span>
  );
}

/** A statement whose words light up one by one as it scrolls through the screen */
export function ScrubWords({ text, className }: { text: string; className?: string }) {
  const ref = useRef<HTMLParagraphElement>(null);
  const reduce = useStill();
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start 0.88", "end 0.42"] });
  const words = text.split(" ");
  if (reduce) return <p ref={ref} className={className}>{text}</p>;
  return (
    <p ref={ref} className={className}>
      {/* Screen readers get the sentence whole; the lit-up words are visual only */}
      <span className="lp-sr">{text}</span>
      <span aria-hidden="true">
        {words.map((w, i) => (
          <Word key={i} word={w} i={i} count={words.length} progress={scrollYProgress} />
        ))}
      </span>
    </p>
  );
}

/** Scroll progress (0 → 1) of an element across a chosen stretch of the screen */
export function useProgress(
  offset: NonNullable<Parameters<typeof useScroll>[0]>["offset"] = ["start 0.9", "end 0.5"],
) {
  const ref = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({ target: ref, offset });
  return { ref, progress: scrollYProgress };
}
