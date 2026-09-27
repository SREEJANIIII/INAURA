import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { impactOf, project, readableHours, type Journey, type JourneySkill, type ReadinessModel } from "./journeyModel";
import StateGlyph from "./StateGlyph";

type Props = {
  journey: Journey;
  model: ReadinessModel;
  role: string;
  hoursPerWeek?: number | null;
};

/** Readiness points as the chips show them: one decimal, since single skills move it a little */
const points = (share: number) => {
  const p = Math.round(share * 1000) / 10;
  return p > 0 ? `+${p}` : "+0";
};

const joinNames = (names: string[]) =>
  names.length <= 1 ? names[0] ?? "" : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;

/**
 * "What changes if you move?": pick skills to focus on and see what reaching their required
 * level would do to readiness, worked out with the analysis's own formula, plus the time it
 * takes on your plan. When the formula can't be reproduced, it says so instead of guessing.
 */
export default function MoveProjection({ journey, model, role, hoursPerWeek }: Props) {
  const open = useMemo(() => journey.skills.filter((s) => !s.tasksDone && s.state !== "proven"), [journey.skills]);
  const nextCheckpoint = useMemo(
    () => new Set(open.filter((s) => s.stage === journey.currentStage).map((s) => s.key)),
    [open, journey.currentStage]
  );
  const [picked, setPicked] = useState<Set<string> | null>(null);
  const [showAll, setShowAll] = useState(false);
  // Until you choose, it shows the checkpoint you're heading to; skills finished since drop out
  const chosen = useMemo(() => {
    const base = picked ?? nextCheckpoint;
    return new Set([...base].filter((k) => open.some((s) => s.key === k)));
  }, [picked, nextCheckpoint, open]);

  const ranked = useMemo(() => {
    if (!model.ok) return { movers: open, extras: [] as JourneySkill[] };
    const withImpact = open.map((s) => ({ s, gain: impactOf(model, s) }));
    return {
      movers: withImpact
        .filter((x) => x.gain > 0.0005)
        .sort((a, b) => b.gain - a.gain || a.s.order - b.s.order)
        .map((x) => x.s),
      extras: withImpact.filter((x) => x.gain <= 0.0005).map((x) => x.s),
    };
  }, [model, open]);

  if (!open.length) return null;

  const toggle = (key: string) => {
    const next = new Set(chosen);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setPicked(next);
  };

  const result = model.ok ? project(model, journey, chosen) : null;
  const minutes = open.filter((s) => chosen.has(s.key)).reduce((sum, s) => sum + s.remainingMinutes, 0);
  const weeks = hoursPerWeek && hoursPerWeek > 0 ? Math.max(1, Math.ceil(minutes / 60 / hoursPerWeek)) : null;
  const shown = showAll ? ranked.movers : ranked.movers.slice(0, 8);
  const biggest = ranked.movers.slice(0, 3).map((s) => s.key);
  const clearsText = result?.clears.length
    ? `That reaches checkpoint${result.clears.length === 1 ? "" : "s"} ${joinNames(result.clears.map((i) => String(i + 1).padStart(2, "0")))}.`
    : null;

  return (
    <section className="jr-proj" aria-labelledby="jr-proj-title">
      <div className="jr-proj__intro">
        <h2 id="jr-proj-title">What changes if you move?</h2>
        <p>
          Pick the skills you’d put your next hours into. INAURA works out your {role} readiness with the same formula as your analysis, as if
          each one reached the level the role needs.
        </p>
      </div>

      <div className="jr-proj__body">
        <div className="jr-proj__pick">
          <div className="jr-proj__presets" role="group" aria-label="Quick picks">
            <button type="button" className={picked === null ? "is-on" : ""} onClick={() => setPicked(null)}>
              Next checkpoint
            </button>
            {model.ok && biggest.length > 0 && (
              <button type="button" onClick={() => setPicked(new Set(biggest))}>
                Biggest gains
              </button>
            )}
            <button type="button" onClick={() => setPicked(new Set())}>
              Clear
            </button>
          </div>

          <ul className="jr-chips" aria-label="Skills to focus on">
            {shown.map((s) => (
              <li key={s.key}>
                <button type="button" className={`jr-chip${chosen.has(s.key) ? " is-on" : ""}`} aria-pressed={chosen.has(s.key)} onClick={() => toggle(s.key)}>
                  <StateGlyph state={s.state} size={12} />
                  <span className="jr-chip__name">{s.shortName}</span>
                  {model.ok ? (
                    <span className="jr-chip__gain jr-num">{points(impactOf(model, s))}</span>
                  ) : (
                    <span className="jr-chip__gain jr-num">{readableHours(s.remainingMinutes)}</span>
                  )}
                </button>
              </li>
            ))}
          </ul>
          {ranked.movers.length > 8 && (
            <button type="button" className="jr-textbtn" onClick={() => setShowAll((v) => !v)}>
              {showAll ? "Show fewer" : `Show all ${ranked.movers.length}`}
            </button>
          )}

          {ranked.extras.length > 0 && (
            <p className="jr-proj__extras">
              {joinNames(ranked.extras.slice(0, 3).map((s) => s.shortName))}
              {ranked.extras.length > 3 ? ` and ${ranked.extras.length - 3} more skills` : ""} on your plan don’t change this score. Your analysis
              counts {ranked.extras.length === 1 ? "it" : "them"} as portfolio extras, not requirements for {role}.
            </p>
          )}
        </div>

        <div className="jr-proj__out" aria-live="polite">
          {!model.ok ? (
            <div className="jr-proj__off">
              <p>{model.reason}</p>
              <Link to="/analysis" className="jr-link">
                Go to your analysis
              </Link>
              {chosen.size > 0 && (
                <p className="jr-proj__time">
                  Your picks take about {readableHours(minutes)} of planned work{weeks ? `, ${weeks} week${weeks === 1 ? "" : "s"} at ${hoursPerWeek} h a week` : ""}.
                </p>
              )}
            </div>
          ) : chosen.size === 0 || !result ? (
            <p className="jr-proj__empty">Pick a skill to see how your readiness would change.</p>
          ) : (
            <>
              <p className="jr-proj__delta">
                <span className="jr-num">{result.delta > 0 ? `+${result.delta}` : result.delta}</span>
                <span>point{Math.abs(result.delta) === 1 ? "" : "s"} of readiness</span>
              </p>
              <div className="jr-scale" role="img" aria-label={`Readiness now ${result.now}%, with these skills ${result.projected}%`}>
                <span className="jr-scale__now" style={{ width: `${result.now}%` }} />
                <span className="jr-scale__gain" style={{ left: `${result.now}%`, width: `${Math.max(0, result.projected - result.now)}%` }} />
                <span className="jr-scale__label jr-scale__label--now" style={{ right: `${100 - result.now}%` }}>
                  Now <strong className="jr-num">{result.now}%</strong>
                </span>
                <span className="jr-scale__label jr-scale__label--then" style={{ left: `${result.projected}%` }}>
                  With these <strong className="jr-num">{result.projected}%</strong>
                </span>
              </div>
              <p className="jr-proj__time">
                About {readableHours(result.minutes)} of planned work{weeks ? `, ${weeks} week${weeks === 1 ? "" : "s"} at ${hoursPerWeek} h a week` : ""}.
                {clearsText && ` ${clearsText}`}
              </p>
              {result.waiting.map((w) => (
                <p key={w.skill} className="jr-proj__warn">
                  {w.skill} is planned after {joinNames(w.needs)}, which you haven’t picked or finished.
                </p>
              ))}
              <p className="jr-proj__note">
                This assumes each skill reaches the level {role} needs and your evidence confidence stays at {model.evidence}%. Your actual score
                changes when you re-run your analysis.
              </p>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
