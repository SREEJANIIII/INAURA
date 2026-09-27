/* eslint-disable react-hooks/set-state-in-effect */
import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { Link } from "react-router-dom";
import {
  STATE_META,
  STATE_ORDER,
  readableHours,
  stageStatusLabel,
  tierLabel,
  type Horizon,
  type Journey,
  type JourneyStage,
  type Tier,
} from "./journeyModel";
import {
  beadPoints,
  contourPath,
  lengthAt,
  layoutJourney,
  placeLabel,
  pointAt,
  ringCount,
  type JourneyLayout,
  type Pt,
  type Rect,
} from "./journeyLayout";
import { GlyphShape } from "./StateGlyph";
import { useElementWidth, useMedia } from "./hooks";

type Props = {
  journey: Journey;
  horizon: Horizon;
  /** When the plan was made: the road's starting point */
  startedAt?: string | null;
  hoursPerWeek?: number | null;
  selectedStage: number | null;
  onSelectStage: (index: number) => void;
  onSelectSkill: (key: string) => void;
};

const shortDate = (value?: string | null) => {
  if (!value) return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
};

const weeksSpan = (s: JourneyStage) => (s.firstWeek === s.lastWeek ? `Week ${s.firstWeek}` : `Weeks ${s.firstWeek}–${s.lastWeek}`);

/** In the tall layout the road only ever runs downward, so a height maps to one distance along it */
function lengthAtY(layout: JourneyLayout, y: number) {
  const { pts, lens } = layout.samples;
  if (!pts.length || y <= pts[0].y) return 0;
  if (y >= pts[pts.length - 1].y) return layout.total;
  let lo = 0;
  let hi = pts.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (pts[mid].y < y) lo = mid;
    else hi = mid;
  }
  return lens[lo];
}

/** A half-circle rising from the horizon line: role readiness, as far round as it's got */
function Gauge({ c, r, value }: { c: Pt; r: number; value: number | null }) {
  const arc = `M${c.x - r} ${c.y} A${r} ${r} 0 0 1 ${c.x + r} ${c.y}`;
  const length = Math.PI * r;
  const share = value === null ? 0 : Math.max(0, Math.min(100, value)) / 100;
  return (
    <g className="jr-gauge">
      <path d={arc} className="jr-gauge__track" />
      <path
        d={arc}
        className="jr-gauge__value"
        strokeDasharray={`${length} ${length}`}
        style={{ strokeDashoffset: length * (1 - share) }}
      />
      <text x={c.x} y={c.y - 17} textAnchor="middle" className="jr-gauge__num">
        {value === null ? "—" : value}
        {value !== null && <tspan className="jr-gauge__unit">%</tspan>}
      </text>
      <text x={c.x} y={c.y - 4} textAnchor="middle" className="jr-gauge__cap">
        role readiness
      </text>
    </g>
  );
}

export default function JourneyMap({ journey, horizon, startedAt, hoursPerWeek, selectedStage, onSelectStage, onSelectSkill }: Props) {
  const [boxRef, width] = useElementWidth<HTMLDivElement>();
  const reduced = useMedia("(prefers-reduced-motion: reduce)");
  const maskId = `jr-draw-${useId().replace(/:/g, "")}`;
  const { stages } = journey;

  const layout = useMemo(() => (width ? layoutJourney(width, stages.length) : null), [width, stages.length]);
  const markerLen = layout ? lengthAt(layout, journey.position) : 0;

  const beads = useMemo(
    () => (layout ? stages.map((s) => beadPoints(layout, s.index, s.skills.length)) : []),
    [layout, stages]
  );

  /* ---- Revealing the road: one drawn sweep on wide screens, drawn as you scroll on narrow ones ---- */
  const rootRef = useRef<HTMLDivElement>(null);
  const [lit, setLit] = useState(0);
  const [revealing, setRevealing] = useState(false);

  useEffect(() => {
    const root = rootRef.current;
    if (!layout || !root) return;
    if (reduced || typeof IntersectionObserver === "undefined") {
      root.style.setProperty("--draw", "1");
      setLit(Infinity);
      return;
    }
    if (layout.mode === "wide") {
      if (lit === Infinity) {
        root.style.setProperty("--draw", "1");
        return;
      }
      const observer = new IntersectionObserver(
        (entries) => {
          if (!entries.some((e) => e.isIntersecting)) return;
          observer.disconnect();
          setRevealing(true);
          // Next frame, so the undrawn road paints first and the sweep has somewhere to start
          requestAnimationFrame(() => {
            root.style.setProperty("--draw", "1");
            setLit(Infinity);
          });
        },
        { rootMargin: "0px 0px -12% 0px" }
      );
      observer.observe(root);
      return () => observer.disconnect();
    }

    // Tall: the road reaches as far as the lower part of the screen has scrolled
    const thresholds = [...layout.stops, ...beads.flat().map((b) => b.len), markerLen].sort((a, b) => a - b);
    let frame = 0;
    // Once drawn, the road stays drawn: scrolling back up doesn't rub it out
    let furthest = 0;
    const update = () => {
      frame = 0;
      const top = root.getBoundingClientRect().top;
      furthest = Math.max(furthest, lengthAtY(layout, window.innerHeight * 0.8 - top));
      const len = furthest;
      root.style.setProperty("--draw", String(layout.total ? Math.min(1, len / layout.total) : 1));
      let reached = -1;
      for (const t of thresholds) if (t <= len + 2) reached = t;
      setLit((prev) => (reached > prev ? reached : prev));
    };
    const onScroll = () => {
      if (!frame) frame = requestAnimationFrame(update);
    };
    update();
    document.addEventListener("scroll", onScroll, { passive: true, capture: true });
    window.addEventListener("resize", onScroll);
    return () => {
      if (frame) cancelAnimationFrame(frame);
      document.removeEventListener("scroll", onScroll, { capture: true });
      window.removeEventListener("resize", onScroll);
    };
    // `lit` is read only to skip a second sweep; it mustn't restart the observer
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layout, reduced, beads, markerLen]);

  const isLit = (len: number) => lit >= len - 2;

  /* ---- The marker: glides along the road whenever your position changes ---- */
  const markerRef = useRef<SVGGElement>(null);
  const travelRef = useRef<number | null>(null);
  const layoutRef = useRef<JourneyLayout | null>(null);
  const [moving, setMoving] = useState(false);
  const markerLit = isLit(markerLen);

  // A layout effect, so the marker is placed before the frame that shows it
  useLayoutEffect(() => {
    const root = rootRef.current;
    const marker = markerRef.current;
    if (!layout || !root || !marker || !markerLit) return;
    const apply = (len: number) => {
      travelRef.current = len;
      root.style.setProperty("--travel", `${len}px`);
      const p = pointAt(layout, len);
      marker.setAttribute("transform", `translate(${p.x} ${p.y})`);
    };
    const first = travelRef.current === null;
    const resized = !first && layoutRef.current !== layout;
    layoutRef.current = layout;
    // Only the first sweep on a wide screen starts from the beginning; resizes just jump
    const from = first ? (layout.mode === "wide" && !reduced ? 0 : markerLen) : resized ? markerLen : (travelRef.current ?? 0);
    if (reduced || Math.abs(markerLen - from) < 0.5) {
      apply(markerLen);
      setMoving(false);
      return;
    }
    apply(from);
    setMoving(true);
    const delay = first ? 650 : 120;
    const duration = Math.max(700, Math.min(1700, Math.abs(markerLen - from) * 2.4));
    const t0 = performance.now() + delay;
    let raf = 0;
    const tick = (now: number) => {
      const t = Math.max(0, Math.min(1, (now - t0) / duration));
      const eased = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
      apply(from + (markerLen - from) * eased);
      if (t < 1) raf = requestAnimationFrame(tick);
      else setMoving(false);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [layout, markerLen, markerLit, reduced]);

  /* ---- A quiet ring when a checkpoint is reached ---- */
  const prevStatus = useRef<string[] | null>(null);
  const [ripples, setRipples] = useState<number[]>([]);
  useEffect(() => {
    const now = stages.map((s) => s.status);
    const before = prevStatus.current;
    prevStatus.current = now;
    if (!before || before.length !== now.length || reduced) return;
    const fresh = now.flatMap((s, i) => (s === "done" && before[i] !== "done" ? [i] : []));
    if (fresh.length) setRipples(fresh);
  }, [stages, reduced]);
  useEffect(() => {
    if (!ripples.length) return;
    const t = window.setTimeout(() => setRipples([]), 1900);
    return () => window.clearTimeout(t);
  }, [ripples]);

  /* ---- Geometry that depends on the layout ---- */
  const markerAt = layout ? pointAt(layout, markerLen) : null;
  // Nothing done yet: the marker sits on the start, so it takes the start caption's place
  const atStart = journey.position < 0.001;
  const here = journey.currentSkill;
  const hereLine = here
    ? `${here.shortName}${journey.currentWeek ? `, week ${journey.currentWeek}` : ""}`
    : "Every checkpoint reached";
  const labelSize = { w: Math.max(104, Math.min(190, hereLine.length * 6.6 + 26)), h: 40 };

  const labelRect: Rect | null = useMemo(() => {
    if (!layout || !markerAt) return null;
    const horizonBlock =
      layout.mode === "wide" ? layout.horizon : { x: 0, y: layout.horizonLineY - 60, w: layout.width, h: layout.height };
    const obstacles = atStart ? [...layout.panels, horizonBlock] : [...layout.panels, layout.startLabel, horizonBlock];
    return placeLabel(layout, markerAt, labelSize, obstacles, beads.flat());
    // labelSize is derived from hereLine
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layout, markerAt?.x, markerAt?.y, hereLine, beads, atStart]);

  const currentSeg = layout && journey.currentStage < stages.length ? layout.segments[journey.currentStage] : null;
  const tierRuns = useMemo(() => {
    const runs: { tier: Tier; from: number; to: number }[] = [];
    stages.forEach((s, i) => {
      const last = runs[runs.length - 1];
      if (last && last.tier === s.tier) last.to = i;
      else runs.push({ tier: s.tier, from: i, to: i });
    });
    return runs;
  }, [stages]);
  const role = horizon.role;
  const hpw = hoursPerWeek && hoursPerWeek > 0 ? hoursPerWeek : null;
  const weeksToGo = hpw ? Math.ceil(journey.remainingMinutes / 60 / hpw) : null;
  const started = shortDate(startedAt);

  const style = layout
    ? ({ height: layout.height, "--len": `${layout.total}px` } as CSSProperties)
    : undefined;

  return (
    <div className="jr-mapwrap">
      <div ref={boxRef} className="jr-measure">
        {layout && (
          <div
            ref={rootRef}
            className={`jr-map jr-map--${layout.mode}${revealing ? " is-revealing" : ""}${reduced ? " is-still" : ""}`}
            style={style}
          >
            <p className="sr-only">
              {here
                ? `You are here: heading for checkpoint ${journey.currentStage + 1} of ${stages.length}, working on ${here.name}${journey.currentWeek ? ` in week ${journey.currentWeek}` : ""}. ${journey.progress}% of your planned hours are done.`
                : `You've reached every checkpoint on this plan.`}
            </p>

            <svg className="jr-svg" width={layout.width} height={layout.height} viewBox={`0 0 ${layout.width} ${layout.height}`} aria-hidden="true">
              <defs>
                <mask id={maskId} maskUnits="userSpaceOnUse" x="0" y="0" width={layout.width} height={layout.height}>
                  <path d={layout.d} className="jr-drawmask" strokeDasharray={`${layout.total} ${layout.total}`} />
                </mask>
              </defs>

              {/* Terrain: contour rings around each checkpoint, more of them where the gap is steeper */}
              <g className="jr-terrain">
                {stages.map((s, i) => {
                  const c = layout.nodes[i];
                  const rings = ringCount(s.elevation);
                  const k = layout.mode === "wide" ? { rx: 1.5, ry: 0.72 } : { rx: 1.25, ry: 0.85 };
                  return (
                    <g key={s.index} className={`jr-rings${isLit(layout.stops[i + 1]) ? " is-lit" : ""}`} style={{ "--at": layout.stops[i + 1] / layout.total } as CSSProperties}>
                      {Array.from({ length: rings }, (_, r) => {
                        const radius = layout.nodeRadius + 14 + r * 12;
                        return <path key={r} d={contourPath(c, radius * k.rx, radius * k.ry, i * 2.3 + r * 0.9)} />;
                      })}
                    </g>
                  );
                })}
              </g>

              <g mask={`url(#${maskId})`}>
                <path d={layout.d} className="jr-groove" />
                {currentSeg && <path d={`M${currentSeg[0].x} ${currentSeg[0].y} C${currentSeg[1].x} ${currentSeg[1].y} ${currentSeg[2].x} ${currentSeg[2].y} ${currentSeg[3].x} ${currentSeg[3].y}`} className="jr-active" />}
                <path d={layout.d} className="jr-route" />
              </g>
              <path d={layout.d} className="jr-travelled" strokeDasharray={`${layout.total} ${layout.total}`} />

              {/* Leaders from each checkpoint to its label */}
              {stages.map((s, i) => {
                const n = layout.nodes[i];
                const p = layout.panels[i];
                const side = layout.sides[i];
                const r = layout.nodeRadius + 3;
                const line =
                  side === "top"
                    ? { x1: n.x, y1: p.y + p.h + 2, x2: n.x, y2: n.y - r }
                    : side === "bottom"
                      ? { x1: n.x, y1: n.y + r, x2: n.x, y2: p.y - 2 }
                      : side === "left"
                        ? { x1: n.x - r, y1: n.y, x2: p.x + p.w + 6, y2: n.y }
                        : { x1: n.x + r, y1: n.y, x2: p.x - 6, y2: n.y };
                return <line key={s.index} {...line} className={`jr-leader${isLit(layout.stops[i + 1]) ? " is-lit" : ""}`} style={{ "--at": layout.stops[i + 1] / layout.total } as CSSProperties} />;
              })}

              {/* Start */}
              <g className="jr-origin" transform={`translate(${layout.start.x} ${layout.start.y})`}>
                <circle r="5" />
                <circle r="2" className="jr-origin__core" />
              </g>

              {/* Skills along each stretch of road, one mark per skill in its state's shape */}
              {stages.map((s, i) =>
                s.skills.map((skill, k) => {
                  const b = beads[i]?.[k];
                  if (!b) return null;
                  return (
                    <g
                      key={skill.key}
                      className={`jr-bead jr-bead--${skill.state}${isLit(b.len) ? " is-lit" : ""}`}
                      transform={`translate(${b.x} ${b.y})`}
                      style={{ "--at": b.len / layout.total } as CSSProperties}
                      onClick={() => onSelectSkill(skill.key)}
                    >
                      <title>{`${skill.name}: ${STATE_META[skill.state].label}`}</title>
                      <circle r="11" className="jr-bead__hit" />
                      <circle r="7.6" className="jr-bead__halo" />
                      <GlyphShape state={skill.state} />
                    </g>
                  );
                })
              )}

              {/* Checkpoints */}
              {stages.map((s, i) => {
                const n = layout.nodes[i];
                const r = layout.nodeRadius;
                return (
                  <g
                    key={s.index}
                    className={`jr-node is-${s.status}${selectedStage === i ? " is-selected" : ""}${isLit(layout.stops[i + 1]) ? " is-lit" : ""}${ripples.includes(i) ? " is-arriving" : ""}`}
                    transform={`translate(${n.x} ${n.y})`}
                    style={{ "--at": layout.stops[i + 1] / layout.total } as CSSProperties}
                    onClick={() => onSelectStage(i)}
                  >
                    <circle r={r + 12} className="jr-node__glow" />
                    <circle r={r + 6} className="jr-node__ripple" />
                    <circle r={r} className="jr-node__disc" />
                    {s.status === "done" ? (
                      <path d="M-5.5 0.3 -1.6 4 5.6 -3.6" className="jr-node__tick" />
                    ) : (
                      <text y="0.5" textAnchor="middle" dominantBaseline="central" className="jr-node__num">
                        {s.number}
                      </text>
                    )}
                  </g>
                );
              })}

              {/* The career horizon: the road runs out onto a horizon line, readiness rising over it */}
              <g className={`jr-horizon-art${isLit(layout.total) ? " is-lit" : ""}`} style={{ "--at": 1 } as CSSProperties}>
                {[0, 7, 15, 25].map((dy, i) => (
                  <line
                    key={dy}
                    x1={layout.mode === "wide" ? layout.end.x + (i ? 18 + i * 10 : 0) : layout.end.x + (i ? 16 + i * 12 : 0)}
                    x2={layout.width - (i ? i * 16 : 0)}
                    y1={layout.horizonLineY + dy}
                    y2={layout.horizonLineY + dy}
                    className={`jr-hline jr-hline--${i}`}
                  />
                ))}
                <Gauge c={layout.gauge.c} r={layout.gauge.r} value={horizon.readiness} />
                <circle cx={layout.end.x} cy={layout.end.y} r="10" className="jr-beacon__ring" />
                <circle cx={layout.end.x} cy={layout.end.y} r="4.5" className="jr-beacon" />
              </g>

              {/* You are here */}
              {/* Positioned only by the effect above, so a re-render never snaps it ahead of its glide */}
              <g ref={markerRef} className={`jr-marker${markerLit ? " is-lit" : ""}${moving ? " is-moving" : ""}`}>
                <circle r="9" className="jr-marker__pulse" />
                <circle r="9" className="jr-marker__pulse jr-marker__pulse--late" />
                <g className="jr-marker__orbit">
                  <circle r="15" className="jr-marker__track" />
                  <circle cx="15" cy="0" r="2" className="jr-marker__moon" />
                </g>
                <circle r="8.5" className="jr-marker__body" />
                <circle r="3" className="jr-marker__core" />
              </g>
            </svg>

            {/* Start caption */}
            {!atStart && (
              <div className={`jr-start jr-start--${layout.mode}`} style={{ left: layout.startLabel.x, top: layout.startLabel.y, width: layout.startLabel.w }}>
                <span className="jr-start__name">Start</span>
                {started && <span className="jr-start__date">{started}</span>}
              </div>
            )}

            {/* Priority regions: which stretch of road is critical, high priority, or lower priority */}
            {layout.mode === "tall" &&
              tierRuns.map((run) => {
                const p = layout.panels[run.from];
                const toLeft = layout.sides[run.from] === "left";
                return (
                  <span
                    key={run.from}
                    className={`jr-region jr-region--tall jr-region--${run.tier}${toLeft ? " jr-region--end" : ""}`}
                    style={toLeft ? { right: layout.width - (p.x + p.w), top: p.y - 30 } : { left: p.x, top: p.y - 30 }}
                    aria-hidden="true"
                  >
                    {tierLabel(run.tier, role)}
                  </span>
                );
              })}

            {/* Checkpoint labels, which are also the way in to each checkpoint's detail */}
            {stages.map((s, i) => {
              const p = layout.panels[i];
              const selected = selectedStage === i;
              const counts = STATE_ORDER.filter((k) => s.counts[k] > 0);
              return (
                <button
                  key={s.index}
                  type="button"
                  className={`jr-stop jr-stop--${layout.sides[i]} is-${s.status}${selected ? " is-selected" : ""}${isLit(layout.stops[i + 1]) ? " is-lit" : ""}`}
                  style={{ left: p.x, top: p.y, width: p.w, height: p.h, "--at": layout.stops[i + 1] / layout.total } as CSSProperties}
                  onClick={() => onSelectStage(i)}
                  aria-expanded={selected}
                  aria-controls="jr-sheet"
                  aria-label={`Checkpoint ${s.number}, ${s.title}. ${stageStatusLabel(s)}, ${s.progress}% done, ${readableHours(s.minutes)} planned, ${weeksSpan(s).toLowerCase()}. ${tierLabel(s.tier, role)}. ${counts.map((k) => `${s.counts[k]} ${STATE_META[k].label.toLowerCase()}`).join(", ")}.`}
                >
                  <span className="jr-stop__head">
                    <span className="jr-stop__num">{s.number}</span>
                    {s.phase && <span className="jr-stop__phase">{s.phase}</span>}
                    {s.status !== "ahead" && <span className={`jr-stop__status jr-stop__status--${s.status}`}>{stageStatusLabel(s)}</span>}
                  </span>
                  <span className="jr-stop__title">{s.title}</span>
                  <span className="jr-stop__line">
                    <span className="jr-stop__meter" aria-hidden="true">
                      <span style={{ width: `${s.progress}%` }} />
                    </span>
                    <span className="jr-stop__facts">
                      <span>{s.progress}%</span>
                      <span>{readableHours(s.minutes)}</span>
                      <span>{weeksSpan(s)}</span>
                    </span>
                  </span>
                  <span className="jr-stop__states" aria-hidden="true">
                    {counts.map((k) => (
                      <span key={k} className="jr-stop__state" title={STATE_META[k].label}>
                        <svg width="12" height="12" viewBox="-7 -7 14 14">
                          <GlyphShape state={k} />
                        </svg>
                        {s.counts[k]}
                      </span>
                    ))}
                  </span>
                </button>
              );
            })}

            {/* You are here: the label beside the marker */}
            {labelRect && (
              <div
                className={`jr-here${markerLit && !moving ? " is-shown" : ""}`}
                style={{ left: labelRect.x, top: labelRect.y, width: labelRect.w }}
                aria-hidden="true"
              >
                <span className="jr-here__title">You are here</span>
                <span className="jr-here__sub">{hereLine}</span>
              </div>
            )}

            {/* Career horizon: where the road leads */}
            <div
              className={`jr-horizon jr-horizon--${layout.horizonText.align}${isLit(layout.total) ? " is-lit" : ""}`}
              style={{ left: layout.horizonText.x, top: layout.horizonText.y, width: layout.horizonText.w }}
            >
              <p className="jr-horizon__kicker">Career horizon</p>
              <p className="jr-horizon__role">{role}</p>
              <dl className="jr-horizon__facts">
                {horizon.coverage && (
                  <div>
                    <dt>Evidence coverage</dt>
                    <dd>
                      {horizon.coverage.withEvidence} of {horizon.coverage.total} skills
                    </dd>
                  </div>
                )}
                {horizon.confidence !== null && (
                  <div>
                    <dt>Evidence confidence</dt>
                    <dd>{horizon.confidence}%</dd>
                  </div>
                )}
                <div>
                  <dt>Still to go</dt>
                  <dd>
                    {journey.remainingMinutes > 0
                      ? `${readableHours(journey.remainingMinutes)}${weeksToGo ? `, about ${weeksToGo} week${weeksToGo === 1 ? "" : "s"}` : ""}`
                      : "Nothing left on this plan"}
                  </dd>
                </div>
              </dl>
              {!horizon.sameRole ? (
                <p className="jr-horizon__note">
                  Readiness appears once your analysis is run for {role}. <Link to="/analysis">Run it</Link>
                </p>
              ) : horizon.outdated ? (
                <p className="jr-horizon__note">
                  Your evidence changed since this was scored. <Link to="/analysis">Re-run your analysis</Link>
                </p>
              ) : horizon.tasksSinceAnalysis > 0 ? (
                <p className="jr-horizon__note">
                  {horizon.tasksSinceAnalysis} task{horizon.tasksSinceAnalysis === 1 ? "" : "s"} done since your last analysis. <Link to="/analysis">Re-run it</Link> to update readiness.
                </p>
              ) : (
                <p className="jr-horizon__note">
                  <Link to="/analysis/results">See how readiness is worked out</Link>
                </p>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Wide screens: the priority regions run beneath the map like a scale bar */}
      {layout?.mode === "wide" && (
        <div className="jr-regions" aria-hidden="true">
          {tierRuns.map((run) => {
            const step = layout.nodes.length > 1 ? layout.nodes[1].x - layout.nodes[0].x : 120;
            const x0 = Math.max(0, layout.nodes[run.from].x - step * 0.46);
            const x1 = layout.nodes[run.to].x + step * 0.46;
            return (
              <span key={run.from} className={`jr-region jr-region--${run.tier}`} style={{ left: x0, width: x1 - x0 }}>
                <span>{tierLabel(run.tier, role)}</span>
              </span>
            );
          })}
        </div>
      )}
    </div>
  );
}
