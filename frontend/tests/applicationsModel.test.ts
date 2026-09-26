import { describe, it } from "node:test";
import assert from "node:assert";
import {
  getAllowedStudentTransitions,
  getAllowedEmployerTransitions,
  isTerminalStatus,
  formatStatusLabel,
  formatOutcomeLabel,
  deriveTimeline,
} from "../src/lib/applicationsModel.ts";

describe("getAllowedStudentTransitions", () => {
  it("allows student to apply or withdraw from saved", () => {
    assert.deepStrictEqual(getAllowedStudentTransitions("saved"), ["applied", "withdrawn"]);
  });

  it("allows student to withdraw from in-progress stages", () => {
    assert.deepStrictEqual(getAllowedStudentTransitions("applied"), ["withdrawn"]);
    assert.deepStrictEqual(getAllowedStudentTransitions("screening"), ["withdrawn"]);
    assert.deepStrictEqual(getAllowedStudentTransitions("interview"), ["withdrawn"]);
    assert.deepStrictEqual(getAllowedStudentTransitions("offer_received"), ["withdrawn"]);
  });

  it("prohibits student transitions from terminal states", () => {
    assert.deepStrictEqual(getAllowedStudentTransitions("selected"), []);
    assert.deepStrictEqual(getAllowedStudentTransitions("rejected"), []);
    assert.deepStrictEqual(getAllowedStudentTransitions("withdrawn"), []);
  });
});

describe("getAllowedEmployerTransitions", () => {
  it("allows employer to advance from applied to screening or rejected", () => {
    assert.deepStrictEqual(getAllowedEmployerTransitions("applied"), ["screening", "rejected"]);
  });

  it("allows employer to advance to interview or reject from screening", () => {
    assert.deepStrictEqual(getAllowedEmployerTransitions("screening"), ["interview", "rejected"]);
  });

  it("allows employer to offer, select, or reject from interview", () => {
    assert.deepStrictEqual(getAllowedEmployerTransitions("interview"), ["offer_received", "selected", "rejected"]);
  });

  it("prohibits employer transitions on saved and terminal applications", () => {
    assert.deepStrictEqual(getAllowedEmployerTransitions("saved"), []);
    assert.deepStrictEqual(getAllowedEmployerTransitions("selected"), []);
    assert.deepStrictEqual(getAllowedEmployerTransitions("rejected"), []);
  });
});

describe("isTerminalStatus", () => {
  it("recognizes selected, rejected, and withdrawn as terminal", () => {
    assert.strictEqual(isTerminalStatus("selected"), true);
    assert.strictEqual(isTerminalStatus("rejected"), true);
    assert.strictEqual(isTerminalStatus("withdrawn"), true);
    assert.strictEqual(isTerminalStatus("interview"), false);
    assert.strictEqual(isTerminalStatus("applied"), false);
  });
});

describe("formatStatusLabel & formatOutcomeLabel", () => {
  it("formats snake_case status to title case", () => {
    assert.strictEqual(formatStatusLabel("offer_received"), "Offer Received");
    assert.strictEqual(formatStatusLabel("applied"), "Applied");
  });

  it("formats outcome labels correctly", () => {
    assert.strictEqual(formatOutcomeLabel("declined_offer"), "Declined Offer");
    assert.strictEqual(formatOutcomeLabel("selected"), "Selected");
    assert.strictEqual(formatOutcomeLabel(null), "");
  });
});

describe("deriveTimeline", () => {
  const ev = (to_status: string, created_at: string) => ({ to_status, created_at });

  it("marks event-backed stages done with their dates, rest pending", () => {
    const stages = deriveTimeline(
      [ev("applied", "2026-09-24T00:00:00Z"), ev("screening", "2026-09-25T00:00:00Z")],
      null,
      false
    );
    assert.deepStrictEqual(
      stages.map((s) => s.key),
      ["applied", "screening", "interview", "offer_received", "selected", "joined"]
    );
    assert.strictEqual(stages[0].done, true);
    assert.strictEqual(stages[0].at, "2026-09-24T00:00:00Z");
    assert.strictEqual(stages[1].done, true);
    assert.strictEqual(stages[2].done, false);
    assert.strictEqual(stages[2].at, undefined);
    assert.strictEqual(stages[5].done, false);
  });

  it("marks joining done only from a joined placement", () => {
    const done = deriveTimeline([ev("applied", "2026-09-24T00:00:00Z")], "2026-09-30", true);
    assert.strictEqual(done[5].done, true);
    assert.strictEqual(done[5].at, "2026-09-30");
    const pending = deriveTimeline([ev("applied", "2026-09-24T00:00:00Z")], null, false);
    assert.strictEqual(pending[5].done, false);
  });

  it("never fabricates stages for empty event history", () => {
    const stages = deriveTimeline([], null, false);
    assert.ok(stages.every((s) => s.done === false));
    assert.ok(stages.every((s) => s.at === undefined));
  });
});
