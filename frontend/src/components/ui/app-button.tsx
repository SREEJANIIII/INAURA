import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Slot } from "@radix-ui/react-slot";
import { cn } from "@/lib/utils";
import "./AppButton.css";

type Variant = "primary" | "secondary" | "ghost" | "accent";
type Size = "sm" | "md" | "lg";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: Size;
  /** Style the single child (e.g. a <Link>) as this button instead of rendering a <button> */
  asChild?: boolean;
  children: ReactNode;
};

/**
 * INAURA's one button.
 *
 * primary — the single thing this view wants you to do: solid accent.
 * secondary — everything else worth a button: paper with a hairline edge.
 * ghost — quiet actions beside a primary one: no edge until hovered.
 * accent — kept as another name for primary, for older call sites.
 *
 * Plain CSS on a real <button> (or the Link it wraps): it used to carry an SVG distortion
 * filter per button, which repeated one element id many times over a page and cost phones
 * a filter pass for every button on screen.
 */
export default function Button({
  variant = "primary",
  size = "md",
  children,
  className,
  type = "button",
  asChild = false,
  ...props
}: Props) {
  const Comp = asChild ? Slot : "button";
  return (
    <Comp
      data-slot="button"
      type={asChild ? undefined : type}
      className={cn("ib", `ib--${variant === "accent" ? "primary" : variant}`, `ib--${size}`, className)}
      {...props}
    >
      {children}
    </Comp>
  );
}
