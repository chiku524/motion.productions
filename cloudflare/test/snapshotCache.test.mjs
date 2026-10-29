import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { bundleModule } from "./helpers/harness.mjs";

let snap, gate, limits, cleanups = [];
before(async () => {
  for (const [rel, set] of [["src/snapshotCache.ts", (m) => (snap = m)], ["src/kvGate.ts", (m) => (gate = m)], ["src/limits.ts", (m) => (limits = m)]]) {
    const b = await bundleModule(rel);
    set(b.mod);
    cleanups.push(b.cleanup);
  }
});
after(() => cleanups.forEach((c) => c()));

function fakeKv() {
  const store = new Map();
  const k = { puts: 0, gets: 0, store };
  return Object.assign(k, {
    async get(key) { k.gets++; return store.get(key) ?? null; },
    async put(key, v) { k.puts++; store.set(key, v); },
  });
}

test("getSnapshot serves from memory inside the soft TTL (one build, zero extra KV writes)", async () => {
  snap.__resetSnapshotMemory();
  const kv = fakeKv();
  let builds = 0;
  const build = async () => ({ n: ++builds });
  const o = { softTtlSec: 3600, kvPersistSec: 21600 };
  const a = await snap.getSnapshot({ MOTION_KV: kv }, "t1", o, build);
  const b = await snap.getSnapshot({ MOTION_KV: kv }, "t1", o, build);
  assert.equal(a.source, "built");
  assert.equal(b.source, "memory");
  assert.equal(builds, 1);
  assert.equal(kv.puts, 1, "exactly one durable KV persist for the first build");
});

test("getSnapshot is single-flight for concurrent callers", async () => {
  snap.__resetSnapshotMemory();
  let builds = 0;
  const build = async () => { builds++; await new Promise((r) => setTimeout(r, 20)); return builds; };
  const res = await Promise.all([1, 2, 3, 4, 5].map(() => snap.getSnapshot({}, "t2", { softTtlSec: 60 }, build)));
  assert.equal(builds, 1);
  assert.ok(res.every((r) => r.value === 1));
});

test("getSnapshot serves stale + degraded when the rebuild hits a free-tier limit", async () => {
  snap.__resetSnapshotMemory();
  const env = {};
  await snap.getSnapshot(env, "t3", { softTtlSec: 0, hardTtlSec: 3600 }, async () => "old");
  const r = await snap.getSnapshot(env, "t3", { softTtlSec: 0, hardTtlSec: 3600 }, async () => {
    throw new Error("D1_ERROR: D1 DB reached its daily limit for rows read");
  });
  assert.equal(r.value, "old");
  assert.equal(r.stale, true);
  assert.equal(r.degraded, true);
});

test("getSnapshot rethrows when there is no stale copy", async () => {
  snap.__resetSnapshotMemory();
  await assert.rejects(snap.getSnapshot({}, "t4", { softTtlSec: 0 }, async () => { throw new Error("boom"); }), /boom/);
});

test("fresh=1 bypass is rate limited", async () => {
  snap.__resetSnapshotMemory();
  let builds = 0;
  const build = async () => ++builds;
  const o = { softTtlSec: 3600, bypass: true, bypassMinIntervalSec: 300 };
  await snap.getSnapshot({}, "t5", o, build); // first bypass honored
  await snap.getSnapshot({}, "t5", o, build); // second inside the interval is ignored
  await snap.getSnapshot({}, "t5", o, build);
  assert.equal(builds, 1);
});

test("kvGate lets one write through per interval", async () => {
  gate.__resetKvGate();
  assert.equal(await gate.shouldWrite("k", 1800), true);
  await gate.markWritten("k", 1800);
  assert.equal(await gate.shouldWrite("k", 1800), false);
  assert.equal(await gate.shouldWrite("other", 1800), true);
});

test("isFreeTierLimitError recognises Cloudflare D1/KV limit messages", () => {
  for (const m of [
    "D1_ERROR: D1 DB exceeded its daily limit",
    "KV put() limit exceeded for the day.",
    "Too many requests",
    "Error 429: rows read limit exceeded",
  ]) assert.equal(limits.isFreeTierLimitError(new Error(m)), true, m);
  assert.equal(limits.isFreeTierLimitError(new Error("UNIQUE constraint failed")), false);
  assert.equal(limits.isFreeTierLimitError(null), false);
});

test("limitResponse: reads degrade to 200, writes get 503 + Retry-After", async () => {
  const g = limits.limitResponse("GET", { prompts: [] });
  assert.equal(g.status, 200);
  assert.equal(g.headers.get("X-Degraded"), "free_tier_limit");
  const body = await g.json();
  assert.equal(body.degraded, true);
  assert.deepEqual(body.prompts, []);
  const p = limits.limitResponse("POST");
  assert.equal(p.status, 503);
  assert.equal(p.headers.get("Retry-After"), "900");
});
// ---- stale-while-revalidate / stampede protection (mission stats rebuilt ~36x/hour) ----

test("SWR: after the soft TTL exactly one caller rebuilds, the rest are served stale", async () => {
  snap.__resetSnapshotMemory();
  let builds = 0;
  const build = async () => { builds++; await new Promise((r) => setTimeout(r, 10)); return { n: builds }; };
  const o = { softTtlSec: 0, swrSec: 3600 };
  const first = await snap.getSnapshot({}, "swr1", o, build);
  assert.equal(first.source, "built");
  assert.equal(builds, 1);
  // The soft TTL (0) has expired for everyone now; 10 callers arrive together.
  const res = await Promise.all(Array.from({ length: 10 }, () => snap.getSnapshot({}, "swr1", o, build)));
  assert.equal(builds, 2, "one refresh, not one per caller");
  assert.ok(res.some((r) => r.stale), "other callers were served the stale copy");
  // The refresh lock is held for 120 s: the next callers do not rebuild again.
  const later = await snap.getSnapshot({}, "swr1", o, build);
  assert.equal(builds, 2);
  assert.ok(later.value.n >= 1);
});

test("SWR: a second isolate (empty memory) does not rebuild while the refresh lock is held", async () => {
  snap.__resetSnapshotMemory();
  const kv = fakeKv();
  let builds = 0;
  const build = async () => ({ n: ++builds });
  const o = { softTtlSec: 0, swrSec: 3600, kvPersistSec: 1 };
  await snap.getSnapshot({ MOTION_KV: kv }, "swr2", o, build); // builds + persists to KV
  assert.equal(builds, 1);
  await snap.getSnapshot({ MOTION_KV: kv }, "swr2", o, build); // this isolate takes the refresh lock
  assert.equal(builds, 2);
  snap.__resetSnapshotMemory(); // simulate a cold isolate in the same colo
  const cold = await snap.getSnapshot({ MOTION_KV: kv }, "swr2", o, build);
  assert.equal(cold.source, "kv");
  assert.equal(cold.stale, true);
  assert.equal(builds, 2, "cold isolate served the KV copy instead of running the aggregate again");
});

test("SWR peek: request paths inside the window never rebuild; outside it they do", async () => {
  snap.__resetSnapshotMemory();
  let builds = 0;
  const build = async () => ({ n: ++builds });
  await snap.getSnapshot({}, "swr3", { softTtlSec: 0, swrSec: 3600 }, build);
  for (let i = 0; i < 5; i++) {
    const r = await snap.getSnapshot({}, "swr3", { softTtlSec: 0, swrSec: 3600, peek: true }, build);
    assert.equal(r.stale, true);
  }
  assert.equal(builds, 1, "peek never started a rebuild");
  // Without an SWR window a peek caller falls back to a normal blocking rebuild.
  await snap.getSnapshot({}, "swr3", { softTtlSec: 0, peek: true }, build);
  assert.equal(builds, 2);
});

test("SWR: past soft+swr the rebuild is blocking and the failure still serves stale", async () => {
  snap.__resetSnapshotMemory();
  const realNow = Date.now;
  let t = 1_000_000_000_000;
  Date.now = () => t;
  try {
    await snap.getSnapshot({}, "swr4", { softTtlSec: 10, swrSec: 100, hardTtlSec: 100000 }, async () => "v1");
    t += 50_000; // inside the SWR window: stale, refresh is allowed
    t += 200_000; // beyond soft+swr
    const r = await snap.getSnapshot({}, "swr4", { softTtlSec: 10, swrSec: 100, hardTtlSec: 100000 }, async () => "v2");
    assert.equal(r.value, "v2");
    assert.equal(r.source, "built");
    t += 500_000;
    const e = await snap.getSnapshot({}, "swr4", { softTtlSec: 10, swrSec: 100, hardTtlSec: 100000 }, async () => { throw new Error("D1 daily limit"); });
    assert.equal(e.value, "v2");
    assert.equal(e.degraded, true);
  } finally {
    Date.now = realNow;
  }
});
