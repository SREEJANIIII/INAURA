import { useEffect, useState, type ImgHTMLAttributes } from "react";
import { preferredTheme, type Theme } from "../../lib/theme";

type Props = ImgHTMLAttributes<HTMLImageElement>;

/** Shared theme-aware brand mark. Exactly one image is mounted at a time. */
export default function InauraLogo({ alt = "INAURA", ...props }: Props) {
  const [theme, setTheme] = useState<Theme>(preferredTheme);

  useEffect(() => {
    const onThemeChange = (event: Event) => {
      const next = (event as CustomEvent<Theme>).detail;
      if (next === "light" || next === "dark") setTheme(next);
    };
    window.addEventListener("inaura-theme-change", onThemeChange);
    return () => window.removeEventListener("inaura-theme-change", onThemeChange);
  }, []);

  return <img {...props} src={theme === "dark" ? "/logo-dark.png" : "/logo.png"} alt={alt} />;
}
