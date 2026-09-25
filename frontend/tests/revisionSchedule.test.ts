import { describe, it } from "node:test";
import assert from "node:assert";
import {
  BOX_DAYS,
  boxAfter,
  DAY_MS,
  TOP_BOX,
  dayKey,
  grade,
  isDue,
  isNew,
  newProgress,
  streakFrom,
  whenBack,
} from "../src/lib/revision/schedule.ts";

/** A fixed mid-morning so day boundaries are unambiguous */
const T0 = new Date(2026, 8, 24, 10, 0, 0).getTime();
const midnightAfter = (days: number) => {
  const d = new Date(T0);
  d.setHours(0, 0, 0, 0);
  return d.getTime() + days * DAY_MS;
};

describe("when a card comes back", () => {
  it("sends a new card you knew away until tomorrow", () => {
    const p = grade(newProgress(), "got", T0);
    assert.equal(p.box, 1);
    assert.equal(p.dueAt, midnightAfter(BOX_DAYS[1]));
    assert.ok(p.dueAt > T0, "should not still be due today");
  });

  it("brings a card you missed straight back", () => {
    const known = grade(grade(newProgress(), "got", T0), "got", T0);
    const missed = grade(known, "again", T0);
    assert.equal(missed.box, 0, "drops to the bottom of the ladder");
    assert.equal(missed.dueAt, T0, "due right away, so it returns this session");
    assert.ok(isDue(missed, T0));
  });

  it("stretches the gap each time you get it right", () => {
    let p = newProgress();
    const gaps: number[] = [];
    for (let i = 0; i < 6; i++) {
      p = grade(p, "got", T0);
      gaps.push(Math.round((p.dueAt - midnightAfter(0)) / DAY_MS));
    }
    assert.deepEqual(gaps, [1, 3, 7, 16, 35, 35]);
  });

  it("never climbs past the top of the ladder", () => {
    let p = newProgress();
    for (let i = 0; i < 20; i++) p = grade(p, "got", T0);
    assert.equal(p.box, TOP_BOX);
  });


  it("keeps your place on the ladder when you almost had it", () => {
    let p = newProgress();
    for (let i = 0; i < 3; i++) p = grade(p, "got", T0);
    const before = p.box;
    const after = grade(p, "almost", T0);
    assert.equal(after.box, before, "no climb");
    assert.ok(after.dueAt > T0, "but no repeat this sitting either");
  });

  it("lifts a brand new card off the bottom when you almost had it", () => {
    const p = grade(newProgress(), "almost", T0);
    assert.equal(p.box, 1, "an almost should not leave a new card stuck at zero");
    assert.equal(p.dueAt, midnightAfter(1));
  });

  it("only counts a clean answer as right", () => {
    let p = newProgress();
    p = grade(p, "got", T0);
    p = grade(p, "almost", T0);
    p = grade(p, "again", T0);
    assert.equal(p.seen, 3);
    assert.equal(p.right, 1);
  });

  it("maps every answer to the box it should land in", () => {
    assert.equal(boxAfter(4, "again"), 0);
    assert.equal(boxAfter(4, "almost"), 4);
    assert.equal(boxAfter(4, "got"), 5);
    assert.equal(boxAfter(0, "almost"), 1);
    assert.equal(boxAfter(TOP_BOX, "got"), TOP_BOX);
  });

  it("counts how often you've seen it and how often you were right", () => {
    let p = newProgress();
    p = grade(p, "got", T0);
    p = grade(p, "again", T0);
    p = grade(p, "got", T0);
    assert.equal(p.seen, 3);
    assert.equal(p.right, 2);
  });

  it("treats a card as new until it has been answered once", () => {
    assert.ok(isNew(undefined));
    assert.ok(isNew(newProgress()));
    assert.ok(!isNew(grade(newProgress(), "got", T0)));
  });

  it("is not due before its time, and is due after", () => {
    const p = grade(newProgress(), "got", T0);
    assert.ok(!isDue(p, T0), "not due the same morning");
    assert.ok(!isDue(p, T0 + 6 * 60 * 60 * 1000), "not due later the same day");
    assert.ok(isDue(p, p.dueAt), "due once the day arrives");
    assert.ok(isDue(p, p.dueAt + DAY_MS), "still due if you skip a day");
  });

  it("says when a card is back in words, not timestamps", () => {
    assert.equal(whenBack({ ...newProgress(), dueAt: T0 }, T0), "later today");
    assert.equal(whenBack({ ...newProgress(), dueAt: T0 + DAY_MS }, T0), "tomorrow");
    assert.equal(whenBack({ ...newProgress(), dueAt: T0 + 3 * DAY_MS }, T0), "in 3 days");
    assert.equal(whenBack({ ...newProgress(), dueAt: T0 + 9 * DAY_MS }, T0), "in a week");
    assert.equal(whenBack({ ...newProgress(), dueAt: T0 + 35 * DAY_MS }, T0), "in a month");
  });
});

describe("study streak", () => {
  const day = (back: number) => dayKey(T0 - back * DAY_MS);

  it("counts consecutive days up to today", () => {
    assert.equal(streakFrom([day(0), day(1), day(2)], T0), 3);
  });

  it("survives today not being studied yet, if yesterday was", () => {
    assert.equal(streakFrom([day(1), day(2)], T0), 2);
  });

  it("breaks once a whole day is missed", () => {
    assert.equal(streakFrom([day(2), day(3)], T0), 0);
  });

  it("stops at the gap rather than counting everything", () => {
    assert.equal(streakFrom([day(0), day(1), day(3), day(4)], T0), 2);
  });

  it("is zero with nothing recorded", () => {
    assert.equal(streakFrom([], T0), 0);
  });

  it("ignores a day recorded twice", () => {
    assert.equal(streakFrom([day(0), day(0), day(1)], T0), 2);
  });
});
