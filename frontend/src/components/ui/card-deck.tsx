import * as React from "react";
import {
  motion,
  useMotionValue,
  useTransform,
  useReducedMotion,
  animate,
  type PanInfo,
  type MotionValue,
} from "framer-motion";
import { cn } from "@/lib/utils";

/**
 * A stack of cards you drag through, the front one square on and the rest fanned
 * behind it, turned and shrunk by how far from the front they are.
 *
 * Which card is in front is controlled from outside, so the page around it stays in step
 * (a counter, a filter, whatever a card reveals). Dragging reports the new one back.
 *
 * Dragging is not the only way through: the deck takes arrow keys, and the page should
 * keep its buttons too, because a drag-only control shuts out anyone not using a mouse.
 */

type DeckConfig = {
  /** Pixels dragged per card advanced */
  sensitivity: number;
  /** How far each card sits from the one in front */
  xMultiplier: number;
  yMultiplier: number;
  rotationMultiplier: number;
  scaleReduction: number;
  distanceDivisor: number;
  velocityDivisor: number;
};

const configFor = (width: number): DeckConfig => {
  if (width < 640) {
    return { sensitivity: 180, xMultiplier: 44, yMultiplier: 14, rotationMultiplier: 5, scaleReduction: 0.08, distanceDivisor: 120, velocityDivisor: 500 };
  }
  if (width < 1024) {
    return { sensitivity: 220, xMultiplier: 72, yMultiplier: 20, rotationMultiplier: 6, scaleReduction: 0.09, distanceDivisor: 160, velocityDivisor: 650 };
  }
  return { sensitivity: 250, xMultiplier: 96, yMultiplier: 26, rotationMultiplier: 7, scaleReduction: 0.1, distanceDivisor: 200, velocityDivisor: 800 };
};

const SPRING = { type: "spring", stiffness: 200, damping: 30, mass: 1 } as const;

export type CardDeckProps<T> = {
  items: T[];
  /** Which card is at the front */
  index: number;
  onIndexChange: (index: number) => void;
  /** Dragging is also how you turn a card over, when the pointer barely moved */
  onTap?: () => void;
  renderCard: (item: T, isFront: boolean) => React.ReactNode;
  /** Announced to screen readers in place of the drag surface */
  label?: string;
  className?: string;
  cardClassName?: string;
};

export function CardDeck<T>({
  items,
  index,
  onIndexChange,
  onTap,
  renderCard,
  label = "Card deck",
  className,
  cardClassName,
}: CardDeckProps<T>) {
  const progress = useMotionValue(index);
  const dragStart = React.useRef(0);
  const pressed = React.useRef<{ x: number; y: number } | null>(null);
  const reduced = useReducedMotion();
  const [width, setWidth] = React.useState(() => (typeof window === "undefined" ? 1280 : window.innerWidth));

  React.useEffect(() => {
    const onResize = () => setWidth(window.innerWidth);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const config = React.useMemo(() => configFor(width), [width]);
  const total = items.length;

  // The front card can also change from outside — a button, a keystroke, a new filter
  React.useEffect(() => {
    const from = progress.get();
    if (Math.round(from) === index) return;
    // Take the short way round a wrapping deck rather than unwinding the whole stack
    let target = index;
    if (total > 1) {
      const diff = ((index - from) % total + total) % total;
      target = from + (diff > total / 2 ? diff - total : diff);
    }
    if (reduced) {
      progress.set(target);
      return;
    }
    const controls = animate(progress, target, SPRING);
    return () => controls.stop();
  }, [index, total, progress, reduced]);

  const settle = (_: MouseEvent | TouchEvent | PointerEvent, info: PanInfo) => {
    const shift = Math.round(-info.offset.x / config.distanceDivisor + -info.velocity.x / config.velocityDivisor);
    const clamped = Math.max(-3, Math.min(3, shift));
    const target = Math.round(dragStart.current) + clamped;
    animate(progress, target, SPRING);
    if (total) onIndexChange(((target % total) + total) % total);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (!total) return;
    if (e.key === "ArrowRight") {
      e.preventDefault();
      onIndexChange((index + 1) % total);
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      onIndexChange((index - 1 + total) % total);
    } else if (onTap && (e.key === "Enter" || e.key === " ")) {
      e.preventDefault();
      onTap();
    }
  };

  if (!total) return null;

  return (
    <div className={cn("relative flex w-full items-center justify-center select-none", className)}>
      {/* One surface takes the drag, so a card being turned can't be dragged out from under it */}
      <motion.div
        drag="x"
        dragConstraints={{ left: 0, right: 0 }}
        dragElastic={0.12}
        onDragStart={() => {
          dragStart.current = progress.get();
        }}
        onDrag={(_, info) => progress.set(progress.get() - info.delta.x / config.sensitivity)}
        onDragEnd={settle}
        onPointerDown={(e) => {
          pressed.current = { x: e.clientX, y: e.clientY };
        }}
        onPointerUp={(e) => {
          const from = pressed.current;
          pressed.current = null;
          // A press that barely moved is a tap on the card, not a drag of the deck
          if (onTap && from && Math.hypot(e.clientX - from.x, e.clientY - from.y) < 8) onTap();
        }}
        onKeyDown={onKeyDown}
        role="group"
        aria-label={label}
        tabIndex={0}
        className="absolute inset-0 z-50 cursor-grab rounded-[28px] active:cursor-grabbing focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[var(--accent)]"
      />

      {items.map((item, i) => (
        <DeckCard
          key={i}
          i={i}
          total={total}
          progress={progress}
          config={config}
          className={cardClassName}
        >
          {renderCard(item, i === index)}
        </DeckCard>
      ))}
    </div>
  );
}

function DeckCard({
  i,
  total,
  progress,
  config,
  className,
  children,
}: {
  i: number;
  total: number;
  progress: MotionValue<number>;
  config: DeckConfig;
  className?: string;
  children: React.ReactNode;
}) {
  // How many places this card sits from the front, the short way round
  const offset = useTransform(progress, (p) => {
    let diff = (i - p) % total;
    if (diff > total / 2) diff -= total;
    if (diff < -total / 2) diff += total;
    return diff;
  });

  const x = useTransform(offset, (o) => o * config.xMultiplier);
  const y = useTransform(offset, (o) => (Math.abs(o) < 0.05 ? 0 : Math.abs(o) * config.yMultiplier));
  const rotate = useTransform(offset, (o) => (Math.abs(o) < 0.05 ? 0 : o * config.rotationMultiplier));
  const scale = useTransform(offset, (o) => 1 - Math.abs(o) * config.scaleReduction);
  const opacity = useTransform(offset, [-total / 2, -total / 2 + 0.6, 0, total / 2 - 0.6, total / 2], [0, 1, 1, 1, 0]);
  const zIndex = useTransform(offset, (o) => Math.round(100 - Math.abs(o) * 10));
  // The ones behind are veiled almost out, so only the front card asks to be read — but the
  // veil lifts as a card comes forward, so you can see what you're dragging towards
  const veil = useTransform(offset, [-1.2, -0.4, 0, 0.4, 1.2], [0.84, 0.26, 0, 0.26, 0.84]);

  return (
    <motion.div
      style={{ x, y, rotate, scale, opacity, zIndex }}
      className={cn("pointer-events-none absolute", className)}
      aria-hidden={undefined}
    >
      {children}
      <motion.div
        style={{ opacity: veil }}
        className="pointer-events-none absolute inset-0 rounded-[inherit] bg-[var(--deck-veil,rgba(240,238,250,0.92))]"
      />
    </motion.div>
  );
}

export default CardDeck;
