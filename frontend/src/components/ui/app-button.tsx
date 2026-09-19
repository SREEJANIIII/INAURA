import type { ButtonHTMLAttributes, ReactNode } from "react";
import { LiquidButton } from "@/components/ui/liquid-glass-button";
import { cn } from "@/lib/utils";

type Variant = "primary" | "secondary" | "ghost" | "accent";
type Size = "sm" | "md" | "lg";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: Size;
  /** Style the single child (e.g. a <Link>) as this button instead of rendering a <button> */
  asChild?: boolean;
  children: ReactNode;
};

// INAURA's sizes on the liquid glass scale
const GLASS_SIZE = { sm: "sm", md: "lg", lg: "xl" } as const;

// Every button is liquid glass. The main action is tinted lavender glass so it still stands out;
// the rest are clear glass. On dark screens (inside .dark) the glass is smoky instead.
const VARIANT_TEXT: Record<Variant, string> = {
  primary:
    "font-semibold text-[#2f2566] bg-[rgba(100,82,176,0.16)] hover:bg-[rgba(100,82,176,0.24)] dark:text-white dark:bg-white/15 dark:hover:bg-white/25",
  secondary: "text-primary bg-white/45 hover:bg-white/65 dark:bg-white/8 dark:hover:bg-white/15",
  ghost: "text-muted-foreground bg-white/20 hover:bg-white/45 dark:bg-transparent dark:hover:bg-white/10",
  accent:
    "font-semibold text-[#2f2566] bg-[rgba(100,82,176,0.16)] hover:bg-[rgba(100,82,176,0.24)] dark:text-white dark:bg-white/15 dark:hover:bg-white/25",
};

export default function Button({
  variant = "primary",
  size = "md",
  children,
  className,
  type = "button",
  asChild = false,
  ...props
}: Props) {
  return (
    <LiquidButton
      asChild={asChild}
      type={asChild ? undefined : type}
      size={GLASS_SIZE[size]}
      className={cn("rounded-full border-0 [font-family:inherit]", VARIANT_TEXT[variant], className)}
      {...props}
    >
      {children}
    </LiquidButton>
  );
}
