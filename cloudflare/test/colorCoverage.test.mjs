/**
 * Exact colour coverage: parity with the Python bitset layout, OR-merge sync, minimal D1 writes, report, cell lookup,
 * and graceful degradation when the (pending, unapplied) table is absent. Runs only against local Miniflare D1.
 */
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import zlib from "node:zlib";
import { createHarness, bundleModule } from "./helpers/harness.mjs";

const ROOT = path.resolve(import.meta.dirname, "..");
const VECTORS = JSON.parse(fs.readFileSync(path.join(ROOT, "..", "tests", "vectors", "color_cells_vectors.json"), "utf8"));
const PENDING = fs.readFileSync(path.join(ROOT, "migrations_pending", "0101_color_coverage_chunks.sql"), "utf8");
const SECRET = "test-secret";
const AUTH = { Authorization: `Bearer ${SECRET}` };

let cc, cleanup, h, hBare;
before(async () => {
  const b = await bundleModule("src/colorCells.ts");
  cc = b.mod;
  cleanup = b.cleanup;
  h = await createHarness({
    bindings: { MOTION_API_SECRET: SECRET, RETENTION_DISABLED: "1" },
    seed: async ({ db }) => {
      for (const s of PENDING.replace(/--.*$/gm, "").split(/;\s*(?:\n|$)/).map((x) => x.trim()).filter(Boolean)) await db.prepare(s).run();
    },
  });
  hBare = await createHarness({ bindings: { MOTION_API_SECRET: SECRET, RETENTION_DISABLED: "1" } }); // table NOT created
});
after(async () => {
  cleanup?.();
  await h?.dispose();
  await hBare?.dispose();
});

const plane = (ids) => {
  const p = new Uint8Array(65536);
  for (const id of ids) {
    const i = id & 0x7ffff;
    p[i >> 3] |= 1 << (i & 7);
  }
  return p;
};
const z = (u8) => zlib.deflateSync(Buffer.from(u8)).toString("base64");
const rgb = (r, g, b) => (r << 16) | (g << 8) | b;
const push = (hh, chunks, extra = {}, headers = AUTH) =>
  hh.call("POST", "/api/coverage/color/chunks", { space: "color.L2.a20", version: 1, enc: "zlib", chunks, ...extra }, headers);

test("TS id/bit layout matches the Python parity vectors", () => {
  assert.equal(VECTORS.space, cc.COLOR_SPACE_ID);
  assert.equal(VECTORS.n_chunks, cc.COLOR_N_CHUNKS);
  for (const v of VECTORS.cells) {
    const id = cc.rgbToId(...v.rgb);
    assert.equal(id, v.id);
    assert.equal(cc.chunkOf(id), v.chunk);
    assert.equal(cc.idToHex(id), v.hex);
    const p = plane([id]);
    assert.equal(p[v.chunk_byte], v.mask, "byte/mask of the bit set");
    assert.equal(cc.popcount(p), 1);
  }
  assert.throws(() => cc.rgbToId(256, 0, 0));
});

test("word-wise popcount/OR and tier precedence", () => {
  const a = plane([0, 1, 2, 524287]);
  const b = plane([2, 3]);
  assert.equal(cc.orInto(a, b), true);
  assert.equal(cc.orInto(a, b), false);
  assert.equal(cc.popcount(a), 5);
  const c = { observed: plane([5]), verified: plane([6]), declared: plane([5, 6, 7]) };
  assert.equal(cc.tierOf(c, 5).tier, "observed");
  assert.equal(cc.tierOf(c, 6).tier, "verified");
  assert.equal(cc.tierOf(c, 7).tier, "declared");
  assert.equal(cc.tierOf(c, 8).tier, "none");
  const n = cc.chunkCounts(c);
  assert.deepEqual([n.covered_n, n.declared_only_n, n.declared_n], [2, 1, 3]);
  assert.equal(cc.toBytes([1, 2, 3], 8).length, 8);
  assert.equal(cc.toBytes(null).length, 65536);
});

test("push requires the API secret", async () => {
  const res = await push(h, [{ idx: 0, observed: z(plane([1])) }], {}, {});
  assert.equal(res.status, 401);
});

test("first push writes exactly one row per changed chunk; replays and subsets write nothing", async () => {
  const ids = [rgb(0, 0, 0), rgb(1, 2, 3), rgb(7, 255, 255)]; // chunk 0
  const other = [rgb(255, 255, 255)]; // chunk 31
  const body = [
    { idx: 0, observed: z(plane(ids)), verified: z(plane([ids[0]])) },
    { idx: 31, observed: z(plane(other)) },
  ];
  const m1 = await h.measure(() => push(h, body));
  assert.equal(m1.result.status, 200, JSON.stringify(m1.result.data));
  assert.equal(m1.result.data.rows_written, 2);
  assert.deepEqual(m1.result.data.changed.sort((a, b) => a - b), [0, 31]);
  assert.deepEqual(m1.result.data.new_bits, { observed: 4, verified: 1, declared: 0 });
  assert.ok(m1.d1Requests <= 5, `d1 requests ${m1.d1Requests}`);
  assert.equal(m1.kv.put + m1.kv.delete, 0);

  const m2 = await h.measure(() => push(h, body)); // identical replay
  assert.equal(m2.result.data.rows_written, 0);
  assert.equal(m2.result.data.chunks_changed, 0);
  assert.equal(m2.rowsWritten, 0, "an unchanged merge must not touch D1 storage");

  const m3 = await h.measure(() => push(h, [{ idx: 0, observed: z(plane([ids[1]])) }])); // strict subset
  assert.equal(m3.result.data.rows_written, 0);
  assert.equal(m3.rowsWritten, 0);
});

test("merge is an OR across pushes (bits never disappear) and updates counts", async () => {
  const r = await push(h, [{ idx: 0, observed: z(plane([rgb(2, 2, 2)])), declared: z(plane([rgb(3, 3, 3), rgb(0, 0, 0)])) }]);
  assert.equal(r.data.rows_written, 1);
  assert.deepEqual(r.data.new_bits, { observed: 1, verified: 0, declared: 2 });
  const row = await h.db.prepare("SELECT observed_n, verified_n, declared_n, covered_n, declared_only_n, version FROM color_coverage_chunks WHERE chunk_idx = 0").first();
  assert.deepEqual({ ...row }, { observed_n: 4, verified_n: 1, declared_n: 2, covered_n: 4, declared_only_n: 1, version: 1 });
  const blob = await h.db.prepare("SELECT observed FROM color_coverage_chunks WHERE chunk_idx = 0").first();
  const bytes = cc.toBytes(blob.observed);
  for (const id of [rgb(0, 0, 0), rgb(1, 2, 3), rgb(7, 255, 255), rgb(2, 2, 2)]) assert.equal(cc.testBit(bytes, id & 0x7ffff), true);
});

test("raw encoding works; bad payloads are rejected before any D1 access", async () => {
  const raw = Buffer.from(plane([rgb(9, 9, 9)])).toString("base64");
  const ok = await push(h, [{ idx: 1, observed: raw }], { enc: "raw" });
  assert.equal(ok.status, 200);
  const bad = [
    [() => push(h, [{ idx: 1, observed: Buffer.from("short").toString("base64") }], { enc: "raw" }), 400],
    [() => push(h, [{ idx: 1, observed: z(new Uint8Array(10)) }]), 400],
    [() => push(h, [{ idx: 32, observed: z(plane([1])) }]), 400],
    [() => push(h, [{ idx: 2 }, { idx: 2 }]), 400],
    [() => push(h, []), 400],
    [() => push(h, [{ idx: 0 }], { space: "color.L9" }), 400],
    [() => push(h, [{ idx: 0 }], { version: 2 }), 409],
    [() => push(h, Array.from({ length: 9 }, (_, i) => ({ idx: i }))), 413],
    [() => push(h, [{ idx: 0 }], { enc: "gzip" }), 400],
  ];
  for (const [p, status] of bad) {
    const m = await h.measure(p);
    assert.equal(m.result.status, status, JSON.stringify(m.result.data));
    assert.equal(m.rowsWritten, 0);
  }
  assert.equal((await h.call("GET", "/api/coverage/color/chunks")).status, 405);
});

test("cell lookup returns tiers and chunk sync state, with all three input forms", async () => {
  await push(h, [{ idx: 0, declared: z(plane([rgb(4, 4, 4)])) }]);
  const get = (q) => h.call("GET", "/api/coverage/color/cell?" + q);
  const v = await get("rgb=0,0,0");
  assert.equal(v.status, 200);
  assert.equal(v.data.tier, "verified");
  assert.equal(v.data.hex, "#000000");
  assert.equal(v.headers.get("cache-control"), "public, max-age=300");
  assert.equal((await get("hex=%23010203")).data.tier, "observed");
  assert.equal((await get("id=" + rgb(4, 4, 4))).data.tier, "declared");
  const none = await get("rgb=5,5,5");
  assert.equal(none.data.tier, "none");
  assert.equal(none.data.chunk_synced, true);
  const unsynced = await get("rgb=100,0,0"); // chunk 12 never pushed
  assert.equal(unsynced.data.tier, "none");
  assert.equal(unsynced.data.chunk_synced, false);
  const multi = await get("ids=" + [0, rgb(255, 255, 255), rgb(5, 5, 5)].join(","));
  assert.deepEqual(multi.data.cells.map((c) => c.tier), ["verified", "observed", "none"]);
  assert.equal((await get("rgb=300,0,0")).status, 400);
  assert.equal((await get("")).status, 400);
  assert.equal((await get("ids=" + Array.from({ length: 65 }, (_, i) => i).join(","))).status, 400);
});

test("repeat lookups of the same chunk are served from the isolate cache (no D1 read)", async () => {
  await h.call("GET", "/api/coverage/color/cell?rgb=0,0,0");
  const m = await h.measure(() => h.call("GET", "/api/coverage/color/cell?rgb=1,1,1"));
  assert.equal(m.result.data.available, true);
  assert.equal(m.d1Requests, 0);
});

test("coverage report counts observed / verified / declared and reads counts only", async () => {
  const m = await h.measure(() => h.call("GET", "/api/coverage/color?chunks=1"));
  const d = m.result.data;
  assert.equal(d.available, true);
  assert.equal(d.total_cells, 16777216);
  assert.equal(d.chunks_synced, 3);
  assert.deepEqual([d.observed, d.verified, d.declared], [6, 1, 3]); // 4 + 1 + (31) + chunk 1 (9,9,9)
  assert.equal(d.covered, 6);
  assert.equal(d.declared_only, 2);
  assert.ok(m.d1Requests === 1 && m.rowsRead <= 32, `one counts query only: ${m.d1Requests}/${m.rowsRead}`);
  const again = await h.measure(() => h.call("GET", "/api/coverage/color?chunks=1"));
  assert.equal(again.d1Requests, 0, "second read is cached");
});

test("without the table: report/lookup say available:false (200) and push says recorded:false, never a 500", async () => {
  const rep = await hBare.call("GET", "/api/coverage/color");
  assert.equal(rep.status, 200);
  assert.equal(rep.data.available, false);
  assert.equal(rep.data.reason, "table_missing");
  const cell = await hBare.call("GET", "/api/coverage/color/cell?rgb=1,2,3");
  assert.equal(cell.status, 200);
  assert.equal(cell.data.available, false);
  const res = await push(hBare, [{ idx: 0, observed: z(plane([1])) }]);
  assert.equal(res.status, 200);
  assert.equal(res.data.recorded, false);
  assert.equal(res.data.available, false);
});

test("a full D1 degrades to the shared 'db full' response", async () => {
  await h.fail({ d1: "D1_ERROR: database or disk is full: SQLITE_FULL" });
  const res = await push(h, [{ idx: 5, observed: z(plane([1])) }]);
  await h.fail({});
  assert.ok(res.status === 200 || res.status === 503 || res.status === 507, String(res.status));
  assert.notEqual(res.data.recorded, true);
});