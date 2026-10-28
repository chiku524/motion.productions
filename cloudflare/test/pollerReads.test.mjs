/**
 * Poller read budget: every endpoint a loop polls on a timer must answer repeat calls from cache (0 D1 statements),
 * keep a miss bounded, and survive a D1 daily-limit error by serving the last good copy. Local Miniflare only.
 */
import { test, describe, before, after } from "node:test";
import assert from "node:assert/strict";
import { createHarness, seedRegistry } from "./helpers/harness.mjs";

const QUOTA = "D1_ERROR: D1 DB reached its daily limit for rows read (7500)";

describe("poller endpoints: repeat calls are free", () => {
  let h;
  before(async () => {
    h = await createHarness({ bindings: { RETENTION_DISABLED: "1" } });
    await seedRegistry(h, { static_colors: 300, static_sound: 100, learned_blends: 500 });
    const stmts = [];
    for (let i = 0; i < 400; i++) stmts.push(h.db.prepare("INSERT INTO linguistic_registry (id, span, canonical, domain, variant_type, count) VALUES (?, ?, ?, 'color', 'synonym', 1)").bind(`l${i}`, `span${i}`, `canon${i}`));
    for (let i = 0; i < stmts.length; i += 80) await h.db.batch(stmts.slice(i, i + 80));
    const jobs = [];
    for (let i = 0; i < 60; i++) jobs.push(h.db.prepare("INSERT INTO jobs (id, prompt, status, r2_key, workflow_type) VALUES (?, 'p', 'completed', ?, 'web')").bind(`j${i}`, `r2/${i}`));
    await h.db.batch(jobs);
  });
  after(async () => { await h?.dispose(); });

  for (const path of ["/api/linguistic-registry", "/api/metrics", "/api/registries/coverage", "/api/registries/mission", "/api/loop/progress"]) {
    test(`${path}: first call may read D1, the next 20 read nothing`, async () => {
      const first = await h.call("GET", path);
      assert.equal(first.status, 200, `${path} -> ${first.status}`);
      const again = await h.measure(async () => { for (let i = 0; i < 20; i++) assert.equal((await h.call("GET", path)).status, 200); });
      assert.equal(again.statements, 0, `${path}: ${again.statements} D1 statements on cached calls`);
      assert.equal(again.rowsRead, 0);
    });
  }

  test("/api/metrics: bounded miss (one pass over <= 20 ids + counts), Prometheus text unchanged", async () => {
    const h2 = await createHarness({ bindings: { RETENTION_DISABLED: "1" } });
    try {
      const jobs = [];
      for (let i = 0; i < 100; i++) jobs.push(h2.db.prepare("INSERT INTO jobs (id, prompt, status, r2_key, workflow_type) VALUES (?, 'p', 'completed', ?, 'web')").bind(`j${i}`, `r2/${i}`));
      await h2.db.batch(jobs.slice(0, 80)); await h2.db.batch(jobs.slice(80));
      const m = await h2.measure(() => h2.call("GET", "/api/metrics"));
      assert.equal(m.result.status, 200);
      assert.match(m.result.data, /motion_productions_total_runs\{last="20"\} 20/);
      assert.match(m.result.data, /motion_productions_jobs_total 100/);
      assert.ok(m.sqls.length <= 5, `${m.sqls.length} statements`);
    } finally { await h2.dispose(); }
  });

  test("/api/linguistic-registry: same mappings as before, domain filter keyed separately", async () => {
    const all = await h.call("GET", "/api/linguistic-registry");
    assert.equal(all.data.mappings.length, 400);
    assert.deepEqual(Object.keys(all.data.mappings[0]).sort(), ["canonical", "count", "domain", "span", "variant_type"]);
    const none = await h.call("GET", "/api/linguistic-registry?domain=nonexistent");
    assert.deepEqual(none.data.mappings, []);
  });
});

describe("poller endpoints: D1 quota error serves the last good copy", () => {
  let h;
  before(async () => {
    h = await createHarness({ bindings: { RETENTION_DISABLED: "1" } });
    await h.db.prepare("INSERT INTO linguistic_registry (id, span, canonical, domain, variant_type, count) VALUES ('a','x','y','color','synonym',1)").run();
  });
  after(async () => { await h?.dispose(); });

  test("metrics with D1 over quota and nothing cached: 200 + X-Degraded (not a 500)", async () => {
    await h.fail({ d1: QUOTA });
    try {
      const r = await h.call("GET", "/api/metrics");
      assert.equal(r.status, 200);
      assert.ok(r.headers.get("x-degraded"));
    } finally { await h.fail({}); }
  });

  test("linguistic registry is cached across a later D1 outage", async () => {
    const ok = await h.call("GET", "/api/linguistic-registry");
    assert.equal(ok.data.mappings.length, 1);
    await h.fail({ d1: QUOTA });
    try {
      const r = await h.call("GET", "/api/linguistic-registry");
      assert.equal(r.data.mappings.length, 1);
    } finally { await h.fail({}); }
  });
});