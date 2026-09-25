import * as React from "react";
import { AnimatePresence, motion, useMotionValue, useReducedMotion, useTransform } from "framer-motion";
import { cn } from "@/lib/utils";

/**
 * A stack of cards with the live one on top and the next few fanned behind it.
 *
 * Answering throws the top card off in the direction of the answer — left for a miss, right
 * for a hit — and the stack settles forward on a spring. That direction is the point: the
 * gesture and the button do the same thing, so dragging teaches you the buttons.
 *
 * Only the top few cards exist in the DOM. A revision deck can hold hundreds, and fanning
 * every one of them would run off the screen and take the page's framerate with it.
 */

export type DeckDirection = "left" | "right" | "down";

const THROW = {
  left: { x: -620, y: 40, rotate: -18 },
  right: { x: 620, y: 40, rotate: 18 },
  down: { x: 0, y: 520, rotate: 4 },
} as const;

/** How far behind the front each card sits. Small numbers: depth, not a fan. */
const STEP = { y: 16, x: 11, scale: 0.05, tilt: 2.4 };

const SPRING = { type: "spring", stiffness: 320, damping: 34, mass: 0.9 } as const;

/** Past this much drag, letting go counts as an answer rather than a nudge */
const COMMIT_PX = 110;

export type StackedDeckProps<T> = {
  /** The whole queue; only the top few are built */
  items: T[];
  getKey: (item: T) => string;
  /** How many sit behind the live one */
  depth?: number;
  /** Whether the front card is showing its answer yet */
  revealed: boolean;
  onReveal: () => void;
  /** left = didn't know, right = got it, down = almost */
  onAnswer: (direction: DeckDirection) => void;
  renderCard: (item: T, state: { front: boolean; revealed: boolean }) => React.ReactNode;
  className?: string;
  cardClassName?: string;
  label?: string;
};

export function StackedDeck<T>({
  items,
  getKey,
  depth = 3,
  revealed,
  onReveal,
  onAnswer,
  renderCard,
  className,
  cardClassName,
  label = "Revision cards",
}: StackedDeckProps<T>) {
  // Read by AnimatePresence as the card leaves, so the throw matches the answer given
  const [direction, setDirection] = React.useState<DeckDirection>("right");
  const reduced = useReducedMotion();

  const answer = React.useCallback(
    (dir: DeckDirection) => {
      setDirection(dir);
      onAnswer(dir);
    },
    [onAnswer]
  );

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (!items.length) return;
    if (!revealed) {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        onReveal();
      }
      return;
    }
    const byKey: Record<string, DeckDirection> = { ArrowLeft: "left", ArrowDown: "down", ArrowRight: "right" };
    const dir = byKey[e.key];
    if (dir) {
      e.preventDefault();
      answer(dir);
    }
  };

  const shown = items.slice(0, depth + 1);

  return (
    <div
      className={cn("relative flex w-full items-center justify-center", className)}
      role="group"
      aria-label={label}
      tabIndex={0}
      onKeyDown={onKeyDown}
    >
      <AnimatePresence custom={direction} initial={false} mode="popLayout">
        {shown
          // Painted back to front so the live card ends up on top without z-index games
          .map((item, i) => ({ item, i }))
          .reverse()
          .map(({ item, i }) => (
            <Card
              key={getKey(item)}
              i={i}
              front={i === 0}
              revealed={revealed}
              reduced={!!reduced}
              onReveal={onReveal}
              onAnswer={answer}
              className={cardClassName}
            >
              {renderCard(item, { front: i === 0, revealed: revealed && i === 0 })}
            </Card>
          ))}
      </AnimatePresence>
    </div>
  );
}

function Card({
  i,
  front,
  revealed,
  reduced,
  onReveal,
  onAnswer,
  className,
  children,
}: {
  i: number;
  front: boolean;
  revealed: boolean;
  reduced: boolean;
  onReveal: () => void;
  onAnswer: (d: DeckDirection) => void;
  className?: string;
  children: React.ReactNode;
}) {
  const x = useMotionValue(0);
  const y = useMotionValue(0);
  // The card leans into the drag, the way a real one would
  const lean = useTransform(x, [-260, 0, 260], [-9, 0, 9]);
  const pressed = React.useRef<{ x: number; y: number } | null>(null);

  // Behind the front: lower, a touch smaller, alternately tilted
  const resting = {
    x: front ? 0 : (i % 2 === 0 ? 1 : -1) * i * STEP.x,
    y: i * STEP.y,
    scale: 1 - i * STEP.scale,
    rotate: front ? 0 : (i % 2 === 0 ? 1 : -1) * i * STEP.tilt,
    opacity: i > 2 ? 0 : 1,
  };

  return (
    <motion.div
      custom={"right" as DeckDirection}
      initial={{ opacity: 0, y: resting.y + 12, scale: resting.scale - 0.02 }}
      animate={resting}
      // A dynamic variant, so the throw reads the direction at the moment the card leaves
      variants={{
        thrown: (dir: DeckDirection) => ({
          ...THROW[dir ?? "right"],
          opacity: 0,
          scale: 0.94,
          transition: reduced ? { duration: 0.12 } : { duration: 0.34, ease: [0.3, 0, 0.2, 1] },
        }),
      }}
      exit="thrown"
      transition={reduced ? { duration: 0 } : SPRING}
      style={front ? { x, y, rotate: lean, zIndex: 10 } : { zIndex: 10 - i }}
      drag={front && !reduced}
      dragSnapToOrigin
      dragElastic={0.5}
      dragConstraints={{ left: 0, right: 0, top: 0, bottom: 0 }}
      onPointerDown={(e) => {
        pressed.current = { x: e.clientX, y: e.clientY };
      }}
      onPointerUp={(e) => {
        const from = pressed.current;
        pressed.current = null;
        // A press that barely moved is a tap on the card, not a throw
        if (!front || !from) return;
        if (Math.hypot(e.clientX - from.x, e.clientY - from.y) < 8 && !revealed) onReveal();
      }}
      onDragEnd={(_, info) => {
        if (!front || !revealed) return;
        if (info.offset.x < -COMMIT_PX) onAnswer("left");
        else if (info.offset.x > COMMIT_PX) onAnswer("right");
        else if (info.offset.y > COMMIT_PX) onAnswer("down");
      }}
      className={cn(
        "absolute",
        front ? "cursor-grab active:cursor-grabbing" : "pointer-events-none",
        className
      )}
      aria-hidden={!front}
    >
      {children}
    </motion.div>
  );
}

export default StackedDeck;
