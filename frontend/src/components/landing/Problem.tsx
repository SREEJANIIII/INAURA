import "./Problem.css";

const items = [
  {
    step: "01",
    title: "Too many choices",
    desc: "Roles, stacks, courses — everything feels equally important. Without a signal, you chase everything.",
  },
  {
    step: "02",
    title: "Unclear priorities",
    desc: "You don't know what to learn next, or what actually moves you closer to the role you want.",
  },
  {
    step: "03",
    title: "Hidden skill gaps",
    desc: "What you’re missing isn’t obvious from a resume or a single course. Gaps stay invisible.",
  },
  {
    step: "04",
    title: "Unstructured preparation",
    desc: "Effort without sequence. Tutorials without a roadmap. Progress that can’t be measured.",
  },
];

export default function Problem() {
  return (
    <section id="problem" className="problem section section--subtle">
      <div className="container">
        <div className="problem__header">
          <div className="eyebrow">The reality for most students</div>
          <h2 className="problem__title">
            Talent isn&rsquo;t the problem.
            <br />
            <span>Clarity is.</span>
          </h2>
          <p className="problem__desc">
            Most students aren&rsquo;t behind because they lack ability — they
            lack a clear view of where they stand and what the industry
            actually expects.
          </p>
        </div>

        <div className="problem__grid" role="list">
          {items.map((item) => (
            <div key={item.step} className="problem__card" role="listitem">
              <div className="problem__step">{item.step}</div>
              <h3 className="problem__card-title">{item.title}</h3>
              <p className="problem__card-desc">{item.desc}</p>
              <div className="problem__arrow" aria-hidden="true">
                →
              </div>
            </div>
          ))}
        </div>

        <div className="problem__footer">
          <span className="problem__footer-line" aria-hidden="true" />
          <p>
            INAURA replaces guesswork with a structured, evidence-aligned view
            of your path — so effort leads to outcomes.
          </p>
        </div>
      </div>
    </section>
  );
}
