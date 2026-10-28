/**
 * GET /api/interpret/queue: bounded rowid-cursor window, negative cache, stale-on-D1-error, and an atomic
 * PATCH /api/interpret/:id so a row served from cache twice can never be completed twice. Local Miniflare only.
 */
import { test, describe, before, after } from "node:test";
import assert from "node:assert/strict";
import { createHarness } from "./helpers/harness.mjs";

const QUOTA = "D1_ERROR: D1 DB reached its daily limit for rows read (7500)";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const INS = "INSERT INTO interpretations (id, prompt, source, status) VALUES (?, ?, ?, ?)";

async function seed(h, { pending = 0, done = 0, web = 0 }) {
  const stmts = [];
  for (let i = 0; i < done; i++) stmts.push(h.db.prepare(INS).bind(`done${i}`, `done prompt ${i}`, "worker", "done"));
  for (let i = 0; i < pending; i++) stmts.push(h.db.prepare(INS).bind(`p${i}`, `pending prompt ${i}`, "worker", "pending"));
  for (let i = 0; i < web; i++) stmts.push(h.db.prepare(INS).bind(`w${i}`, `web prompt ${i}`, "web", "pending"));
  for (let i = 0; i < stmts.length; i += 80) await h.db.batch(stmts.slice(i, i + 80));
}
const q = (h, qs = "limit=20") => h.call("GET", `/api/interpret/queue?${qs}`);

describe("interpret queue: reads are bounded by the window, not the backlog", () => {
  let h;
  before(async () => {
    h = await createHarness({ bindings: { RETENTION_DISABLED: "1" } });
    await seed(h, { pending: 1200, done: 800, web: 3 });
  });
  after(async () => { await h?.dispose(); });

  test("a miss reads at most ~2 x limit rows with 1 statement, regardless of 1200 pending rows", async () => {
    const m = await h.measure(() => q(h, "limit=20"));
    assert.equal(m.result.status, 200);
    assert.equal(m.result.data.items.length, 20);
    assert.equal(m.statements, 1);
    assert.ok(m.rowsRead <= 60, `rows read ${m.rowsRead} (old query read every pending row: >= ${1203 * 2})`);
    assert.equal(m.result.data.scan_complete, false);
    assert.equal(m.result.data.poll_after_sec, 0);
  });

  test("web prompts are ordered first inside the window; rows carry rid and next_cursor is the max rowid", async () => {
    const r = await q(h, "limit=50");
    const ids = r.data.items.map((i) => i.id);
    assert.ok(r.data.items.length === 50);
    // web rows were inserted last (rowid > 2000: 800 done + 1200 pending before them), so they are outside this window
    assert.ok(!ids.some((i) => i.startsWith("w")));
    assert.equal(r.data.next_cursor, Math.max(...r.data.items.map((i) => i.rid)));
    const sources = r.data.items.map((i) => i.source);
    assert.deepEqual(sources, [...sources].sort((a, b) => (a === "web" ? 0 : 1) - (b === "web" ? 0 : 1)));
  });

  test("the cursor skips rows the client already attempted and reaches web rows at the tail", async () => {
    const r = await q(h, "limit=50&after=1250");
    assert.equal(r.data.items.length, 50);
    assert.ok(r.data.items.every((i) => i.rid > 1250));
    const tail = await q(h, "limit=50&after=1990");
    const ids = tail.data.items.map((i) => i.id);
    assert.deepEqual(ids.slice(0, 3), ["w0", "w1", "w2"]); // web first
    assert.ok(tail.data.items.every((i) => i.rid > 1990));
  });

  test("the same poll again costs zero D1 statements (positive cache)", async () => {
    await q(h, "limit=20");
    const m = await h.measure(() => q(h, "limit=20"));
    assert.equal(m.statements, 0);
    assert.equal(m.result.headers.get("x-cache"), "HIT");
  });

  test("garbage limit/after values are normalised, not NaN-bound", async () => {
    const r = await q(h, "limit=abc&after=-5");
    assert.equal(r.status, 200);
    assert.equal(r.data.items.length, 20);
    const big = await q(h, "limit=100000");
    assert.equal(big.data.items.length, 50);
  });
});

describe("interpret queue: negative cache, enqueue invalidation, atomic completion", () => {
  let h;
  before(async () => { h = await createHarness({ bindings: { RETENTION_DISABLED: "1" } }); });
  after(async () => { await h?.dispose(); });

  test("empty queue: 1 cheap read, then 60 s of zero-read answers with poll_after_sec >= 120 and Retry-After", async () => {
    const first = await h.measure(() => q(h));
    assert.deepEqual(first.result.data.items, []);
    assert.equal(first.result.data.scan_complete, true);
    assert.ok(first.rowsRead <= 2);
    assert.equal(first.result.data.poll_after_sec, 120);
    assert.equal(first.result.headers.get("retry-after"), "120");
    const many = await h.measure(async () => { for (let i = 0; i < 25; i++) await q(h); });
    assert.equal(many.statements, 0);
    assert.equal(many.rowsRead, 0);
  });

  test("POST enqueue invalidates the negative cache so the new prompt is served immediately", async () => {
    const c = await h.call("POST", "/api/interpret/queue", { prompt: "a red fox at dawn", source: "web" });
    assert.equal(c.status, 201);
    const r = await q(h);
    assert.deepEqual(r.data.items.map((i) => i.id), [c.data.id]);
    assert.equal(r.data.poll_after_sec, 0);
  });

  test("PATCH completes once; a second (cached/duplicate) worker gets 400 Already interpreted; unknown id is 404", async () => {
    const id = (await q(h)).data.items[0].id;
    const body = { instruction: { subject: "fox" } };
    const a = await h.call("PATCH", `/api/interpret/${id}`, body);
    assert.equal(a.status, 200);
    const b = await h.call("PATCH", `/api/interpret/${id}`, body);
    assert.equal(b.status, 400);
    assert.match(JSON.stringify(b.data), /Already interpreted/);
    const c = await h.call("PATCH", `/api/interpret/nope`, body);
    assert.equal(c.status, 404);
    const row = await h.db.prepare("SELECT status, instruction_json FROM interpretations WHERE id = ?").bind(id).first();
    assert.equal(row.status, "done");
    assert.equal(row.instruction_json, JSON.stringify({ subject: "fox" }));
  });

  test("two concurrent PATCHes: exactly one wins", async () => {
    const c = await h.call("POST", "/api/interpret/queue", { prompt: "race", source: "web" });
    const body = { instruction: { x: 1 } };
    const rs = await Promise.all([1, 2, 3].map(() => h.call("PATCH", `/api/interpret/${c.data.id}`, body)));
    assert.deepEqual(rs.map((r) => r.status).sort(), [200, 400, 400]);
  });

  test("after completion the queue is empty again (completion invalidates the cached window)", async () => {
    const r = await q(h);
    assert.deepEqual(r.data.items, []);
  });
});

describe("interpret queue: D1 quota errors degrade instead of failing", () => {
  let h;
  before(async () => {
    h = await createHarness({ bindings: { RETENTION_DISABLED: "1" } });
    await seed(h, { pending: 5 });
  });
  after(async () => { await h?.dispose(); });

  test("stale window is served (200, X-Degraded, poll_after_sec >= 300) once its 5 s TTL lapsed and D1 is over quota", async () => {
    const fresh = await q(h, "limit=5");
    assert.equal(fresh.data.items.length, 5);
    await sleep(5400);
    await h.fail({ d1: QUOTA });
    try {
      const r = await q(h, "limit=5");
      assert.equal(r.status, 200);
      assert.equal(r.headers.get("x-degraded"), "d1-quota");
      assert.equal(r.headers.get("x-cache"), "STALE");
      assert.equal(r.data.degraded, true);
      assert.equal(r.data.items.length, 5);
      assert.ok(r.data.poll_after_sec >= 300);
      assert.ok(Number(r.headers.get("retry-after")) >= 300);
    } finally {
      await h.fail({});
    }
  });

  test("quota error with nothing cached: 200 with empty items, X-Degraded and Retry-After, never a 5xx", async () => {
    await h.fail({ d1: QUOTA });
    try {
      const r = await q(h, "limit=7");
      assert.equal(r.status, 200);
      assert.deepEqual(r.data.items, []);
      assert.ok(r.data.poll_after_sec >= 300);
      assert.ok(r.headers.get("x-degraded"));
      assert.ok(Number(r.headers.get("retry-after")) >= 300);
    } finally {
      await h.fail({});
    }
  });
});