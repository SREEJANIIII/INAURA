import "./Footer.css";

export default function Footer() {
  return (
    <footer className="footer">
      <div className="container">
        <div className="footer__top">
          <div className="footer__brand">
            <a
              href="/"
              className="footer__logo-link"
              aria-label="INAURA — Home"
            >
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
            <div className="footer__tagline">Bridging skills to industry.</div>
            <p className="footer__desc">
              Professional career-readiness platform for students who want
              precision, not guesswork.
            </p>
          </div>

          <nav className="footer__col" aria-label="Product">
            <div className="footer__heading">Product</div>
            <a href="#how-it-works">How It Works</a>
            <a href="#evidence">Evidence</a>
            <a href="#industry">Industry Alignment</a>
          </nav>

          <nav className="footer__col" aria-label="Audience">
            <div className="footer__heading">For</div>
            <a href="#students">For Students</a>
            <a href="#institutions">For Institutions</a>
            <a href="#problem">Why INAURA</a>
          </nav>

          <div className="footer__col">
            <div className="footer__heading">Contact</div>
            <a href="mailto:hello@inaura.example">hello@inaura.example</a>
            <span className="footer__muted">Phase 2A — Landing only</span>
          </div>
        </div>

        <div className="footer__bottom">
          <span>© {new Date().getFullYear()} INAURA. All rights reserved.</span>
          <span className="footer__bottom-dot">·</span>
          <span>Bridging skills to industry.</span>
        </div>
      </div>
    </footer>
  );
}
