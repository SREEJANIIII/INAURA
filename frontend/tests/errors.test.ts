import { describe, it } from "node:test";
import assert from "node:assert";
import { friendlyError, statusOf } from "../src/lib/errors.ts";

/** The shape services/api.ts throws, without pulling the network code into the test */
const apiError = (status: number, detail: string | null = null) =>
  Object.assign(new Error(`API error ${status}`), { name: "ApiError", status, detail });

const FALLBACK = "Your project couldn't be saved.";

describe("friendlyError", () => {
  it("never shows the raw API message", () => {
    const e = apiError(422, null);
    e.message = 'API error 422 Unprocessable Entity: {"detail":[{"msg":"x"}]}';
    assert.strictEqual(friendlyError(e, FALLBACK), FALLBACK);
  });

  it("keeps a server reason written for people, as a sentence", () => {
    assert.strictEqual(friendlyError(apiError(400, "File too large. Max 10 MB"), FALLBACK), "File too large. Max 10 MB.");
    assert.strictEqual(friendlyError(apiError(422, "username contains invalid characters"), FALLBACK), "Username contains invalid characters.");
  });

  it("hides server reasons that are developer notes", () => {
    assert.strictEqual(
      friendlyError(apiError(400, "Roadmap tables not configured — run backend/supabase/022.sql"), FALLBACK),
      FALLBACK
    );
    assert.strictEqual(friendlyError(apiError(404, "relation \"skills\" does not exist"), FALLBACK), FALLBACK);
  });

  it("says what the status means where the status says it all", () => {
    assert.match(friendlyError(apiError(0), FALLBACK), /can't be reached/);
    assert.match(friendlyError(apiError(401, "Invalid token"), FALLBACK), /session has expired/);
    assert.match(friendlyError(apiError(413), FALLBACK), /10 MB/);
    assert.match(friendlyError(apiError(429), FALLBACK), /wait a moment/i);
  });

  it("uses the fallback for server failures and anything that isn't an API error", () => {
    assert.strictEqual(friendlyError(apiError(500, "Failed to update task: KeyError 'id'"), FALLBACK), FALLBACK);
    assert.strictEqual(friendlyError(new TypeError("x is undefined"), FALLBACK), FALLBACK);
    assert.strictEqual(friendlyError("boom", FALLBACK), FALLBACK);
  });

  it("reads the status back out", () => {
    assert.strictEqual(statusOf(apiError(404)), 404);
    assert.strictEqual(statusOf(new Error("API error 404")), null);
  });
});
