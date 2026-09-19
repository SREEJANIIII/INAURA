import { useMemo, useState } from "react";
import type { SkillGap } from "../../services/analysis";
import {
  CONFIDENCE_THRESHOLD,
  PROFICIENCY_THRESHOLD,
  QUADRANTS,
  confidenceWord,
  evidenceKindsFor,
  levelWord,
  pct,
  quadrantOf,
  skillName,
  type QuadrantKey,
} from "./analysisModel";
import { type GapActions } from "./gapActions";

const ORDER: QuadrantKey[] = ["unverified_claim", "strong_validated", "exploratory", "confirmed_gap"];

type Point = { g: SkillGap; x: number; y: number; q: QuadrantKey; label: "right" | "left" | null };

// Plot inside a small inset so points at 0% or 100% don't sit on the frame or corner labels
const plot = (v: number) => 4 + v * 0.92;

/**
 * Give each point a label on the right, or on the left if that's taken; skip it only if both clash.
 * Sizes are estimated in % of a ~700 × 380 px plot, which is close enough to avoid overlaps.
 */
function placeLabels(skills: SkillGap[]): Point[] {
  const points: Point[] = skills.map((g) => ({
    g,
    x: pct(g.current_proficiency),
    y: pct(g.confidence),
    q: quadrantOf(g),
    label: null,
  }));
  type Box = { l: number; r: number; b: number; t: number };
  const boxes: Box[] = points.map((p) => ({ l: plot(p.x) - 1.2, r: plot(p.x) + 1.2, b: plot(p.y) - 2, t: plot(p.y) + 2 }));
  const overlaps = (a: Box, c: Box) => a.l < c.r && a.r > c.l && a.b < c.t && a.t > c.b;
  for (const p of points) {
    const w = ((skillName(p.g).length * 6.6 + 14) / 700) * 100;
    const px = plot(p.x);
    const py = plot(p.y);
    const right: Box = { l: px + 1.4, r: px + 1.4 + w, b: py - 2.4, t: py + 2.4 };
    const left: Box = { l: px - 1.4 - w, r: px - 1.4, b: py - 2.4, t: py + 2.4 };
    const free = (box: Box) => box.l >= 0 && box.r <= 100 && !boxes.some((o) => overlaps(box, o));
    const side = free(right) ? "right" : free(left) ? "left" : null;
    if (side) {
      p.label = side;
      boxes.push(side === "right" ? right : left);
    }
  }
  return points;
}

export default function SkillQuadrant({ skills, actions }: { skills: SkillGap[]; actions: GapActions }) {
  const points = useMemo(() => placeLabels(skills), [skills]);
  const [selectedId, setSelectedId] = useState<string | null>(skills[0]?.id ?? null);
  const [hoverId, setHoverId] = useState<string | null>(null);
  const selected = points.find((p) => p.g.id === selectedId) ?? points[0];

  if (skills.length === 0) {
    return <p className="an-empty">No skills to plot yet. Run your analysis after adding evidence.</p>;
  }

  const counts = Object.fromEntries(ORDER.map((q) => [q, points.filter((p) => p.q === q).length])) as Record<QuadrantKey, number>;

  return (
    <div className="an-quad-wrap">
    <div className="an-quad">
      {/* Chart: shown when there's room; phones get the grouped list below instead */}
      <div className="an-quad__chart">
        <div className="an-plot" role="group" aria-label="Skills by strength and evidence confidence">
          <span className="an-plot__axis an-plot__axis--y">Evidence confidence</span>
          <span className="an-plot__axis an-plot__axis--x">Skill strength</span>
          <div className="an-plot__area">
            {[25, 50, 75].map((v) => (
              <span key={v} className="an-plot__grid" style={{ left: `${plot(v)}%` }} />
            ))}
            {[25, 50, 75].map((v) => (
              <span key={`h${v}`} className="an-plot__grid an-plot__grid--h" style={{ bottom: `${plot(v)}%` }} />
            ))}
            {/* Divider lines sit at INAURA's real thresholds, not the visual centre */}
            <span className="an-plot__line an-plot__line--v" style={{ left: `${plot(PROFICIENCY_THRESHOLD * 100)}%` }} />
            <span className="an-plot__line an-plot__line--h" style={{ bottom: `${plot(CONFIDENCE_THRESHOLD * 100)}%` }} />
            <span className="an-plot__q an-plot__q--tl">{QUADRANTS.confirmed_gap.title}</span>
            <span className="an-plot__q an-plot__q--tr">{QUADRANTS.strong_validated.title}</span>
            {/* Lower labels sit just under the confidence line, away from points near zero */}
            <span className="an-plot__q an-plot__q--bl" style={{ top: `calc(${100 - plot(CONFIDENCE_THRESHOLD * 100)}% + 8px)` }}>{QUADRANTS.exploratory.title}</span>
            <span className="an-plot__q an-plot__q--br" style={{ top: `calc(${100 - plot(CONFIDENCE_THRESHOLD * 100)}% + 8px)` }}>{QUADRANTS.unverified_claim.title}</span>

            {points.map((p) => {
              const active = p.g.id === selected?.g.id;
              const showLabel = !!p.label || active || p.g.id === hoverId;
              const flip = p.label === "left" || (!p.label && p.x > 70);
              return (
                <button
                  key={p.g.id}
                  type="button"
                  className={`an-pt an-pt--${p.q}${active ? " is-active" : ""}${flip ? " is-flipped" : ""}`}
                  style={{ left: `${plot(p.x)}%`, bottom: `${plot(p.y)}%` }}
                  onClick={() => setSelectedId(p.g.id)}
                  onMouseEnter={() => setHoverId(p.g.id)}
                  onMouseLeave={() => setHoverId(null)}
                  aria-pressed={active}
                  aria-label={`${skillName(p.g)}: strength ${p.x}%, confidence ${p.y}%, ${QUADRANTS[p.q].title}`}
                >
                  <span className="an-pt__dot" />
                  {showLabel && <span className="an-pt__label">{skillName(p.g)}</span>}
                </button>
              );
            })}
          </div>
          <span className="an-plot__tick an-plot__tick--x0">0</span>
          <span className="an-plot__tick an-plot__tick--x1">100</span>
        </div>
      </div>

      {/* Phones: the same information as grouped, tappable lists */}
      <div className="an-quad__list">
        {ORDER.map((q) => (
          <div key={q} className={`an-qgroup an-qgroup--${q}`}>
            <p className="an-qgroup__title">
              {QUADRANTS[q].title} <span className="an-faint an-num">{counts[q]}</span>
            </p>
            <div className="an-qgroup__skills">
              {points.filter((p) => p.q === q).map((p) => (
                <button
                  key={p.g.id}
                  type="button"
                  className={`an-chip${p.g.id === selected?.g.id ? " is-active" : ""}`}
                  onClick={() => setSelectedId(p.g.id)}
                  aria-pressed={p.g.id === selected?.g.id}
                >
                  {skillName(p.g)}
                </button>
              ))}
              {counts[q] === 0 && <span className="an-faint">None</span>}
            </div>
          </div>
        ))}
      </div>

      {selected && (
        <aside className={`an-quad__detail an-quad__detail--${selected.q}`} aria-live="polite">
          <p className="an-quad__qname">{QUADRANTS[selected.q].title}</p>
          <h3 className="an-quad__skill">{skillName(selected.g)}</h3>
          <dl className="an-meters">
            <div>
              <dt>Skill strength</dt>
              <dd>
                <span className="an-meter"><span style={{ width: `${selected.x}%` }} /></span>
                <span className="an-num">{levelWord(selected.g.current_proficiency)}, {selected.x}%</span>
              </dd>
            </div>
            <div>
              <dt>Evidence confidence</dt>
              <dd>
                <span className="an-meter an-meter--conf"><span style={{ width: `${selected.y}%` }} /></span>
                <span className="an-num">{confidenceWord(selected.g.confidence)}, {selected.y}%</span>
              </dd>
            </div>
          </dl>
          <p className="an-quad__sub">Supported by</p>
          <ul className="an-kinds an-kinds--compact">
            {evidenceKindsFor(selected.g)
              .filter((k) => k.present)
              .map(({ kind }) => (
                <li key={kind.key} className="is-present">
                  <span className="an-kinds__mark" aria-hidden="true">✓</span>
                  {kind.label}
                </li>
              ))}
            {evidenceKindsFor(selected.g).every((k) => !k.present) && <li className="an-faint">No evidence yet</li>}
          </ul>
          <p className="an-quad__guide">{QUADRANTS[selected.q].guidance}</p>
          <button type="button" className="an-link an-link--btn" onClick={() => actions.openDetails(selected.g)}>
            Why this position?
          </button>
        </aside>
      )}
    </div>
    </div>
  );
}
