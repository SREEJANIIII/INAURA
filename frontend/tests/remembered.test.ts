import { describe, it, beforeEach } from "node:test";
import assert from "node:assert";
import { forgetAll, remember, rememberByKey } from "../src/lib/remembered.ts";

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** A loader that counts how many times the server was actually asked. */
const counting = <T,>(value: (n: number) => T, delay = 0) => {
  const calls = { n: 0 };
  const load = async () => {
    calls.n += 1;
    const n = calls.n;
    if (delay) await wait(delay);
    return value(n);
  };
  return { calls, load };
};

let seq = 0;
const nextKey = () => `k${++seq}`;

describe("remembered page data", () => {
  beforeEach(() => forgetAll());

  it("asks the server once, then reuses what it has", async () => {
    const { calls, load } = counting((n) => `load ${n}`);
    const entry = remember(nextKey(), load);

    assert.equal(await entry.fetch(), "load 1");
    assert.equal(await entry.fetch(), "load 1");
    assert.equal(await entry.fetch(), "load 1");
    assert.equal(calls.n, 1, "revisiting a page should not re-ask the server");
  });

  it("shares one request between callers asking at the same time", async () => {
    const { calls, load } = counting((n) => `load ${n}`, 10);
    const entry = remember(nextKey(), load);

    const all = await Promise.all([entry.fetch(), entry.fetch(), entry.fetch()]);
    assert.deepEqual(all, ["load 1", "load 1", "load 1"]);
    assert.equal(calls.n, 1);
  });

  it("asks again when told to, e.g. after something was saved", async () => {
    const { calls, load } = counting((n) => `load ${n}`);
    const entry = remember(nextKey(), load);

    assert.equal(await entry.fetch(), "load 1");
    assert.equal(await entry.fetch(true), "load 2");
    assert.equal(calls.n, 2);
    assert.equal(entry.peek(), "load 2");
  });

  it("asks again once the copy is no longer current", async () => {
    const { calls, load } = counting((n) => `load ${n}`);
    const entry = remember(nextKey(), load, 20);

    assert.equal(await entry.fetch(), "load 1");
    await wait(40);
    assert.equal(await entry.fetch(), "load 2");
    assert.equal(calls.n, 2);
  });

  it("peek shows the remembered copy without asking the server", async () => {
    const { calls, load } = counting((n) => `load ${n}`);
    const entry = remember(nextKey(), load);

    assert.equal(entry.peek(), undefined);
    await entry.fetch();
    assert.equal(entry.peek(), "load 1");
    assert.equal(calls.n, 1);
  });

  it("does not remember a failed load, so the next visit retries", async () => {
    let n = 0;
    const key = nextKey();
    const entry = remember(key, async () => {
      n += 1;
      if (n === 1) throw new Error("offline");
      return `load ${n}`;
    });

    await assert.rejects(entry.fetch(), /offline/);
    assert.equal(entry.peek(), undefined);
    assert.equal(await entry.fetch(), "load 2");
  });

  it("forgetting clears every remembered copy, so the next user sees none of it", async () => {
    const { calls, load } = counting((n) => `load ${n}`);
    const entry = remember(nextKey(), load);

    await entry.fetch();
    forgetAll();
    assert.equal(entry.peek(), undefined);
    assert.equal(await entry.fetch(), "load 2");
    assert.equal(calls.n, 2);
  });

  it("notifies subscribers only when the remembered copy changes", async () => {
    const { load } = counting((n) => `load ${n}`);
    const entry = remember(nextKey(), load);
    let notices = 0;
    const { subscribeRemembered } = await import("../src/lib/remembered.ts");
    const off = subscribeRemembered(() => {
      notices += 1;
    });

    await entry.fetch();
    assert.equal(notices, 1);
    await entry.fetch(); // served from memory — nothing changed
    assert.equal(notices, 1);
    off();
  });

  describe("one copy per key", () => {
    it("keeps each key separate and reuses each one", async () => {
      const { calls, load } = counting(() => 0);
      const byRole = rememberByKey("role", async (role: string) => {
        await load();
        return `map for ${role}`;
      });

      assert.equal(await byRole("Full Stack Developer").fetch(), "map for Full Stack Developer");
      assert.equal(await byRole("Backend Developer").fetch(), "map for Backend Developer");
      assert.equal(await byRole("Full Stack Developer").fetch(), "map for Full Stack Developer");
      assert.equal(calls.n, 2, "each role is loaded once");
    });

    it("refreshAll re-asks for every key loaded so far", async () => {
      let n = 0;
      const byRole = rememberByKey("role2", async (role: string) => {
        n += 1;
        return `${role} v${n}`;
      });

      await byRole("A").fetch();
      await byRole("B").fetch();
      assert.equal(n, 2);

      byRole.refreshAll();
      await wait(5);
      assert.equal(n, 4);
      assert.equal(byRole("A").peek(), "A v3");
      assert.equal(byRole("B").peek(), "B v4");
    });

    it("refreshAll ignores a key that fails to reload", async () => {
      const byRole = rememberByKey("role3", async (role: string) => {
        if (role === "bad") throw new Error("offline");
        return role;
      });

      await byRole("good").fetch();
      await assert.rejects(byRole("bad").fetch(), /offline/);

      assert.doesNotThrow(() => byRole.refreshAll());
      await wait(5);
      assert.equal(byRole("good").peek(), "good");
    });
  });
});
