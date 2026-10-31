/**
 * Opacity / cross-axis aggregates (pending migration 0104): allow-list, monotonic max merge, changed-only writes,
 * GET summary and graceful degradation when the table is absent. Local Miniflare D1 only.
 */
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createHarness } from "./helpers/harness.mjs";

const ROOT = path.resolve(import.meta.dirname, "..");
const SQL = fs.readFileSync(path.join(ROOT, "migrations", "0025_axis_coverage.sql"), "utf8");
const SECRET = "test-secret";
const AUTH = { Authorization: `Bearer ${SECRET}` };

let h, hBare;
before(async () => {
  h = await createHarness({
    bindings: { MOTION_API_SECRET: SECRET, RETENTION_DISABLED: "1" },
    seed: async ({ db }) => {
      for (const s of SQL.replace(/--.*$/gm, "").split(/;\s*(?:\n|$)/).map((x) => x.trim()).filter(Boolean)) await db.prepare(s).run();
    },
  });
  hBare = await createHarness({
    bindings: { MOTION_API_SECRET: SECRET, RETENTION_DISABLED: "1" },
    seed: async ({ db }) => { await db.prepare("DROP TABLE IF EXISTS axis_coverage").run(); },
  });
});
after(async () => { await h?.dispose(); await hBare?.dispose(); });

const post = (hh, items, headers = AUTH) => hh.call("POST", "/api/coverage/axes", { items }, headers);
const get = (hh) => hh.call("GET", "/api/coverage/axes");

test("POST requires auth", async () => {
  const r = await post(h, [{ key: "opacity.total", seen: 1 }], {});
  assert.equal(r.status, 401);
});

test("unknown keys and bad counts are rejected", async () => {
  assert.equal((await post(h, [{ key: "evil", seen: 1 }])).status, 400);
  assert.equal((await post(h, [{ key: "opacity.total", seen: -1 }])).status, 400);
  assert.equal((await post(h, [])).status, 400);
});

test("upsert, max-merge and changed-only writes", async () => {
  let j = await (await post(h, [
    { key: "opacity.total", seen: 100 },
    { key: "opacity.level.3", seen: 40, universe: 32768 },
    { key: "pair.genrexlighting_preset", seen: 12, universe: 50 },
  ])).data;
  assert.equal(j.items_changed, 3);
  assert.equal(j.rows_written, 3);
  j = await (await post(h, [{ key: "opacity.total", seen: 100 }, { key: "opacity.level.3", seen: 10, universe: 32768 }])).data;
  assert.equal(j.items_changed, 0, "unchanged or lower values cost zero writes");
  assert.equal(j.rows_written, 0);
  j = await (await post(h, [{ key: "opacity.total", seen: 150 }])).data;
  assert.equal(j.items_changed, 1);
  const g = (await get(h)).data;
  assert.equal(g.available, true);
  assert.equal(g.opacity.levels.length, 16);
  assert.equal(g.cross_axis.pairs.length, 15);
  const pair = g.cross_axis.pairs.find((p) => p.pair === "genrexlighting_preset");
  assert.equal(pair.seen, 12);
  assert.equal(pair.pct, 24);
  assert.equal(g.opacity.levels[3].seen, 40);
});

test("missing table degrades to available:false", async () => {
  const g = (await get(hBare)).data;
  assert.equal(g.available, false);
  const r = await post(hBare, [{ key: "opacity.total", seen: 1 }]);
  assert.equal(r.status, 200);
  const j = r.data;
  assert.equal(j.available, false);
  assert.equal(j.rows_written, 0);
});
