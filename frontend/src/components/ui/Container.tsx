import type { ReactNode } from "react";

export default function Container({
  children,
  className,
  wide,
}: {
  children: ReactNode;
  className?: string;
  wide?: boolean;
}) {
  const cls = ["container", wide ? "container--wide" : "", className]
    .filter(Boolean)
    .join(" ");
  // Note: .container is defined globally in index.css
  // wide variant uses --container-wide
  return (
    <div
      className={cls}
      style={
        wide ? ({ ["--container" as string]: "var(--container-wide)" } as React.CSSProperties) : undefined
      }
    >
      {children}
    </div>
  );
}
