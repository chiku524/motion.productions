/**
 * D1 read-scan mitigations (free tier: 5M rows read / day). Local Miniflare only; never talks to Cloudflare.
 *
 * Regression for the incident where motion-productions-db read ~55.7B rows in a day: every POST /api/knowledge/name/take
 * probed learned_blends.name / static_colors.name / learned_colors.name (no index = full scan) up to 50 times.
 */
import { test, before, after, describe } from "node:test";
import assert from "node:assert/strict";
import { createHarness, seedRegistry, bundleModule } from "./helpers/harness.mjs";

const QUOTA = "D1_ERROR: D1 DB reached its daily limit for rows read (7500)";

describe("name take: name_reserve (PK) is the only uniqueness probe", () => {
  let h;
  before(async () => {
    h = await createHarness({ bindings: { RETENTION_DISABLED: "1" } });
    await seedRegistry(h, { learned_blends: 6000, static_colors: 1500 });
  });
  after(async () => { await h?.dispose(); });

  test("name/take issues no `WHERE name =` against learned_blends / static_colors / learned_colors", async () => {
    const m = await h.measure(async () => {
      const out = [];
      for (let i = 0; i < 25; i++) out.push(await h.call("POST", "/api/knowledge/name/take"));
      return out;
    });
    assert.ok(m.result.every((r) => r.status === 201 && typeof r.data.name === "string" && r.data.name.length > 0));
    const scans = m.sqls.filter((s) => /FROM\s+(learned_blends|static_colors|learned_colors)\b/i.test(s.sql) && /\bname\b/i.test(s.sql));
    assert.deepEqual(scans.map((s) => s.sql), [], "no name probe against an un-indexed table");
    assert.ok(m.sqls.some((s) => /FROM name_reserve WHERE name IN/i.test(s.sql)), "uses the name_reserve primary key");
    // 6000 learned_blends + 1500 static_colors rows exist. 25 takes = ~17 PK probes each (previously up to 50 full scans each).
    assert.ok(m.rowsRead < 25 * 40, `rows read ${m.rowsRead}`);
    assert.ok(m.sqls.filter((x) => /INSERT OR IGNORE INTO name_reserve/i.test(x.sql)).length === 25, "each taken name is persisted");
  });

  test("names are unique and persisted to name_reserve", async () => {
    const names = new Set();
    for (let i = 0; i < 60; i++) {
      const r = await h.call("POST", "/api/knowledge/name/take");
      assert.equal(r.status, 201);
      assert.ok(!names.has(r.data.name), `duplicate name ${r.data.name}`);
      names.add(r.data.name);
    }
    const stored = await h.db.prepare("SELECT COUNT(*) AS n FROM name_reserve").first();
    assert.ok(stored.n >= 60, `name_reserve rows ${stored.n}`);
    const first = [...names][0];
    assert.ok(await h.db.prepare("SELECT 1 FROM name_reserve WHERE name = ?").bind(first).first());
  });

});

describe("GET /api/jobs: cached, bounded, rate limited", () => {
  let h;
  before(async () => {
    h = await createHarness({ bindings: { RETENTION_DISABLED: "1" } });
    const stmts = [];
    for (let i = 0; i < 400; i++) {
      stmts.push(h.db.prepare("INSERT INTO jobs (id, prompt, status, r2_key, duration_seconds, workflow_type) VALUES (?, ?, ?, ?, ?, ?)")
        .bind(`job${i}`, `prompt ${i}`, i % 10 === 0 ? "pending" : "completed", i % 10 === 0 ? null : `videos/job${i}.mp4`, 4 + (i % 5), i % 20 === 0 ? "web" : null));
    }
    for (let i = 0; i < stmts.length; i += 80) await h.db.batch(stmts.slice(i, i + 80));
  });
  after(async () => { await h?.dispose(); });

  test("second identical request (even with a cache-buster) issues zero D1 statements and returns the same body", async () => {
    const ip = { "cf-connecting-ip": "198.51.100.1" };
    const a = await h.measure(() => h.call("GET", "/api/jobs?status=completed&limit=12", undefined, ip));
    assert.equal(a.result.status, 200);
    assert.equal(a.result.data.jobs.length, 12);
    assert.ok(a.statements >= 1);
    assert.ok(a.rowsRead <= 40, `bounded read: ${a.rowsRead} rows`);
    assert.equal(a.result.headers.get("x-cache"), "MISS");
    const b = await h.measure(() => h.call("GET", "/api/jobs?limit=12&status=completed&_=" + Date.now(), undefined, ip));
    assert.equal(b.statements, 0, "served from cache");
    assert.equal(b.result.headers.get("x-cache"), "HIT");
    assert.deepEqual(b.result.data, a.result.data);
  });

  test("pending list is cached and only returns web/unspecified-workflow jobs", async () => {
    const ip = { "cf-connecting-ip": "198.51.100.2" };
    const a = await h.call("GET", "/api/jobs?status=pending&limit=50", undefined, ip);
    assert.equal(a.status, 200);
    assert.ok(a.data.jobs.length > 0 && a.data.jobs.length <= 50);
    const b = await h.measure(() => h.call("GET", "/api/jobs?status=pending&limit=50", undefined, ip));
    assert.equal(b.statements, 0);
  });

  test("a cached copy is still served when D1 reports the daily read limit (degraded fallback)", async () => {
    const ip = { "cf-connecting-ip": "198.51.100.3" };
    const warm = await h.call("GET", "/api/jobs?status=completed&limit=7", undefined, ip);
    assert.equal(warm.status, 200);
    await h.fail({ d1: QUOTA });
    try {
      const r = await h.call("GET", "/api/jobs?status=completed&limit=7", undefined, ip);
      assert.equal(r.status, 200);
      assert.deepEqual(r.data, warm.data);
    } finally {
      await h.fail({});
    }
  });

  test("missing/invalid status is 400 before any D1 read; per-IP rate limit returns 429 + Retry-After", async () => {
    const ip = { "cf-connecting-ip": "198.51.100.4" };
    const bad = await h.measure(() => h.call("GET", "/api/jobs", undefined, ip));
    assert.equal(bad.result.status, 400);
    assert.equal(bad.statements, 0);
    let limited = null;
    for (let i = 0; i < 140 && !limited; i++) {
      const r = await h.call("GET", "/api/jobs?status=completed&limit=3", undefined, ip);
      if (r.status === 429) limited = r;
    }
    assert.ok(limited, "429 after the per-minute cap");
    assert.ok(Number(limited.headers.get("retry-after")) >= 1);
    const other = await h.call("GET", "/api/jobs?status=completed&limit=3", undefined, { "cf-connecting-ip": "198.51.100.5" });
    assert.equal(other.status, 200, "another client is unaffected");
  });
});

describe("rowid-ordered scans use the status/domain index and no temp sort", () => {
  let h;
  before(async () => { h = await createHarness({ bindings: { RETENTION_DISABLED: "1" } }); });
  after(async () => { await h?.dispose(); });

  const plan = async (sql, ...binds) => {
    const r = await h.db.prepare("EXPLAIN QUERY PLAN " + sql).bind(...binds).all();
    return (r.results || []).map((x) => x.detail).join(" | ");
  };

  test("interpretations done / jobs completed / learned_blends domain", async () => {
    const q1 = await plan("SELECT id, prompt, instruction_json, updated_at FROM interpretations WHERE status = 'done' AND instruction_json IS NOT NULL ORDER BY rowid DESC LIMIT ?", 100);
    assert.match(q1, /idx_interpretations_status/);
    assert.doesNotMatch(q1, /TEMP B-TREE/i);
    const q2 = await plan("SELECT id FROM jobs WHERE status = 'completed' AND r2_key IS NOT NULL ORDER BY rowid DESC LIMIT ?", 10);
    assert.match(q2, /idx_jobs_status/);
    assert.doesNotMatch(q2, /TEMP B-TREE/i);
    const q3 = await plan("SELECT output_json FROM learned_blends WHERE domain = 'camera' ORDER BY rowid DESC LIMIT ?", 40);
    assert.match(q3, /idx_learned_blends_domain/);
    assert.doesNotMatch(q3, /TEMP B-TREE/i);
    // The old shape for contrast: sorting by an un-indexed-with-status column needs a temp B-tree.
    const old = await plan("SELECT id FROM interpretations WHERE status = 'done' ORDER BY updated_at DESC LIMIT ?", 100);
    assert.ok(/TEMP B-TREE|idx_interpretations_updated_at/i.test(old), old);
  });
});

describe("readCache.cachedRows + rateLimit units", () => {
  let rc, rl, cleanups = [];
  before(async () => {
    for (const [rel, set] of [["src/readCache.ts", (m) => (rc = m)], ["src/rateLimit.ts", (m) => (rl = m)]]) {
      const b = await bundleModule(rel);
      set(b.mod);
      cleanups.push(b.cleanup);
    }
  });
  after(() => cleanups.forEach((c) => c()));

  test("cachedRows builds once inside the soft TTL and serves stale on a quota error", async () => {
    let builds = 0;
    const env = {};
    const a = await rc.cachedRows(env, "unit:a", 300, async () => ({ n: ++builds }));
    const b = await rc.cachedRows(env, "unit:a", 300, async () => ({ n: ++builds }));
    assert.deepEqual(a, b);
    assert.equal(builds, 1);
    await rc.cachedRows(env, "unit:b", 0, async () => "old");
    const stale = await rc.cachedRows(env, "unit:b", 0, async () => { throw new Error(QUOTA); });
    assert.equal(stale, "old");
  });

  test("recentDoneInterpretations is one rowid-ordered LIMIT query, then cached", async () => {
    const sqls = [];
    const env = { DB: { prepare: (sql) => ({ bind: (n) => ({ all: async () => { sqls.push([sql, n]); return { results: [{ id: "1", prompt: "p", instruction_json: "{}", updated_at: "t" }] }; } }) }) } };
    const x = await rc.recentDoneInterpretations(env, 25);
    const y = await rc.recentDoneInterpretations(env, 25);
    assert.deepEqual(x, y);
    assert.equal(sqls.length, 1);
    assert.match(sqls[0][0], /ORDER BY rowid DESC LIMIT \?/);
    assert.equal(sqls[0][1], 25);
  });

  test("hitRateLimit counts per client and window and fails open", async () => {
    rl.__resetRateLimit();
    const req = (ip) => new Request("http://x/y", { headers: { "cf-connecting-ip": ip } });
    const r1 = await rl.hitRateLimit(req("1.1.1.1"), "t", 2, 60);
    const r2 = await rl.hitRateLimit(req("1.1.1.1"), "t", 2, 60);
    const r3 = await rl.hitRateLimit(req("1.1.1.1"), "t", 2, 60);
    assert.deepEqual([r1.allowed, r2.allowed, r3.allowed], [true, true, false]);
    assert.ok(r3.retryAfterSec >= 1 && r3.retryAfterSec <= 60);
    assert.equal((await rl.hitRateLimit(req("2.2.2.2"), "t", 2, 60)).allowed, true);
  });
});
