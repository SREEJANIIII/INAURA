import { Suspense, useEffect, useState } from "react";
import { Link, Outlet } from "react-router-dom";
import Sidebar from "./Sidebar";
import AccountMenu from "./AccountMenu";
<<<<<<< HEAD
import SearchBar from "../search/SearchBar";
import InauraLogo from "./InauraLogo";
=======
import AppSearch from "../search/AppSearch";
>>>>>>> 3cad89f448472cdaf6129a10e69895215a350f21
import { preloadPageData } from "../../lib/pageData";
import "./AppLayout.css";

const SMALL = "(max-width: 860px)";
const isSmallScreen = () => window.matchMedia(SMALL).matches;

/** Shown for the moment a page's code is still downloading — the shape of a page, not a spinner */
function PageLoading() {
  return (
    <div className="app__loading" aria-busy="true">
      <div className="app__loading-line app__loading-line--title" />
      <div className="app__loading-line" />
      <div className="app__loading-block" />
      <span className="sr-only">Loading…</span>
    </div>
  );
}

// Shared frame for logged-in pages: top bar with menu button + sidebar that stays across pages
export default function AppLayout() {
  // Open by default on computers, closed on phones so it doesn't cover the page
  const [open, setOpen] = useState(() => !isSmallScreen());

  // Start loading every sidebar page's data now, so the first click on each is quick too
  useEffect(() => {
    preloadPageData();
  }, []);

  // Crossing between phone and computer widths resets the sidebar to suit the new screen,
  // rather than leaving a phone with a sidebar over the page
  useEffect(() => {
    const query = window.matchMedia(SMALL);
    const onChange = () => setOpen(!query.matches);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  // On a phone the open sidebar covers the page, so Escape puts it away
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isSmallScreen() && !e.defaultPrevented) setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <div className="app">
      <a href="#main-content" className="skip-link">Skip to content</a>
      <header className="app__bar">
        <div className="app__lead">
          <button
            type="button"
            className="app__menu"
            aria-label={open ? "Close menu" : "Open menu"}
            aria-expanded={open}
            aria-controls="app-sidebar"
            onClick={() => setOpen((o) => !o)}
          >
            <span />
            <span />
            <span />
          </button>
          <Link to="/career-track" className="app__brand" aria-label="INAURA home">
            <InauraLogo alt="INAURA" width={120} height={30} />
          </Link>
        </div>
        <div className="app__search">
          <AppSearch />
        </div>
        <div className="app__actions">
          <AccountMenu />
        </div>
      </header>

      <div className="app__body">
        {open && <div className="app__backdrop" onClick={() => setOpen(false)} aria-hidden="true" />}
        <Sidebar
          open={open}
          onNavigate={() => {
            if (isSmallScreen()) setOpen(false);
          }}
        />
        <main id="main-content" className="app__content" tabIndex={-1}>
          {/* Only the very first page waits on this; after that, the page you're on stays up
              until the next one has loaded */}
          <Suspense fallback={<PageLoading />}>
            <Outlet />
          </Suspense>
        </main>
      </div>
    </div>
  );
}
