import type { ReactNode } from "react";
import "./Section.css";

export default function Section({
  children,
  id,
  variant = "default",
  className,
}: {
  children: ReactNode;
  id?: string;
  variant?: "default" | "subtle" | "dark";
  className?: string;
}) {
  return (
    <section
      id={id}
      className={["section", `section--${variant}`, className].filter(Boolean).join(" ")}
    >
      {children}
    </section>
  );
}
