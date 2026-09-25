import { describe, it } from "node:test";
import assert from "node:assert";
import { freshness, staleLabel } from "../src/lib/analysisFreshness.ts";

const ran = (over: Record<string, unknown> = {}) => ({
  target_role: "Full Stack Developer",
  evidence_changed: false,
  scoring_outdated: false,
  ...over,
});

describe("when the analysis still describes you", () => {
  it("says nothing when nothing has changed", () => {
    const f = freshness({ analysis: ran(), targetRole: "Full Stack Developer" });
    assert.equal(f.stale, false);
    assert.equal(f.message, null);
  });

  it("stays quiet when there is no analysis at all", () => {
    // Nothing to be out of date — the pages handle emptiness themselves
    assert.equal(freshness({ analysis: null, targetRole: "Backend Developer" }).stale, false);
    assert.equal(freshness({ analysis: undefined }).stale, false);
  });

  it("ignores casing and stray spacing in the role", () => {
    assert.equal(freshness({ analysis: ran(), targetRole: "  full stack developer " }).stale, false);
  });

  it("doesn't cry stale just because the current role isn't known yet", () => {
    assert.equal(freshness({ analysis: ran(), targetRole: null }).stale, false);
    assert.equal(freshness({ analysis: ran() }).stale, false);
  });

  it("treats an unrecorded evidence flag as fine, not as changed", () => {
    // Older runs didn't record a fingerprint, so the flag comes back null
    assert.equal(freshness({ analysis: ran({ evidence_changed: null }), targetRole: "Full Stack Developer" }).stale, false);
  });
});

describe("when it no longer describes you", () => {
  it("flags changed evidence and says so plainly", () => {
    const f = freshness({ analysis: ran({ evidence_changed: true }), targetRole: "Full Stack Developer" });
    assert.equal(f.stale, true);
    assert.equal(f.reason, "evidence");
    assert.match(f.message!, /evidence has changed/i);
    assert.ok(f.action);
  });

  it("flags a changed role, naming both", () => {
    const f = freshness({ analysis: ran(), targetRole: "Backend Developer" });
    assert.equal(f.reason, "role");
    assert.match(f.message!, /Full Stack Developer/);
    assert.match(f.message!, /Backend Developer/);
  });

  it("flags improved scoring", () => {
    const f = freshness({ analysis: ran({ scoring_outdated: true }), targetRole: "Full Stack Developer" });
    assert.equal(f.reason, "scoring");
  });

  it("puts a changed role above changed evidence, since it invalidates more", () => {
    const f = freshness({
      analysis: ran({ evidence_changed: true, scoring_outdated: true }),
      targetRole: "Backend Developer",
    });
    assert.equal(f.reason, "role");
  });

  it("puts changed evidence above improved scoring", () => {
    const f = freshness({
      analysis: ran({ evidence_changed: true, scoring_outdated: true }),
      targetRole: "Full Stack Developer",
    });
    assert.equal(f.reason, "evidence");
  });

  it("always offers something to do about it", () => {
    for (const over of [{ evidence_changed: true }, { scoring_outdated: true }]) {
      const f = freshness({ analysis: ran(over), targetRole: "Full Stack Developer" });
      assert.ok(f.action?.trim(), "a warning with no action is just a scold");
    }
  });
});

describe("the short label on the dot", () => {
  it("names the reason in a few words", () => {
    assert.equal(staleLabel("evidence"), "Your evidence changed");
    assert.equal(staleLabel("role"), "Your target role changed");
    assert.equal(staleLabel("scoring"), "Scoring improved");
  });

  it("is empty when nothing is wrong", () => {
    assert.equal(staleLabel(null), "");
  });
});
