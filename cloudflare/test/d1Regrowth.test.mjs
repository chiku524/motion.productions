/**
 * D1 regrowth prevention (free tier: 500 MB per database): blend dedupe, slim learning_runs, opportunistic retention,
 * and the DB-full guard. Local Miniflare only; never talks to Cloudflare.
 */
import { test, before, after, describe } from "node:test";
import assert from "node:assert/strict";
import { createHarness, clipPayload, bundleModule } from "./helpers/harness.mjs";

const ok = (r) => [200, 201].includes(r.status);

describe("blend dedupe + slim learning_runs (retention off)", () => {
  let h;
  before(async () => { h = await createHarness({ bindings: { RETENTION_DISABLED: "1" } }); });
  after(async () => { await h?.dispose(); });

  test("the same clip posted twice writes ~0 blend rows the second time", async () => {
    const payload = clipPayload(7);
    const first = await h.measure(() => h.call("POST", "/api/knowledge/discoveries", payload));
    assert.ok(ok(first.result), JSON.stringify(first.result.data));
    const n1 = (await h.db.prepare("SELECT COUNT(*) AS n FROM learned_blends").first()).n;
    assert.equal(n1, 10, "10 distinct blends stored once");
    const blendWrites1 = first.sqls.filter((s) => /INTO learned_blends/i.test(s.sql)).reduce((a, s) => a + s.rows_written, 0);
    assert.ok(blendWrites1 >= 10);

    // Same blends again, with different (generated) names: content hash is the identity, not the name.
    const again = { ...payload, blends: payload.blends.map((b) => ({ ...b, name: b.name + " renamed" })) };
    const second = await h.measure(() => h.call("POST", "/api/knowledge/discoveries", again));
    assert.ok(ok(second.result));
    const n2 = (await h.db.prepare("SELECT COUNT(*) AS n FROM learned_blends").first()).n;
    assert.equal(n2, n1, "no new blend rows");
    const blendWrites2 = second.sqls.filter((s) => /INTO learned_blends/i.test(s.sql)).reduce((a, s) => a + s.rows_written, 0);
    assert.equal(blendWrites2, 0, "conflicting INSERT OR IGNORE writes nothing (no row, no index entries)");
    assert.equal(second.result.data.new_blends, 0);
  });

  test("blend id is deterministic and key-order / rounding insensitive", async () => {
    const { mod, cleanup } = await bundleModule("src/blendId.ts");
    try {
      const a = await mod.blendId("Color ", { x: 1.00001, y: { b: 2, a: 1 } });
      const b = await mod.blendId("color", { y: { a: 1, b: 2 }, x: 1 });
      const c = await mod.blendId("motion", { y: { a: 1, b: 2 }, x: 1 });
      assert.equal(a, b);
      assert.notEqual(a, c);
      assert.match(a, /^bl_[0-9a-f]{32}$/);
    } finally { cleanup(); }
  });

  test("POST /api/learning stores only the fields the stats aggregate reads (store_full opts out)", async () => {
    const big = { motion_level: 0.42, mean_brightness: 0.5, mean_contrast: 0.3, motion_per_frame: Array.from({ length: 2000 }, (_, i) => i / 7), palette_stats: { junk: "x".repeat(5000) } };
    const spec = { palette_name: "sunset", motion_type: "pan", huge: "y".repeat(5000), nested: { a: [1, 2, 3] } };
    let r = await h.call("POST", "/api/learning", { prompt: "slim me", spec, analysis: big });
    assert.ok(ok(r), JSON.stringify(r.data));
    r = await h.call("POST", "/api/learning", { prompt: "keep me", spec, analysis: big, store_full: true });
    assert.ok(ok(r));
    const slim = await h.db.prepare("SELECT spec_json, analysis_json FROM learning_runs WHERE prompt = 'slim me'").first();
    const full = await h.db.prepare("SELECT spec_json, analysis_json FROM learning_runs WHERE prompt = 'keep me'").first();
    assert.ok(slim.analysis_json.length < 120, slim.analysis_json);
    assert.ok(slim.spec_json.length < 120, slim.spec_json);
    assert.deepEqual(JSON.parse(slim.analysis_json), { motion_level: 0.42, mean_brightness: 0.5, mean_contrast: 0.3 });
    assert.equal(JSON.parse(slim.spec_json).palette_name, "sunset");
    assert.ok(full.analysis_json.length > 10_000);
    const stats = await h.call("GET", "/api/learning/stats");
    assert.equal(stats.status, 200);
    assert.ok(stats.data.total_runs >= 1);
  });
});

describe("opportunistic retention", () => {
  let h;
  const old = "2020-01-01 00:00:00";
  const count = async (t, where = "1=1") => (await h.db.prepare("SELECT COUNT(*) AS n FROM " + t + " WHERE " + where).first()).n;
  const post = (prompt) => h.measure(() => h.call("POST", "/api/learning", { prompt, spec: {}, analysis: {} }));
  const deletes = (m, table) => m.sqls.filter((s) => new RegExp("^DELETE FROM " + table, "i").test(s.sql.trim()));

  before(async () => {
    h = await createHarness({ bindings: { RETENTION_CHECK_INTERVAL_SEC: "0", RETENTION_BATCH_ROWS: "100", RETENTION_MAX_BATCHES: "2", RETENTION_DAYS: "3" } });
    const stmts = [];
    const job = (id, status, r2, created) => stmts.push(created
      ? h.db.prepare("INSERT INTO jobs (id, prompt, status, r2_key, created_at, updated_at) VALUES (?, 'p', ?, ?, ?, ?)").bind(id, status, r2, created, created)
      : h.db.prepare("INSERT INTO jobs (id, prompt, status, r2_key) VALUES (?, 'p', ?, ?)").bind(id, status, r2));
    for (let i = 0; i < 300; i++) {
      job("oldjob" + i, "completed", "skipped:no-upload", old);
      stmts.push(h.db.prepare("INSERT INTO learning_runs (id, job_id, prompt, spec_json, analysis_json, created_at) VALUES (?, ?, 'p', '{}', '{}', ?)").bind("oldlr" + i, "oldjob" + i, old));
    }
    job("lonely_skip", "completed", "skipped:no-upload", "2019-01-01 00:00:00");
    job("lonely_null", "failed", null, "2019-01-01 00:00:00");
    job("keep_r2", "completed", "jobs/keep_r2/video.mp4", old);
    job("keep_pending", "pending", null, old);
    job("keep_young", "completed", "skipped:no-upload", null);
    stmts.push(h.db.prepare("INSERT INTO learning_runs (id, job_id, prompt, spec_json, analysis_json) VALUES ('younglr', 'keep_young', 'p', '{}', '{}')"));
    for (let i = 0; i < stmts.length; i += 80) await h.db.batch(stmts.slice(i, i + 80));
  });
  after(async () => { await h?.dispose(); });

  test("daily run: <= batchRows x maxBatches per table; FK-safe; real R2 / pending / young rows are kept", async () => {
    const m = await post("trigger 1");
    assert.ok(ok(m.result), JSON.stringify(m.result.data));
    assert.equal(await count("learning_runs", "created_at < '2021-01-01'"), 100, "200 of 300 old runs pruned (2 batches x 100)");
    assert.equal(deletes(m, "learning_runs").length, 2);
    assert.equal(await count("learning_runs", "prompt = 'trigger 1'"), 1, "the fresh row survives");
    assert.equal(await count("learning_runs", "id = 'younglr'"), 1);
    // jobs: childless prunable jobs go first (oldest), then jobs whose runs were just pruned; never ones with children
    assert.equal(await count("jobs", "id IN ('lonely_skip','lonely_null')"), 0);
    assert.equal(await count("jobs", "id IN ('keep_r2','keep_pending','keep_young')"), 3);
    assert.equal(await count("learning_runs", "job_id IS NOT NULL AND job_id NOT IN (SELECT id FROM jobs)"), 0, "no orphaned FK children");
    // 2 batches x 100 jobs: the 2 childless ones (oldest) + 198 of the 200 whose runs were just pruned; 100 jobs still have runs
    assert.equal(await count("jobs", "id LIKE 'oldjob%'"), 102);
    const marker = await h.db.prepare("SELECT rows_deleted FROM retention_marker WHERE table_name = 'learning_runs'").first();
    assert.equal(marker.rows_deleted, 200);
  });

  test("not due again for 24 h: the check is read-only (0 rows written, no DELETE)", async () => {
    const m = await post("trigger 2");
    assert.ok(ok(m.result));
    assert.equal(deletes(m, "").length, 0);
    const claimWrites = m.sqls.filter((s) => /retention_marker/i.test(s.sql)).reduce((a, s) => a + s.rows_written, 0);
    assert.equal(claimWrites, 0);
    assert.ok(m.statements <= 8, "statements: " + m.statements);
  });

  test("due again after 24 h: continues where it stopped", async () => {
    await h.db.prepare("UPDATE retention_marker SET last_run_at = last_run_at - 90000").run();
    const m = await post("trigger 3");
    assert.ok(ok(m.result));
    assert.equal(await count("learning_runs", "created_at < '2021-01-01'"), 0);
    assert.equal(deletes(m, "learning_runs").length, 2, "100 rows, then a short batch ends the table");
  });
});

describe("retention write budget", () => {
  let h;
  before(async () => {
    h = await createHarness({ bindings: { RETENTION_CHECK_INTERVAL_SEC: "0", RETENTION_BATCH_ROWS: "500", RETENTION_MAX_BATCHES: "3", RETENTION_WRITE_BUDGET: "100" } });
    const stmts = [];
    for (let i = 0; i < 400; i++) stmts.push(h.db.prepare("INSERT INTO learning_runs (id, job_id, prompt, spec_json, analysis_json, created_at) VALUES (?, NULL, 'p', '{}', '{}', '2020-01-01 00:00:00')").bind("b" + i));
    for (let i = 0; i < stmts.length; i += 80) await h.db.batch(stmts.slice(i, i + 80));
  });
  after(async () => { await h?.dispose(); });

  test("stops once the rows-written budget is spent", async () => {
    const m = await h.measure(() => h.call("POST", "/api/learning", { prompt: "budget", spec: {}, analysis: {} }));
    assert.ok(ok(m.result));
    const dels = m.sqls.filter((s) => /^DELETE FROM learning_runs/i.test(s.sql.trim()));
    const written = dels.reduce((a, s) => a + s.rows_written, 0);
    const left = (await h.db.prepare("SELECT COUNT(*) AS n FROM learning_runs WHERE created_at < '2021-01-01'").first()).n;
    assert.ok(written <= 100, "rows written by retention: " + written);
    assert.ok(left > 300 && left < 400, "pruned a little, not everything: " + left);
  });
});

describe("DB-full guard", () => {
  let h;
  before(async () => { h = await createHarness({ bindings: { RETENTION_DISABLED: "1" } }); });
  after(async () => { await h?.dispose(); });

  test("'Exceeded maximum DB size' yields degraded HTTP 200 for writes and reads, never 5xx", async () => {
    await h.fail({ d1: "D1_ERROR: Exceeded maximum DB size" });
    try {
      const calls = [
        h.call("POST", "/api/knowledge/discoveries", clipPayload(3)),
        h.call("POST", "/api/learning", { prompt: "x", spec: {}, analysis: {} }),
        h.call("POST", "/api/jobs", { prompt: "x", duration_seconds: 2 }),
        h.call("GET", "/api/knowledge/for-creation?limit=10"),
      ];
      const res = await Promise.all(calls);
      for (const r of res) {
        assert.equal(r.status, 200, JSON.stringify(r.data));
        assert.equal(r.data.degraded, true);
      }
      for (const r of res.slice(0, 3)) {
        assert.equal(r.data.recorded, false);
        assert.equal(r.headers.get("x-degraded"), "d1_db_full");
      }
    } finally {
      await h.fail({});
    }
    const ok2 = await h.call("POST", "/api/learning", { prompt: "after", spec: {}, analysis: {} });
    assert.ok(ok(ok2) && !ok2.data.degraded);
  });
});
