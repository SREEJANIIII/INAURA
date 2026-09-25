import type { Location } from "react-router-dom";

/** Where a signed-in visitor goes when there's nowhere better to send them */
export const HOME = "/career-track";

/** The page someone was sent to log in from, so logging in can take them back there */
export function returnPath(state: unknown): string {
  const from = (state as { from?: Location } | null)?.from;
  if (!from?.pathname || ["/login", "/signup", "/reset-password"].includes(from.pathname)) return HOME;
  return `${from.pathname}${from.search ?? ""}${from.hash ?? ""}`;
}
