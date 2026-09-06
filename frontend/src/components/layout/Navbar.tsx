import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import Button from "../ui/Button";
import { useAuth } from "../../context/AuthContext";
import "./Navbar.css";

const navLinks = [
  { label: "How It Works", href: "#how-it-works" },
  { label: "Why INAURA", href: "#evidence" },
  { label: "For Students", href: "#industry" },
  { label: "For Institutions", href: "#problem" },
];

export default function Navbar() {
  const [open, setOpen] = useState(false);
  const { user, signOut } = useAuth();
  const navigate = useNavigate();

  const handleGetStarted = () => {
    if (user) navigate("/dashboard");
    else navigate("/signup");
  };

  const handleLogout = async () => {
    await signOut();
    navigate("/login");
  };

  return (
    <header className="nav">
      <div className="nav__inner container">
        <Link to="/" className="nav__brand" aria-label="INAURA — Home">
          <img
            src="/logo.png"
            alt="INAURA"
            className="nav__logo"
            width={144}
            height={36}
            decoding="async"
          />
        </Link>

        <nav className="nav__links" aria-label="Primary">
          {navLinks.map((l) => (
            <a key={l.label} href={l.href} className="nav__link">
              {l.label}
            </a>
          ))}
        </nav>

        <div className="nav__actions">
          {user ? (
            <>
              <Link to="/dashboard" className="nav__login">
                Dashboard
              </Link>
              <Button variant="primary" size="sm" onClick={handleLogout}>
                Logout
              </Button>
            </>
          ) : (
            <>
              <Link to="/login" className="nav__login">
                Log in
              </Link>
              <Button variant="primary" size="sm" onClick={handleGetStarted}>
                Get Started
              </Button>
            </>
          )}
        </div>

        <button
          type="button"
          className="nav__burger"
          aria-label={open ? "Close menu" : "Open menu"}
          aria-expanded={open}
          aria-controls="mobile-menu"
          onClick={() => setOpen((v) => !v)}
        >
          <span className="nav__burger-line" />
          <span className="nav__burger-line" />
          <span className="nav__burger-line" />
        </button>
      </div>

      {open && (
        <div id="mobile-menu" className="nav__mobile">
          <nav aria-label="Mobile">
            {navLinks.map((l) => (
              <a
                key={l.label}
                href={l.href}
                className="nav__mobile-link"
                onClick={() => setOpen(false)}
              >
                {l.label}
              </a>
            ))}
          </nav>
          <div className="nav__mobile-actions">
            {user ? (
              <>
                <Link
                  to="/dashboard"
                  className="nav__mobile-login"
                  onClick={() => setOpen(false)}
                >
                  Dashboard
                </Link>
                <Button
                  variant="primary"
                  size="md"
                  onClick={async () => {
                    setOpen(false);
                    await handleLogout();
                  }}
                >
                  Logout
                </Button>
              </>
            ) : (
              <>
                <Link
                  to="/login"
                  className="nav__mobile-login"
                  onClick={() => setOpen(false)}
                >
                  Log in
                </Link>
                <Button
                  variant="primary"
                  size="md"
                  onClick={() => {
                    setOpen(false);
                    handleGetStarted();
                  }}
                >
                  Get Started
                </Button>
              </>
            )}
          </div>
        </div>
      )}
    </header>
  );
}
