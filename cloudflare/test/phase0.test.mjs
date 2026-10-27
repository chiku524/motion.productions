/**
 * Phase 0 D1/KV read+write reduction, measured against a local Miniflare Worker (never Cloudflare).
 * Budgets are deliberately a little above the measured values so they catch regressions, not noise.
 */
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { createHarness, seedRegistry, clipPayload, chunkDiscoveries } from "./helpers/harness.mjs";

let h;
before(async () => {
  // Retention has its own budget test (d1Regrowth.test.mjs); the daily prune run is disabled here so these assert steady state.
  h = await createHarness({ bindings: { RETENTION_DISABLED: "1" }, seed: (ctx) => seedRegistry(ctx) });
});
after(async () => { await h?.dispose(); });

test("a 36-item chunk is ONE bounded batch: few D1 subrequests, no table scans, zero KV ops", async () => {
  const chunks = chunkDiscoveries(clipPayload(1, { jobId: "job-a" }), 36, 1);
  assert.ok(chunks.length <= 3, `one clip should be <=3 POSTs, got ${chunks.length}`);
  let posts = 0, statements = 0, rowsRead = 0;
  for (const ch of chunks) {
    const m = await h.measure(() => h.call("POST", "/api/knowledge/discoveries", ch));
    assert.ok([200, 201].includes(m.result.status), JSON.stringify(m.result.data));
    assert.ok(m.d1Requests <= 12, `D1 requests per POST: ${m.d1Requests}`);
    assert.equal(m.kv.put + m.kv.delete, 0, "no KV writes/deletes per POST");
    assert.equal(m.kv.get, 0, "no KV reads per POST");
    posts++; statements += m.statements; rowsRead += m.rowsRead;
  }
  assert.ok(rowsRead / posts < 2000, `rows read per POST must not scan static tables: ${rowsRead / posts}`);
  assert.ok(statements / posts <= 60, `statements per POST: ${statements / posts}`);
});

test("upsert counts add up across and within requests; blends are deduped", async () => {
  const key = "p0_unique_color_key";
  const item = { key, r: 7, g: 8, b: 9, name: "P0Test", source_prompt: "p" };
  let r = await h.call("POST", "/api/knowledge/discoveries", { static_colors: [item, item] });
  assert.ok([200, 201].includes(r.status), JSON.stringify(r.data));
  r = await h.call("POST", "/api/knowledge/discoveries", { static_colors: [item] });
  assert.ok([200, 201].includes(r.status));
  const row = await h.db.prepare("SELECT count, name FROM static_colors WHERE color_key = ?").bind(key).first();
  assert.equal(row.count, 3);
  const dup = await h.db.prepare("SELECT COUNT(*) AS n FROM static_colors WHERE color_key = ?").bind(key).first();
  assert.equal(dup.n, 1);
});

test("cached GETs and GETs right after a POST cost zero D1/KV (no per-post invalidation)", async () => {
  await h.call("GET", "/api/knowledge/for-creation?limit=100"); // warm
  const repeat = await h.measure(() => h.call("GET", "/api/knowledge/for-creation?limit=100"));
  assert.equal(repeat.result.status, 200);
  assert.equal(repeat.statements, 0);
  const afterPost = await h.measure(async () => {
    await h.call("POST", "/api/knowledge/discoveries", { static_colors: [{ key: "p0_after_post", r: 1, g: 2, b: 3 }] });
    return h.call("GET", "/api/knowledge/for-creation?limit=100");
  });
  assert.equal(afterPost.kv.put + afterPost.kv.delete, 0);
  // the GET after the POST must not rebuild (the only statements are the POST's own writes)
  const scans = afterPost.sqls.filter((s) => /ORDER BY count DESC/i.test(s.sql));
  assert.equal(scans.length, 0, "no registry scan after a POST");
  await h.call("GET", "/api/registries/coverage");
  const cov = await h.measure(() => h.call("GET", "/api/registries/coverage"));
  assert.equal(cov.statements, 0);
  assert.equal(cov.kv.put, 0);
});

test("/api/loop/state POST is throttled: second save inside 30 min does not touch KV", async () => {
  const body = { worker: "explorer", state: { run_count: 1, recent_prompts: ["a"] } };
  await h.call("POST", "/api/loop/state", body);
  const m = await h.measure(() => h.call("POST", "/api/loop/state", { ...body, state: { run_count: 2 } }));
  assert.equal(m.result.status, 200);
  assert.equal(m.result.data.throttled, true);
  assert.equal(m.kv.put + m.kv.delete, 0);
  assert.equal(m.statements, 0);
});

test("loop progress is a cached snapshot with no KV writes", async () => {
  await h.call("GET", "/api/loop/progress");
  const m = await h.measure(() => h.call("GET", "/api/loop/progress"));
  assert.equal(m.result.status, 200);
  assert.equal(m.statements, 0);
  assert.equal(m.kv.put, 0);
});

test("D1 limit error: GET /api/loop/status degrades to 200, POST discoveries returns 503 + Retry-After", async () => {
  await h.fail({ d1: "D1_ERROR: D1 DB exceeded its daily limit for rows read" });
  try {
    const st = await h.call("GET", "/api/loop/status");
    assert.equal(st.status, 200);
    assert.equal(st.data.degraded, true);
    const post = await h.call("POST", "/api/knowledge/discoveries", { static_colors: [{ key: "p0_limit", r: 1, g: 1, b: 1 }] });
    assert.equal(post.status, 503);
    assert.equal(post.headers.get("Retry-After"), "900");
    assert.equal(post.data.error, "free_tier_limit");
    // uncached read with no stale copy still answers 200 (degraded), not a 5xx
    const fc = await h.call("GET", "/api/knowledge/for-creation?limit=7&interp=3");
    assert.equal(fc.status, 200);
    assert.equal(fc.data.degraded, true);
  } finally {
    await h.fail({});
  }
});

test("KV limit error on loop state does not 5xx a GET path", async () => {
  await h.fail({ kv: "KV put() limit exceeded for the day." });
  try {
    const st = await h.call("GET", "/api/loop/status");
    assert.ok(st.status === 200, `status ${st.status}`);
  } finally {
    await h.fail({});
  }
});