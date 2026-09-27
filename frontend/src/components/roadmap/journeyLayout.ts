/**
 * Journey map geometry: where the road, the checkpoints, their labels and the career horizon
 * sit for a given width. Wide screens get a road that winds left to right with labels above
 * and below it; narrower ones get a road that winds down the page with labels beside it.
 *
 * Pure numbers only (no DOM), so layouts can be tested and computed before anything renders.
 */

export type Pt = { x: number; y: number };
export type Rect = { x: number; y: number; w: number; h: number };
export type Cubic = [Pt, Pt, Pt, Pt];
export type LayoutMode = "wide" | "tall";
export type Side = "top" | "bottom" | "left" | "right";

export type JourneyLayout = {
  mode: LayoutMode;
  width: number;
  height: number;
  start: Pt;
  nodes: Pt[];
  /** Where the road meets the career horizon */
  end: Pt;
  /** segments[i] leads into nodes[i]; the last one leads from the final checkpoint to the horizon */
  segments: Cubic[];
  d: string;
  /** Distance along the road at the start (0), at each checkpoint, and at the horizon */
  stops: number[];
  total: number;
  panels: Rect[];
  /** Which side of its checkpoint each label sits on */
  sides: Side[];
  /** Where the "Start" caption goes */
  startLabel: Rect;
  /** The horizon's block, the line it stands on, its text, and the readiness arc rising over it */
  horizon: Rect;
  horizonLineY: number;
  horizonText: Rect & { align: "left" | "center" };
  gauge: { c: Pt; r: number };
  nodeRadius: number;
  /** Points every few pixels along the road, for lookups and collision checks */
  samples: { pts: Pt[]; lens: number[] };
};

/* ---------------- Curves ---------------- */

export function cubicAt([p0, c1, c2, p1]: Cubic, t: number): Pt {
  const u = 1 - t;
  const a = u * u * u;
  const b = 3 * u * u * t;
  const c = 3 * u * t * t;
  const d = t * t * t;
  return { x: a * p0.x + b * c1.x + c * c2.x + d * p1.x, y: a * p0.y + b * c1.y + c * c2.y + d * p1.y };
}

const r1 = (n: number) => Math.round(n * 10) / 10;

function pathOf(segments: Cubic[]) {
  if (!segments.length) return "";
  const [p0] = segments[0];
  return (
    `M${r1(p0.x)} ${r1(p0.y)}` +
    segments.map(([, c1, c2, p1]) => ` C${r1(c1.x)} ${r1(c1.y)} ${r1(c2.x)} ${r1(c2.y)} ${r1(p1.x)} ${r1(p1.y)}`).join("")
  );
}

/** Sample the whole road, recording the running length at each point */
function sampleRoad(segments: Cubic[], perSegment = 64) {
  const pts: Pt[] = [];
  const lens: number[] = [];
  const stops: number[] = [0];
  let total = 0;
  segments.forEach((seg, i) => {
    for (let k = i === 0 ? 0 : 1; k <= perSegment; k++) {
      const p = cubicAt(seg, k / perSegment);
      if (pts.length) total += Math.hypot(p.x - pts[pts.length - 1].x, p.y - pts[pts.length - 1].y);
      pts.push(p);
      lens.push(total);
    }
    stops.push(total);
  });
  return { pts, lens, stops, total };
}

/** The point a given distance along the road */
export function pointAt(layout: Pick<JourneyLayout, "samples">, len: number): Pt {
  const { pts, lens } = layout.samples;
  if (!pts.length) return { x: 0, y: 0 };
  if (len <= 0) return pts[0];
  if (len >= lens[lens.length - 1]) return pts[pts.length - 1];
  let lo = 0;
  let hi = lens.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (lens[mid] < len) lo = mid;
    else hi = mid;
  }
  const span = lens[hi] - lens[lo] || 1;
  const t = (len - lens[lo]) / span;
  return { x: pts[lo].x + (pts[hi].x - pts[lo].x) * t, y: pts[lo].y + (pts[hi].y - pts[lo].y) * t };
}

/** Distance along the road for a journey position (0 = start, k = checkpoint k) */
export function lengthAt(layout: Pick<JourneyLayout, "stops">, position: number) {
  const { stops } = layout;
  const last = stops.length - 2; // the final checkpoint; the horizon lies beyond it
  const p = Math.max(0, Math.min(Math.max(0, last), position));
  const i = Math.floor(p);
  if (i >= last) return stops[Math.max(0, last)];
  return stops[i] + (stops[i + 1] - stops[i]) * (p - i);
}

/** Where a checkpoint's skills sit on the stretch of road leading into it */
export function beadPoints(layout: Pick<JourneyLayout, "stops" | "samples">, stage: number, count: number) {
  const a = layout.stops[stage];
  const b = layout.stops[stage + 1];
  if (count <= 0 || b === undefined) return [];
  const from = a + (b - a) * 0.24;
  const to = a + (b - a) * 0.76;
  return Array.from({ length: count }, (_, i) => {
    const len = count === 1 ? (from + to) / 2 : from + ((to - from) * i) / (count - 1);
    return { ...pointAt(layout, len), len };
  });
}

/* ---------------- Layouts ---------------- */

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

/** The width the horizon takes on a wide map */
const horizonWidth = (W: number) => Math.round(clamp(W * 0.23, 212, 260));

/** Whether a width has room for the left-to-right road with this many checkpoints */
export function fitsWide(width: number, stages: number) {
  const W = Math.round(width);
  return W >= 720 && (W - horizonWidth(W) - 4) / (stages + 1) >= 100;
}

export const PANEL_H = { wide: 112, tall: 116 };

function wideLayout(W: number, n: number): Omit<JourneyLayout, "samples" | "stops" | "total" | "d"> & { segments: Cubic[] } {
  const hw = horizonWidth(W);
  const startX = 14;
  const endX = W - hw + 12;
  const step = (endX - startX) / (n + 1);
  const panelH = PANEL_H.wide;
  const leader = 26;
  // A generous swing: the road is the page's main picture, not a timeline rule
  const amp = clamp(step * 1.45, 130, 190);
  const topY = 4 + panelH + leader;
  const bottomY = topY + amp;
  const midY = (topY + bottomY) / 2;
  const height = Math.round(bottomY + leader + panelH + 6);

  // The road starts low and climbs, alternating up and down through the checkpoints
  const start = { x: startX, y: bottomY };
  const nodes = Array.from({ length: n }, (_, i) => ({ x: startX + step * (i + 1), y: i % 2 === 0 ? topY : bottomY }));
  const end = { x: endX, y: midY - 12 };
  const points = [start, ...nodes, end];
  const segments: Cubic[] = points.slice(1).map((p1, i) => {
    const p0 = points[i];
    const dx = p1.x - p0.x;
    return [p0, { x: p0.x + dx * 0.5, y: p0.y }, { x: p1.x - dx * 0.5, y: p1.y }, p1];
  });

  const panelW = Math.min(250, Math.floor(step * 2 - 16));
  const maxX = W - hw - panelW - 6;
  const panels = nodes.map((p, i) => ({
    x: clamp(p.x - panelW / 2, 0, Math.max(0, maxX)),
    y: i % 2 === 0 ? 4 : bottomY + leader,
    w: panelW,
    h: panelH,
  }));

  return {
    mode: "wide",
    width: W,
    height,
    start,
    nodes,
    end,
    segments,
    panels,
    sides: nodes.map((_, i) => (i % 2 === 0 ? "top" : "bottom")),
    startLabel: { x: 0, y: bottomY + 16, w: 84, h: 34 },
    horizon: { x: W - hw, y: 0, w: hw, h: height },
    horizonLineY: end.y,
    horizonText: { x: W - hw + 18, y: end.y + 34, w: hw - 22, h: height - end.y - 34, align: "left" },
    gauge: { c: { x: W - hw + hw * 0.55, y: end.y }, r: Math.min(54, hw * 0.24) },
    nodeRadius: 17,
  };
}

/** Tablets: the road winds down the middle, checkpoints alternating right and left of it */
function centreLayout(W: number, n: number): Omit<JourneyLayout, "samples" | "stops" | "total" | "d"> & { segments: Cubic[] } {
  const ax = Math.round(W / 2);
  // The bows stay narrow enough near each checkpoint that its label, 44px out, stays clear
  const wob = 56;
  const gap = 44;
  const panelH = PANEL_H.tall;
  const panelW = Math.min(300, ax - gap);
  const spacing = 250;
  const start = { x: ax, y: 22 };
  const nodes = Array.from({ length: n }, (_, i) => ({ x: ax, y: start.y + spacing * 0.9 + spacing * i }));
  const last = nodes[nodes.length - 1] ?? start;
  const end = { x: ax, y: last.y + spacing * 0.75 };
  const points = [start, ...nodes, end];
  // Each stretch bows away from the label of the checkpoint it leads into
  const segments: Cubic[] = points.slice(1).map((p1, i) => {
    const p0 = points[i];
    const dy = p1.y - p0.y;
    const side = i % 2 === 0 ? -1 : 1;
    return [p0, { x: p0.x + side * wob, y: p0.y + dy * 0.3 }, { x: p1.x + side * wob, y: p1.y - dy * 0.3 }, p1];
  });
  const height = Math.round(end.y + 258);
  return {
    mode: "tall",
    width: W,
    height,
    start,
    nodes,
    end,
    segments,
    panels: nodes.map((p, i) => ({
      x: i % 2 === 0 ? ax + gap : ax - gap - panelW,
      y: p.y - panelH / 2,
      w: panelW,
      h: panelH,
    })),
    sides: nodes.map((_, i) => (i % 2 === 0 ? "right" : "left")),
    startLabel: { x: ax + 20, y: start.y - 12, w: 200, h: 30 },
    horizon: { x: 0, y: end.y - 64, w: W, h: height - end.y + 64 },
    horizonLineY: end.y,
    horizonText: { x: ax - 180, y: end.y + 36, w: 360, h: 210, align: "center" },
    gauge: { c: { x: Math.min(W - 60, ax + 150), y: end.y }, r: 48 },
    nodeRadius: 16,
  };
}

/** Phones: the road runs down the left edge with a gentle meander, labels beside it */
function railLayout(W: number, n: number): Omit<JourneyLayout, "samples" | "stops" | "total" | "d"> & { segments: Cubic[] } {
  const roomy = W >= 480;
  const ax = roomy ? 40 : 26;
  const wob = roomy ? 30 : 18;
  const panelX = ax + wob + (roomy ? 34 : 24);
  const panelH = PANEL_H.tall;
  const spacing = panelH + 70;
  const start = { x: ax, y: 22 };
  const nodes = Array.from({ length: n }, (_, i) => ({ x: ax, y: start.y + spacing * 0.8 + spacing * i }));
  const last = nodes[nodes.length - 1] ?? start;
  const end = { x: ax, y: last.y + spacing * 0.78 };
  const points = [start, ...nodes, end];
  // A gentle meander: each stretch bows out to one side, then the other
  const segments: Cubic[] = points.slice(1).map((p1, i) => {
    const p0 = points[i];
    const dy = p1.y - p0.y;
    const side = i % 2 === 0 ? 1 : -1;
    return [p0, { x: p0.x + side * wob, y: p0.y + dy * 0.3 }, { x: p1.x + side * wob, y: p1.y - dy * 0.3 }, p1];
  });
  const horizonTop = end.y - 64;
  const height = Math.round(end.y + 262);

  return {
    mode: "tall",
    width: W,
    height,
    start,
    nodes,
    end,
    segments,
    panels: nodes.map((p) => ({ x: panelX, y: p.y - panelH / 2, w: W - panelX, h: panelH })),
    sides: nodes.map(() => "right"),
    startLabel: { x: panelX, y: start.y - 12, w: Math.min(220, W - panelX), h: 30 },
    horizon: { x: 0, y: horizonTop, w: W, h: height - horizonTop },
    horizonLineY: end.y,
    horizonText: { x: panelX, y: end.y + 36, w: W - panelX, h: 210, align: "left" },
    gauge: { c: { x: W - 54, y: end.y }, r: 46 },
    nodeRadius: 15,
  };
}

export function layoutJourney(width: number, stages: number, mode?: LayoutMode): JourneyLayout {
  const W = Math.max(280, Math.round(width));
  const n = Math.max(1, stages);
  const chosen = mode ?? (fitsWide(W, n) ? "wide" : "tall");
  const base = chosen === "wide" ? wideLayout(W, n) : W >= 600 ? centreLayout(W, n) : railLayout(W, n);
  const road = sampleRoad(base.segments);
  return {
    ...base,
    d: pathOf(base.segments),
    stops: road.stops,
    total: road.total,
    samples: { pts: road.pts, lens: road.lens },
  };
}

/* ---------------- Terrain ---------------- */

/**
 * One contour ring: a closed, slightly irregular loop, the same shape every render for the
 * same seed, so the terrain doesn't shimmer when the page updates.
 */
export function contourPath(c: Pt, rx: number, ry: number, seed: number) {
  const steps = 40;
  const pts: Pt[] = [];
  for (let i = 0; i < steps; i++) {
    const a = (i / steps) * Math.PI * 2;
    const wobble = 1 + 0.07 * Math.sin(3 * a + seed) + 0.04 * Math.sin(5 * a + seed * 1.7);
    pts.push({ x: c.x + Math.cos(a) * rx * wobble, y: c.y + Math.sin(a) * ry * wobble });
  }
  // A smooth closed curve through the points (Catmull-Rom as Béziers)
  let d = `M${r1(pts[0].x)} ${r1(pts[0].y)}`;
  for (let i = 0; i < steps; i++) {
    const p0 = pts[(i - 1 + steps) % steps];
    const p1 = pts[i];
    const p2 = pts[(i + 1) % steps];
    const p3 = pts[(i + 2) % steps];
    const c1 = { x: p1.x + (p2.x - p0.x) / 6, y: p1.y + (p2.y - p0.y) / 6 };
    const c2 = { x: p2.x - (p3.x - p1.x) / 6, y: p2.y - (p3.y - p1.y) / 6 };
    d += ` C${r1(c1.x)} ${r1(c1.y)} ${r1(c2.x)} ${r1(c2.y)} ${r1(p2.x)} ${r1(p2.y)}`;
  }
  return `${d} Z`;
}

/** How many contour rings a checkpoint's terrain gets (0–5): steeper for bigger gaps */
export const ringCount = (elevation: number) => (elevation > 0.02 ? Math.min(5, 1 + Math.round(elevation * 5)) : 0);

/* ---------------- Label placement ---------------- */

const overlaps = (a: Rect, b: Rect, pad = 0) =>
  a.x < b.x + b.w + pad && a.x + a.w + pad > b.x && a.y < b.y + b.h + pad && a.y + a.h + pad > b.y;

/**
 * Where to put the "You are here" label beside the marker: the first spot around it that
 * stays on the map and clear of the road, the checkpoint labels and anything else passed in.
 */
export function placeLabel(
  layout: Pick<JourneyLayout, "width" | "height" | "samples">,
  at: Pt,
  size: { w: number; h: number },
  obstacles: Rect[],
  points: Pt[] = []
): Rect {
  const { w, h } = size;
  const gap = 18;
  const offsets = [
    { x: gap, y: -h / 2 },
    { x: -gap - w, y: -h / 2 },
    { x: -w / 2, y: -gap - h },
    { x: -w / 2, y: gap },
    { x: gap - 4, y: -gap - h + 6 },
    { x: gap - 4, y: gap - 6 },
    { x: -gap - w + 4, y: -gap - h + 6 },
    { x: -gap - w + 4, y: gap - 6 },
    // Further out, for when a label beside the marker fills the whole width (narrow screens)
    ...[40, 80].flatMap((k) => [
      { x: gap - 4, y: -gap - h - k },
      { x: gap - 4, y: gap + k },
      { x: -w / 2, y: -gap - h - k },
      { x: -w / 2, y: gap + k },
    ]),
  ];
  const roadPts = layout.samples.pts.filter((_, i) => i % 3 === 0);
  let best: Rect | null = null;
  let bestHits = Infinity;
  for (const o of offsets) {
    const r = {
      x: clamp(at.x + o.x, 2, layout.width - w - 2),
      y: clamp(at.y + o.y, 2, layout.height - h - 2),
      w,
      h,
    };
    const box = { x: r.x - 4, y: r.y - 4, w: r.w + 8, h: r.h + 8 };
    const hits =
      obstacles.filter((ob) => overlaps(r, ob, 6)).length * 10 +
      [...roadPts, ...points].filter((p) => p.x >= box.x && p.x <= box.x + box.w && p.y >= box.y && p.y <= box.y + box.h).length +
      // Never cover the marker itself
      (at.x >= r.x - 10 && at.x <= r.x + r.w + 10 && at.y >= r.y - 10 && at.y <= r.y + r.h + 10 ? 100 : 0);
    if (hits < bestHits) {
      best = r;
      bestHits = hits;
      if (hits === 0) break;
    }
  }
  return best ?? { x: at.x + gap, y: at.y - h / 2, w, h };
}
