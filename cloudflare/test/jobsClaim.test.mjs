/**
 * GET /api/jobs?status=pending claim path (incident: 4.19M of ~4.4M D1 rows read in 6 h by one query that walked ~31k
 * loop-owned pending jobs on every cache miss). Local Miniflare only; never talks to Cloudflare.
 */
import { test, describe, before, after } from "node:test";
import assert from "node:assert/strict";
import { createHarness } from "./helpers/harness.mjs";

const QUOTA = "D1_ERROR: D1 DB reached its daily limit for rows read (7500)";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let ipSeq = 0;
const nextIp = () => ({ "cf-connecting-ip": `203.0.113.${(ipSeq++ % 250) + 1}` });

async function seedJobs(h, { junk = 0, junkType = "explorer", web = 0, nullType = 0 }) {
  const ins = "INSERT INTO jobs (id, prompt, status, workflow_type) VALUES (?, ?, 'pending', ?)";
  const stmts = [];
  for (let i = 0; i < junk; i++) stmts.push(h.db.prepare(ins).bind(`junk${i}`, `loop prompt ${i}`, junkType));
  for (let i = 0; i < web; i++) stmts.push(h.db.prepare(ins).bind(`abc${i}`, `web prompt ${i}`, "web"));
  for (let i = 0; i < nullType; i++) stmts.push(h.db.prepare(ins).bind(`null${i}`, `null prompt ${i}`, null));
  for (let i = 0; i < stmts.length; i += 80) await h.db.batch(stmts.slice(i, i + 80));
}

const poll = (h, limit = 5) => h.call("GET", `/api/jobs?status=pending&limit=${limit}`, undefined, nextIp());

describe("jobs claim: backlog of non-web pending jobs does not turn every poll into a full scan", () => {
  let h;
  before(async () => {
    h = await createHarness({ bindings: { RETENTION_DISABLED: "1" } });
    await seedJobs(h, { junk: 1500, web: 2 });
  });
  after(async () => { await h?.dispose(); });

  test("first poll walks the backlog once and finds the web jobs, in oldest-first order, never a loop job", async () => {
    const m = await h.measure(() => poll(h));
    assert.equal(m.result.status, 200);
    assert.deepEqual(m.result.data.jobs.map((j) => j.id), ["abc0", "abc1"]);
    assert.equal(m.result.data.scan_complete, true);
    assert.equal(m.result.data.poll_after_sec, 0);
    assert.ok(m.rowsRead >= 1500 && m.rowsRead <= 1800, `one-time catch-up read ${m.rowsRead} rows`);
  });

  test("a cache miss after the backlog was walked starts at the cursor: ~one window, not 1500 rows", async () => {
    const created = await h.call("POST", "/api/jobs", { prompt: "fresh web job", workflow_type: "web" });
    assert.equal(created.status, 201);
    const m = await h.measure(() => poll(h));
    assert.deepEqual(m.result.data.jobs.map((j) => j.id), ["abc0", "abc1", created.data.id]);
    assert.ok(m.rowsRead <= 200, `steady-state rows read ${m.rowsRead} (was ~1500+ per miss before the cursor)`);
    assert.equal(m.sqls.length, 1);
  });

  test("the same poll again is served from cache: zero D1 statements", async () => {
    const m = await h.measure(() => poll(h));
    assert.equal(m.statements, 0);
    assert.equal(m.result.data.jobs.length, 3);
    assert.equal(m.result.headers.get("x-cache"), "HIT");
  });

  test("loop-owned pending jobs added later are skipped and never starve web jobs behind them", async () => {
    await seedJobs(h, { junk: 0 });
    await h.db.prepare("INSERT INTO jobs (id, prompt, status, workflow_type) VALUES ('late-loop', 'x', 'pending', 'main')").run();
    const created = await h.call("POST", "/api/jobs", { prompt: "web after loop job" }); // null workflow_type = web
    assert.equal(created.status, 201);
    const r = await poll(h, 10);
    const ids = r.data.jobs.map((j) => j.id);
    assert.ok(ids.includes(created.data.id) && !ids.includes("late-loop") && !ids.some((i) => i.startsWith("junk")));
  });
});

describe("jobs claim: negative cache, incomplete scans and degraded (D1 quota) behaviour", () => {
  let h;
  before(async () => {
    h = await createHarness({ bindings: { RETENTION_DISABLED: "1" } });
    await seedJobs(h, { junk: 2500 }); // > 20 windows x 100 rows: one request cannot reach the end of the queue
  });
  after(async () => { await h?.dispose(); });

  test("a scan that ran out of windows is bounded, reports scan_complete=false and is only cached for seconds", async () => {
    const m = await h.measure(() => poll(h));
    assert.equal(m.result.status, 200);
    assert.deepEqual(m.result.data.jobs, []);
    assert.equal(m.result.data.scan_complete, false);
    assert.ok(m.result.data.poll_after_sec >= 1 && m.result.data.poll_after_sec <= 5);
    assert.ok(m.sqls.length <= 20, `${m.sqls.length} window queries`);
    assert.ok(m.rowsRead <= 2100, `bounded: ${m.rowsRead} rows`);
  });

  test("D1 daily-limit error after the short TTL: stale answer, HTTP 200, X-Degraded and a long poll_after_sec", async () => {
    await sleep(3300); // incomplete-scan TTL is 3 s
    await h.fail({ d1: QUOTA });
    try {
      const r = await poll(h);
      assert.equal(r.status, 200);
      assert.equal(r.headers.get("x-degraded"), "d1-quota");
      assert.equal(r.headers.get("x-cache"), "STALE");
      assert.equal(r.data.degraded, true);
      assert.ok(r.data.poll_after_sec >= 300);
      assert.ok(Number(r.headers.get("retry-after")) >= 300);
      assert.deepEqual(r.data.jobs, []);
    } finally {
      await h.fail({});
    }
  });

  test("the next scan continues from the cursor and proves the queue empty; empty result is negative-cached for 60 s", async () => {
    const m = await h.measure(() => poll(h));
    assert.equal(m.result.data.scan_complete, true);
    assert.deepEqual(m.result.data.jobs, []);
    assert.equal(m.result.data.poll_after_sec, 60);
    assert.ok(m.rowsRead <= 700, `only the unscanned tail was read: ${m.rowsRead}`);
    const again = await h.measure(async () => { for (let i = 0; i < 10; i++) await poll(h); });
    assert.equal(again.statements, 0, "10 more empty polls cost no D1 statements");
    assert.equal(again.rowsRead, 0);
  });

  test("a new web job invalidates the negative cache immediately (no 60 s wait) and is found past the cursor", async () => {
    const created = await h.call("POST", "/api/jobs", { prompt: "hello", workflow_type: "web" });
    assert.equal(created.status, 201);
    const m = await h.measure(() => poll(h));
    assert.deepEqual(m.result.data.jobs.map((j) => j.id), [created.data.id]);
    assert.ok(m.rowsRead <= 200, `${m.rowsRead} rows`);
  });

  test("a loop-typed job does not invalidate the cache (only web/NULL jobs do)", async () => {
    const warm = await poll(h);
    assert.equal(warm.status, 200);
    await h.call("POST", "/api/jobs", { prompt: "loop job", workflow_type: "explorer" });
    const m = await h.measure(() => poll(h));
    assert.equal(m.statements, 0);
  });
});

describe("jobs claim: finishing a job is atomic (no double claim)", () => {
  let h;
  before(async () => {
    h = await createHarness({ bindings: { RETENTION_DISABLED: "1" } });
    await seedJobs(h, { junk: 0, web: 3 });
  });
  after(async () => { await h?.dispose(); });

  test("two concurrent /complete calls: exactly one wins, the other gets 400 and the row is written once", async () => {
    const res = await Promise.all([
      h.call("POST", "/api/jobs/abc0/complete"),
      h.call("POST", "/api/jobs/abc0/complete"),
    ]);
    const codes = res.map((r) => r.status).sort();
    assert.deepEqual(codes, [200, 400]);
    const row = await h.db.prepare("SELECT status, r2_key FROM jobs WHERE id = 'abc0'").first();
    assert.equal(row.status, "completed");
  });

  test("the guarded UPDATE only matches pending rows", async () => {
    const m = await h.measure(() => h.call("POST", "/api/jobs/abc0/complete"));
    assert.equal(m.result.status, 400);
    assert.ok(!m.sqls.some((s) => /^UPDATE jobs/i.test(s.sql) && s.rows_written > 0));
    const ok = await h.measure(() => h.call("POST", "/api/jobs/abc1/complete"));
    assert.equal(ok.result.status, 200);
    assert.ok(ok.sqls.some((s) => /UPDATE jobs SET status = 'completed'.*AND status = 'pending'/i.test(s.sql)));
  });
});

describe("jobs claim: window query plan", () => {
  let h;
  before(async () => { h = await createHarness({ bindings: { RETENTION_DISABLED: "1" } }); });
  after(async () => { await h?.dispose(); });

  const plan = async (sql, ...binds) => {
    const r = await h.db.prepare("EXPLAIN QUERY PLAN " + sql).bind(...binds).all();
    return (r.results || []).map((x) => x.detail).join(" | ");
  };
  const WINDOW =
    "SELECT rowid AS rid, CASE WHEN workflow_type IS NULL OR workflow_type = 'web' THEN id END AS id FROM jobs WHERE status = 'pending' AND rowid > ? ORDER BY rowid ASC LIMIT ?";

  test("range-seeks idx_jobs_status on (status, rowid) with no temp sort", async () => {
    const p = await plan(WINDOW, 0, 100);
    assert.match(p, /USING (COVERING )?INDEX idx_jobs_status \(status=\? AND rowid>\?\)/);
    assert.ok(!/TEMP B-TREE/i.test(p), p);
  });

  test("optional partial index (NOT applied remotely) is used by the exact-match query shape", async () => {
    await h.db.prepare(
      "CREATE INDEX IF NOT EXISTS idx_jobs_pending_web ON jobs(status) WHERE status = 'pending' AND (workflow_type IS NULL OR workflow_type = 'web')",
    ).run();
    const p = await plan(
      "SELECT rowid AS rid, id FROM jobs WHERE status = 'pending' AND (workflow_type IS NULL OR workflow_type = 'web') AND rowid > ? ORDER BY rowid ASC LIMIT ?",
      0, 100,
    );
    assert.match(p, /idx_jobs_pending_web/);
    // The loose window query (status = 'pending' only) cannot use it: it does not imply the partial WHERE.
    assert.ok(!/idx_jobs_pending_web/.test(await plan(WINDOW, 0, 100)));
  });
});

describe("jobs claim: JOBS_PARTIAL_INDEX=1 (only after migrations_pending/0102 is applied) reads just claimable rows", () => {
  let h;
  before(async () => {
    h = await createHarness({ bindings: { RETENTION_DISABLED: "1", JOBS_PARTIAL_INDEX: "1" } });
    await h.db.prepare(
      "CREATE INDEX IF NOT EXISTS idx_jobs_pending_web ON jobs(status) WHERE status = 'pending' AND (workflow_type IS NULL OR workflow_type = 'web')",
    ).run();
    await seedJobs(h, { junk: 1500, web: 2 });
  });
  after(async () => { await h?.dispose(); });

  test("1500 loop-owned pending rows cost nothing: one query, ~2 rows read", async () => {
    const m = await h.measure(() => poll(h));
    assert.deepEqual(m.result.data.jobs.map((j) => j.id), ["abc0", "abc1"]);
    assert.equal(m.sqls.length, 1);
    assert.ok(m.rowsRead <= 10, `rows read ${m.rowsRead}`);
  });

  test("empty queue: scan_complete and a 60 s poll hint", async () => {
    await h.call("POST", "/api/jobs/abc0/complete");
    await h.call("POST", "/api/jobs/abc1/complete");
    await h.call("POST", "/api/jobs", { prompt: "poke" }); // invalidates; consume it
    await h.db.prepare("DELETE FROM jobs WHERE workflow_type IS NULL").run();
    await h.call("POST", "/api/jobs", { prompt: "poke2", workflow_type: "web" }); // invalidate again
    await h.db.prepare("DELETE FROM jobs WHERE workflow_type = 'web'").run();
    const r = await poll(h);
    assert.deepEqual(r.data.jobs, []);
    assert.equal(r.data.scan_complete, true);
    assert.equal(r.data.poll_after_sec, 60);
  });
});
