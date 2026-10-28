/**
 * Worker side of the shared D1 write budget (additive API): `count_delta` coalescing, `rows_written` reporting,
 * and the batched linguistic upsert. Local Miniflare only (never Cloudflare).
 */
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { createHarness } from "./helpers/harness.mjs";

let h;
before(async () => {
  h = await createHarness({ bindings: { RETENTION_DISABLED: "1" } });
});
after(async () => { await h?.dispose(); });

test("count_delta folds N client sightings into one upsert; no field means 1; clamped", async () => {
  const mk = (key, extra = {}) => ({ key, r: 1, g: 2, b: 3, name: `N ${key}`, source_prompt: "p", ...extra });
  let r = await h.call("POST", "/api/knowledge/discoveries", { static_colors: [mk("wb_a", { count_delta: 7 }), mk("wb_b")] });
  assert.ok([200, 201].includes(r.status), JSON.stringify(r.data));
  assert.equal((await h.db.prepare("SELECT count FROM static_colors WHERE color_key = 'wb_a'").first()).count, 7);
  assert.equal((await h.db.prepare("SELECT count FROM static_colors WHERE color_key = 'wb_b'").first()).count, 1);
  assert.equal(r.data.novel.static_colors, 2, "fresh rows still count as novel when delta > 1");
  // same key twice in one body with deltas: summed, still one row
  r = await h.call("POST", "/api/knowledge/discoveries", { static_colors: [mk("wb_a", { count_delta: 3 }), mk("wb_a")] });
  assert.equal((await h.db.prepare("SELECT count FROM static_colors WHERE color_key = 'wb_a'").first()).count, 11);
  assert.equal(r.data.novel.static_colors, 0, "an existing row is not novel");
  // nonsense / huge deltas are clamped, never negative
  await h.call("POST", "/api/knowledge/discoveries", { static_colors: [mk("wb_c", { count_delta: 10 ** 9 }), mk("wb_d", { count_delta: -5 })] });
  assert.equal((await h.db.prepare("SELECT count FROM static_colors WHERE color_key = 'wb_c'").first()).count, 1000);
  assert.equal((await h.db.prepare("SELECT count FROM static_colors WHERE color_key = 'wb_d'").first()).count, 1);
});

test("discoveries response reports rows_written equal to what D1 charged", async () => {
  const m = await h.measure(() =>
    h.call("POST", "/api/knowledge/discoveries", {
      static_colors: [{ key: "wb_rw1", r: 9, g: 9, b: 9, name: "RW One" }, { key: "wb_rw2", r: 8, g: 8, b: 8, name: "RW Two" }],
    }),
  );
  assert.ok([200, 201].includes(m.result.status));
  assert.equal(typeof m.result.data.rows_written, "number");
  assert.ok(m.result.data.rows_written >= 2, "at least one row per unique key");
  assert.ok(m.result.data.rows_written <= m.rowsWritten, "never over-reports what D1 charged");
  assert.ok(m.result.data.rows_written >= m.rowsWritten - 2, "close to the measured total");
});

test("linguistic batch: one batched upsert, summed counts, rows_written, no per-item SELECT", async () => {
  const items = [
    { span: "wb dusk", canonical: "dark", domain: "color" },
    { span: "wb dusk", canonical: "dark", domain: "color", count: 4 },
    { span: "wb glow", canonical: "bright", domain: "color", count: 2 },
  ];
  let m = await h.measure(() => h.call("POST", "/api/linguistic-registry/batch", { items }));
  assert.ok([200, 201].includes(m.result.status), JSON.stringify(m.result.data));
  assert.equal(m.result.data.inserted, 2);
  assert.equal(m.result.data.updated, 0);
  assert.equal((await h.db.prepare("SELECT count FROM linguistic_registry WHERE span = 'wb dusk'").first()).count, 5);
  assert.equal((await h.db.prepare("SELECT count FROM linguistic_registry WHERE span = 'wb glow'").first()).count, 2);
  assert.equal(m.d1Requests, 1, "one D1 request for the whole batch");
  assert.equal(m.sqls.filter((s) => /^\s*SELECT/i.test(s.sql)).length, 0, "no per-item SELECT");
  assert.equal(m.result.data.rows_written, m.rowsWritten);

  // bumping existing spans costs ONE row each (count/updated_at are not indexed)
  m = await h.measure(() => h.call("POST", "/api/linguistic-registry/batch", { items: [{ span: "wb dusk", canonical: "dark", domain: "color", count: 9 }, { span: "wb glow", canonical: "bright", domain: "color" }] }));
  assert.equal(m.result.data.inserted, 0);
  assert.equal(m.result.data.updated, 2);
  assert.equal(m.rowsWritten, 2);
  assert.equal((await h.db.prepare("SELECT count FROM linguistic_registry WHERE span = 'wb dusk'").first()).count, 14);
});

test("interpretation POSTs report rows_written", async () => {
  const body = { prompt: "a slow green tide at dawn", instruction: { duration: 6 }, source: "loop" };
  const m = await h.measure(() => h.call("POST", "/api/interpretations", body));
  assert.equal(m.result.status, 201, JSON.stringify(m.result.data));
  assert.equal(m.result.data.rows_written, m.rowsWritten);
  const b = await h.measure(() => h.call("POST", "/api/interpretations/batch", { items: [{ prompt: "a quiet violet harbor at night", instruction: { duration: 6 }, source: "backfill" }] }));
  assert.equal(b.result.data.inserted, 1);
  assert.equal(b.result.data.rows_written, b.rowsWritten);
});
