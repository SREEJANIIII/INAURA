import { describe, it } from "node:test";
import assert from "node:assert";
import {
  getAllowedStudentTransitions,
  getAllowedEmployerTransitions,
  isTerminalStatus,
  formatStatusLabel,
  formatOutcomeLabel,
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
