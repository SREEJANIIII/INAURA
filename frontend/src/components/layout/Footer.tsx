import "./Footer.css";

// Every link lands on a section (or card) of the landing page. There's no separate About
// page yet, so About opens the section that explains why INAURA exists.
const COLUMNS = [
  {
    heading: "Product",
    links: [
      { label: "How It Works", href: "#how-it-works" },
      { label: "Features", href: "#features" },
      { label: "Career Track", href: "#career-track" },
      { label: "Opportunities", href: "#opportunities" },
    ],
  },
  {
    heading: "Why INAURA",
    links: [
      { label: "Evidence", href: "#evidence" },
      { label: "Industry Alignment", href: "#industry" },
      { label: "Why INAURA", href: "#why-inaura" },
    ],
  },
  {
    heading: "For",
    links: [
      { label: "Students", href: "#for-students" },
      { label: "Graduates", href: "#for-graduates" },
      { label: "Career Switchers", href: "#for-career-switchers" },
      { label: "Professionals", href: "#for-professionals" },
      { label: "Freelancers", href: "#for-freelancers" },
    ],
  },
  {
    heading: "Company",
    links: [
      { label: "About", href: "#problem" },
      { label: "Contact", href: "mailto:hello@inaura.example" },
    ],
  },
];

export default function Footer() {
  return (
    <footer className="footer">
      <div className="container">
        <div className="footer__top">
          <div className="footer__brand">
            <a href="/" className="footer__logo-link" aria-label="INAURA — Home">
              <span className="footer__logo-wrap">
                <img
                  src="/logo.png"
                  alt="INAURA"
                  className="footer__logo"
                  width={140}
                  height={36}
                  decoding="async"
                  loading="lazy"
                />
              </span>
            </a>
            <p className="footer__desc">
              Evidence-driven career readiness: know where you stand, see the whole path, and move
              toward the role you want with intent.
            </p>
          </div>

          {COLUMNS.map((col) => (
            <nav key={col.heading} className="footer__col" aria-label={col.heading}>
              <div className="footer__heading">{col.heading}</div>
              {col.links.map((l) => (
                <a key={l.label} href={l.href}>
                  {l.label}
                </a>
              ))}
            </nav>
          ))}
        </div>

        <div className="footer__bottom">
          <span>© {new Date().getFullYear()} INAURA. All rights reserved.</span>
          <span className="footer__tagline">Bridging skills to industry.</span>
        </div>
      </div>
    </footer>
  );
}
