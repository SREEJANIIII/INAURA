import { describe, it } from "node:test";
import assert from "node:assert";
import {
  validateSkillLevel,
  formatProficiencyPercent,
  formatEmploymentType,
  canManageMembers,
} from "../src/lib/employersModel.ts";

describe("validateSkillLevel", () => {
  it("accepts valid decimal levels between 0 and 1", () => {
    assert.deepStrictEqual(validateSkillLevel("0.75"), { valid: true, value: 0.75 });
    assert.deepStrictEqual(validateSkillLevel("0"), { valid: true, value: 0 });
    assert.deepStrictEqual(validateSkillLevel("1.0"), { valid: true, value: 1 });
  });

  it("rejects non-numeric inputs", () => {
    const res = validateSkillLevel("abc");
    assert.strictEqual(res.valid, false);
    assert.match(res.error || "", /valid number/);
  });

  it("rejects out of bounds levels", () => {
    assert.strictEqual(validateSkillLevel("-0.1").valid, false);
    assert.strictEqual(validateSkillLevel("1.1").valid, false);
  });
});

describe("formatProficiencyPercent", () => {
  it("formats decimal values to rounded percentages", () => {
    assert.strictEqual(formatProficiencyPercent(0.85), "85%");
    assert.strictEqual(formatProficiencyPercent(0.333), "33%");
    assert.strictEqual(formatProficiencyPercent(1.0), "100%");
    assert.strictEqual(formatProficiencyPercent(0.0), "0%");
  });

  it("handles null and undefined gracefully", () => {
    assert.strictEqual(formatProficiencyPercent(null), "N/A");
    assert.strictEqual(formatProficiencyPercent(undefined), "N/A");
  });
});

describe("formatEmploymentType", () => {
  it("formats snake_case types to Title Case", () => {
    assert.strictEqual(formatEmploymentType("full_time"), "Full Time");
    assert.strictEqual(formatEmploymentType("part_time"), "Part Time");
    assert.strictEqual(formatEmploymentType("internship"), "Internship");
  });

  it("handles empty or null values", () => {
    assert.strictEqual(formatEmploymentType(null), "Unspecified");
    assert.strictEqual(formatEmploymentType(""), "Unspecified");
  });
});

describe("canManageMembers", () => {
  it("returns true only for owner role", () => {
    assert.strictEqual(canManageMembers("owner"), true);
    assert.strictEqual(canManageMembers("member"), false);
    assert.strictEqual(canManageMembers(null), false);
  });
});
