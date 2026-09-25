import { describe, it } from "node:test";
import assert from "node:assert";
import { buildNotices } from "../src/components/layout/notices.ts";

const ids = (input: Parameters<typeof buildNotices>[0]) => buildNotices(input).map((n) => n.id);

describe("the bell's notices", () => {
  it("is empty when nothing needs doing", () => {
    assert.deepStrictEqual(ids({ analysis: { target_role: "Data Analyst" }, targetRole: "Data Analyst", analysedBefore: true }), []);
  });

  it("says when the analysis no longer matches the role or the evidence", () => {
    assert.deepStrictEqual(ids({ analysis: { target_role: "Data Analyst" }, targetRole: "Frontend Developer", analysedBefore: true }), ["stale"]);
    assert.deepStrictEqual(ids({ analysis: { target_role: "Data Analyst", evidence_changed: true }, analysedBefore: true }), ["stale"]);
  });

  it("shows a running re-run instead of calling the analysis stale", () => {
    const out = buildNotices({
      analysis: { target_role: "Data Analyst" },
      targetRole: "Frontend Developer",
      sync: { stage: "analysing", role: "Frontend Developer", message: null },
    });
    assert.deepStrictEqual(out.map((n) => n.id), ["sync"]);
    assert.match(out[0].title, /Frontend Developer/);
  });

  it("nudges a first analysis only when there's evidence to analyse", () => {
    assert.deepStrictEqual(ids({ analysis: null, analysedBefore: false, evidence: [] }), []);
    assert.deepStrictEqual(ids({ analysis: null, analysedBefore: false, projectCount: 1 }), ["first-run"]);
  });

  it("flags profiles that failed verification, but not excluded ones or files", () => {
    const out = ids({
      analysis: null,
      analysedBefore: true,
      evidence: [
        { id: "a", evidence_type: "github", verification_status: "failed" },
        { id: "b", evidence_type: "leetcode", verification_status: "failed", is_excluded: true },
        { id: "c", evidence_type: "resume", verification_status: "failed" },
      ],
    });
    assert.deepStrictEqual(out, ["verify-a"]);
  });

  it("counts revision cards that are due", () => {
    const [notice] = buildNotices({ analysedBefore: true, revisionDue: 3 });
    assert.strictEqual(notice.title, "3 revision cards are due");
    assert.strictEqual(buildNotices({ analysedBefore: true, revisionDue: 1 })[0].title, "1 revision card is due");
  });
});
