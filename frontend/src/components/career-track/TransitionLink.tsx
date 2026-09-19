import type { ComponentProps } from "react";
import { Link, useNavigate } from "react-router-dom";
import { navigateWithTransition } from "./motion";

/** A router link whose plain clicks move between pages with a view transition */
export default function TransitionLink({ to, onClick, ...rest }: ComponentProps<typeof Link> & { to: string }) {
  const navigate = useNavigate();
  return (
    <Link
      to={to}
      {...rest}
      onClick={(e) => {
        onClick?.(e);
        if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
        e.preventDefault();
        navigateWithTransition(navigate, to);
      }}
    />
  );
}
