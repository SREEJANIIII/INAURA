import { useEffect, useState } from "react";
import { Link, Outlet } from "react-router-dom";
import Sidebar from "./Sidebar";
import AccountMenu from "./AccountMenu";
import SearchBar from "../search/SearchBar";
import { preloadPageData } from "../../lib/pageData";
import "./AppLayout.css";

const isSmallScreen = () => window.matchMedia("(max-width: 860px)").matches;

// Shared frame for logged-in pages: top bar with menu button + sidebar that stays across pages
export default function AppLayout() {
  // Open by default on computers, closed on phones so it doesn't cover the page
  const [open, setOpen] = useState(() => !isSmallScreen());

  // Start loading every sidebar page's data now, so the first click on each is quick too
  useEffect(() => {
    preloadPageData();
  }, []);

  return (
    <div className="app">
      <header className="app__bar">
        <div className="app__lead">
          <button
            type="button"
            className="app__menu"
            aria-label={open ? "Close menu" : "Open menu"}
            aria-expanded={open}
            onClick={() => setOpen((o) => !o)}
          >
            <span />
            <span />
            <span />
          </button>
          <Link to="/career-track" className="app__brand" aria-label="INAURA home">
            <img src="/logo.png" alt="INAURA" width={120} height={30} />
          </Link>
        </div>
        {/* Search isn't built yet: the bar is fully interactive, and onSubmit is where results will plug in */}
        <div className="app__search">
          <SearchBar />
        </div>
        <div className="app__actions">
          <AccountMenu />
        </div>
      </header>

      <div className="app__body">
        {open && <div className="app__backdrop" onClick={() => setOpen(false)} />}
        <Sidebar
          open={open}
          onNavigate={() => {
            if (isSmallScreen()) setOpen(false);
          }}
        />
        <div className="app__content">
          <Outlet />
        </div>
      </div>
    </div>
  );
}
