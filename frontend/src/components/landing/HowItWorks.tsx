import "./HowItWorks.css";

const steps = [
  {
    n: "01",
    title: "Understand You",
    desc: "Your goals, background, interests and constraints — captured cleanly at the start.",
  },
  {
    n: "02",
    title: "Analyze Your Evidence",
    desc: "Projects, coursework, experience and learning history mapped to actual skills.",
  },
  {
    n: "03",
    title: "Map Industry Requirements",
    desc: "Curated role benchmarks show what great looks like — not generic advice.",
  },
  {
    n: "04",
    title: "Build Your Roadmap",
    desc: "A sequenced, personalized plan that closes your gaps in the right order.",
  },
  {
    n: "05",
    title: "Track Your Progress",
    desc: "Evidence-linked progress that’s measurable, not just motivational.",
  },
];

export default function HowItWorks() {
  return (
    <section id="how-it-works" className="how section">
      <div className="container">
        <div className="how__header">
          <div className="eyebrow">How INAURA works</div>
          <h2 className="how__title">From evidence to employability.</h2>
          <p className="how__desc">
            Five clear steps — no black boxes. You always know what was
            evaluated, what’s missing, and what to do next.
          </p>
        </div>

        <div className="how__grid">
          {steps.map((s) => (
            <div key={s.n} className="how__card">
              <div className="how__num">{s.n}</div>
              <h3 className="how__card-title">{s.title}</h3>
              <p className="how__card-desc">{s.desc}</p>
              <div className="how__bar" aria-hidden="true">
                <span />
              </div>
            </div>
          ))}
        </div>

        <div className="how__note">
          <span className="how__note-dot" />
          <p>
            Deterministic scoring + curated industry knowledge — intelligence
            without the AI theatre.
          </p>
        </div>
      </div>
    </section>
  );
}
