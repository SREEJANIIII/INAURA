import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { animate, motion, useMotionValue, useReducedMotion, useTransform, useVelocity } from "framer-motion";
import Button from "../ui/app-button";
import { useAuth } from "../../context/AuthContext";
import InauraLogo from "./InauraLogo";
import "./Navbar.css";

const navLinks = [
  { label: "How It Works", href: "#how-it-works" },
  { label: "Features", href: "#features" },
  { label: "Career Track", href: "#career-track" },
  { label: "Opportunities", href: "#opportunities" },
  { label: "Why INAURA", href: "#why-inaura" },
];

const SECTION_IDS = navLinks.map((l) => l.href.slice(1));

// The active capsule's two edges run on different springs: the edge heading toward the new tab
// is quick and a little springy, the trailing edge follows softly. So the capsule stretches,
// flows across and gathers itself on arrival instead of sliding as a rigid block.
const LEAD = { type: "spring", stiffness: 420, damping: 28, mass: 0.8 } as const;
const TRAIL = { type: "spring", stiffness: 230, damping: 26, mass: 0.9 } as const;

/**
 * Which landing section is under the reading line (a little below the navbar). A clicked link
 * takes over straight away and holds until its smooth scroll comes to rest, so the capsule
 * flows once to the chosen tab rather than stepping through every section passed on the way.
 */
function useActiveSection() {
  const [active, setActive] = useState<string | null>(null);
  const [scrolled, setScrolled] = useState(false);
  const pinned = useRef(false);
  const settle = useRef<number | undefined>(undefined);

  useEffect(() => {
    let frame = 0;
    const read = () => {
      frame = 0;
      setScrolled(window.scrollY > 8);
      if (pinned.current) return;
      const line = window.innerHeight * 0.35;
      const hit = SECTION_IDS.find((id) => {
        const r = document.getElementById(id)?.getBoundingClientRect();
        return !!r && r.top <= line && r.bottom > line;
      });
      setActive(hit ?? null);
    };
    const onScroll = () => {
      if (pinned.current) {
        window.clearTimeout(settle.current);
        settle.current = window.setTimeout(() => {
          pinned.current = false;
          read();
        }, 160);
      }
      if (!frame) frame = requestAnimationFrame(read);
    };
    frame = requestAnimationFrame(read);
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => {
      cancelAnimationFrame(frame);
      window.clearTimeout(settle.current);
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
    };
  }, []);

  const choose = useCallback((id: string) => {
    pinned.current = true;
    setActive(id);
    window.clearTimeout(settle.current);
    // Already at that section, so no scroll follows: let the reading line take back over
    settle.current = window.setTimeout(() => {
      pinned.current = false;
    }, 600);
  }, []);

  return { active, scrolled, choose };
}

export default function Navbar() {
  const [open, setOpen] = useState(false);
  const { user, signOut } = useAuth();
  const navigate = useNavigate();
  const { active, scrolled, choose } = useActiveSection();
  const reduce = useReducedMotion();

  const handleGetStarted = () => {
    if (user) navigate("/career-track");
    else navigate("/signup");
  };

  const handleLogout = async () => {
    await signOut();
    navigate("/login");
  };

  // The capsule is drawn from its two edges; width, and a slight squash while it's
  // travelling fast, follow from them
  const trackRef = useRef<HTMLElement>(null);
  const tabRefs = useRef<Record<string, HTMLAnchorElement | null>>({});
  const activeRef = useRef<string | null>(null);
  const shown = useRef(false);
  const left = useMotionValue(0);
  const right = useMotionValue(0);
  const opacity = useMotionValue(0);
  const width = useTransform([left, right], ([l, r]: number[]) => r - l);
  const centre = useTransform([left, right], ([l, r]: number[]) => (l + r) / 2);
  const scaleY = useTransform(useVelocity(centre), [-1800, 0, 1800], [0.92, 1, 0.92]);

  const place = useCallback(
    (id: string | null, instant = false) => {
      const tab = id ? tabRefs.current[id] : null;
      if (!tab || !tab.offsetWidth) {
        shown.current = false;
        animate(opacity, 0, { duration: instant || reduce ? 0 : 0.22, ease: "easeOut" });
        return;
      }
      const l = tab.offsetLeft;
      const r = l + tab.offsetWidth;
      if (instant || reduce || !shown.current) {
        // Appearing for the first time: form in place rather than sweeping in from the edge
        left.jump(l);
        right.jump(r);
      } else {
        const rightward = l > left.get();
        animate(left, l, rightward ? TRAIL : LEAD);
        animate(right, r, rightward ? LEAD : TRAIL);
      }
      shown.current = true;
      animate(opacity, 1, { duration: instant || reduce ? 0 : 0.3, ease: "easeOut" });
    },
    [left, right, opacity, reduce],
  );

  useLayoutEffect(() => {
    activeRef.current = active;
    place(active);
  }, [active, place]);

  // Re-measure without animating when the layout shifts (window resized, web font arrives)
  useEffect(() => {
    const track = trackRef.current;
    if (!track) return;
    const snap = () => place(activeRef.current, true);
    const observer = new ResizeObserver(snap);
    observer.observe(track);
    document.fonts?.ready.then(snap);
    return () => observer.disconnect();
  }, [place]);

  return (
    <header className="nav" data-scrolled={scrolled || undefined}>
      <div className="nav__pill">
        <Link to="/" className="nav__brand" aria-label="INAURA — Home">
          <InauraLogo
            alt="INAURA"
            className="nav__logo"
            width={1748}
            height={899}
            decoding="async"
          />
        </Link>

        <nav className="nav__links" aria-label="Primary" ref={trackRef}>
          <motion.span className="nav__capsule" aria-hidden="true" style={{ x: left, width, scaleY, opacity }} />
          {navLinks.map((l) => {
            const id = l.href.slice(1);
            const isActive = active === id;
            return (
              <a
                key={l.label}
                ref={(el) => {
                  tabRefs.current[id] = el;
                }}
                href={l.href}
                className={isActive ? "nav__link is-active" : "nav__link"}
                aria-current={isActive ? "location" : undefined}
                onClick={() => choose(id)}
              >
                {l.label}
              </a>
            );
          })}
        </nav>

        <div className="nav__actions">
          {user ? (
            <>
              <Link to="/career-track" className="nav__login">
                My Career Track
              </Link>
              <Button variant="primary" size="md" className="nav__cta" onClick={handleLogout}>
                Logout
              </Button>
            </>
          ) : (
            <>
              <Link to="/login" className="nav__login">
                Log in
              </Link>
              <Button variant="primary" size="md" className="nav__cta" onClick={handleGetStarted}>
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
            {navLinks.map((l) => {
              const id = l.href.slice(1);
              const isActive = active === id;
              return (
                <a
                  key={l.label}
                  href={l.href}
                  className={isActive ? "nav__mobile-link is-active" : "nav__mobile-link"}
                  aria-current={isActive ? "location" : undefined}
                  onClick={() => {
                    choose(id);
                    setOpen(false);
                  }}
                >
                  {l.label}
                </a>
              );
            })}
          </nav>
          <div className="nav__mobile-actions">
            {user ? (
              <>
                <Link
                  to="/career-track"
                  className="nav__mobile-login"
                  onClick={() => setOpen(false)}
                >
                  My Career Track
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
