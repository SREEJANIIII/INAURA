import type { ButtonHTMLAttributes, ReactNode } from "react";
import "./Button.css";

type Variant = "primary" | "secondary" | "ghost" | "accent";
type Size = "sm" | "md" | "lg";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: Size;
  children: ReactNode;
};

export default function Button({
  variant = "primary",
  size = "md",
  children,
  className,
  ...props
}: Props) {
  const cls = ["btn", `btn--${variant}`, `btn--${size}`, className]
    .filter(Boolean)
    .join(" ");
  return (
    <button className={cls} {...props}>
      <span className="btn__label">{children}</span>
    </button>
  );
}
