import { describe, it } from "node:test";
import assert from "node:assert";
import { fitsWide, layoutJourney, lengthAt, placeLabel, pointAt, type JourneyLayout, type Rect } from "../src/components/roadmap/journeyLayout.ts";

const inside = (p: { x: number; y: number }, r: Rect, pad = 0) =>
  p.x >= r.x - pad && p.x <= r.x + r.w + pad && p.y >= r.y - pad && p.y <= r.y + r.h + pad;

const overlaps = (a: Rect, b: Rect) => a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;

/** No checkpoint label may sit on the road, or on another label */
function assertLabelsClear(layout: JourneyLayout) {
  layout.panels.forEach((panel, i) => {
    const onRoad = layout.samples.pts.filter((p) => inside(p, panel, 2));
    assert.equal(onRoad.length, 0, `label ${i + 1} covers the road at ${layout.width}px`);
    layout.panels.forEach((other, k) => {
      if (k > i) assert.ok(!overlaps(panel, other), `labels ${i + 1} and ${k + 1} overlap at ${layout.width}px`);
    });
  });
}

describe("journey layouts", () => {
  it("winds left to right on wide screens and down the page on narrow ones", () => {
    assert.equal(layoutJourney(1016, 6).mode, "wide");
    assert.equal(layoutJourney(760, 6).mode, "tall");
    assert.equal(layoutJourney(358, 6).mode, "tall");
    assert.ok(fitsWide(700, 3) === false && fitsWide(760, 3));
  });

  for (const [width, stages] of [
    [1016, 6],
    [1016, 3],
    [900, 4],
    [760, 6],
    [620, 5],
    [358, 6],
    [320, 1],
  ] as const) {
    it(`keeps labels off the road at ${width}px with ${stages} checkpoints`, () => {
      const layout = layoutJourney(width, stages);
      assert.equal(layout.nodes.length, stages);
      assert.equal(layout.panels.length, stages);
      assertLabelsClear(layout);
      for (const p of layout.panels) assert.ok(p.x >= 0 && p.x + p.w <= layout.width + 0.5, "label stays on the map");
    });
  }

  it("measures distance along the road, checkpoint by checkpoint", () => {
    const layout = layoutJourney(1016, 4);
    assert.equal(lengthAt(layout, 0), 0);
    for (let i = 1; i < layout.stops.length; i++) assert.ok(layout.stops[i] > layout.stops[i - 1]);
    assert.equal(lengthAt(layout, 2), layout.stops[2]);
    assert.ok(lengthAt(layout, 1.5) > layout.stops[1] && lengthAt(layout, 1.5) < layout.stops[2]);
    // The marker never runs past the final checkpoint onto the horizon
    assert.equal(lengthAt(layout, 99), layout.stops[4]);
    const atNode = pointAt(layout, layout.stops[3]);
    assert.ok(Math.hypot(atNode.x - layout.nodes[2].x, atNode.y - layout.nodes[2].y) < 1.5);
  });

  it("places the you-are-here label on the map, clear of the checkpoint labels", () => {
    for (const width of [1016, 700, 358]) {
      const layout = layoutJourney(width, 5);
      for (const position of [0, 0.5, 2.3, 5]) {
        const at = pointAt(layout, lengthAt(layout, position));
        const label = placeLabel(layout, at, { w: 130, h: 40 }, layout.panels);
        assert.ok(label.x >= 0 && label.y >= 0 && label.x + label.w <= layout.width && label.y + label.h <= layout.height);
        assert.ok(!layout.panels.some((p) => overlaps(label, p)), `label hits a checkpoint at ${width}px, position ${position}`);
      }
    }
  });
});
