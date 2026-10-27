// Sound v2 (sound.L1) key space parity with Python, plus Worker write budget, v1 isolation and mission stats.
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createHarness, seedRegistry, bundleModule } from "./helpers/harness.mjs";
const ks = await bundleModule("src/soundKeyspace.ts");
const nm = await bundleModule("src/naming.ts");
const {
  SOUND_V2_SPACE_SIZE, soundV2Key, soundV2KeyToOrdinal, soundV2OrdinalToKey, soundV2CellId, parseSoundV2Key,
  isSoundV2Key, encodeSeenBitmap, decodeSeenBitmap, decodeSoundV2Ordinal,
} = ks.mod;
const { sanitizePureSoundKey } = nm.mod;
const vectors = JSON.parse(
  fs.readFileSync(path.resolve(import.meta.dirname, "..", "..", "tests", "vectors", "sound_v2_vectors.json"), "utf8"),
);

test("frozen parity vectors from the Python key space reproduce exactly", () => {
  assert.equal(vectors.size, SOUND_V2_SPACE_SIZE);
  assert.ok(vectors.vectors.length >= 10);
  for (const v of vectors.vectors) {
    const key = soundV2Key(v.amplitude, v.peak_hz, v.flatness, v.attack, v.zcr);
    assert.equal(key, v.key, JSON.stringify(v));
    assert.equal(soundV2KeyToOrdinal(key), v.ordinal);
    assert.equal(soundV2OrdinalToKey(v.ordinal), v.key);
    assert.equal(soundV2CellId(key), v.cell_id);
  }
});

test("every ordinal round-trips and malformed keys are rejected", () => {
  for (let o = 0; o < SOUND_V2_SPACE_SIZE; o++) {
    const k = soundV2OrdinalToKey(o);
    assert.equal(soundV2KeyToOrdinal(k), o);
  }
  assert.throws(() => decodeSoundV2Ordinal(SOUND_V2_SPACE_SIZE));
  for (const bad of ["s2.12-0-0-0-0", "s2.00-8-0-0-0", "s2.00-0-4-0-0", "s2.0-0-0-0-0", "s1.00-0-0-0-0", "0.1_mid_hum", "", null]) {
    assert.equal(isSoundV2Key(bad), false, String(bad));
    assert.equal(parseSoundV2Key(bad), null);
  }
});

test("v1 key sanitising is untouched and v2 keys pass through", () => {
  assert.equal(sanitizePureSoundKey("s2.07-3-1-2-0"), "s2.07-3-1-2-0");
  assert.equal(sanitizePureSoundKey("0.12_mid_hum"), "0.12_mid_hum");
});

test("seen bitmap layout matches Python encode_bitmap (hex of the integer with bit = ordinal)", () => {
  const ords = [0, 1, 5, 4095, 6143];
  const expected = ords.reduce((a, o) => a | (1n << BigInt(o)), 0n).toString(16).padStart(SOUND_V2_SPACE_SIZE / 4, "0");
  const hex = encodeSeenBitmap(ords);
  assert.equal(hex, expected);
  assert.deepEqual([...decodeSeenBitmap(hex)].sort((a, b) => a - b), ords);
  assert.equal(decodeSeenBitmap("zz").size, 0);
  assert.equal(encodeSeenBitmap([]).length, 1536);
});

let h;
before(async () => {
  h = await createHarness({ bindings: { RETENTION_DISABLED: "1" }, seed: (ctx) => seedRegistry(ctx, { static_sound: 40 }) });
});
after(async () => { await h?.dispose(); });

const cell = (o, extra = {}) => ({
  key: soundV2OrdinalToKey(o), name: soundV2CellId(o), amplitude: 0.1, strength_pct: 10, tone: "band3", timbre: "noisy",
  evidence_tier: "observed", depth_breakdown: { ordinal: o, tier: "observed" }, source_prompt: "sound v2 survey", ...extra,
});

test("a clip's 6 v2 cells cost the same D1 budget as 6 v1 sounds and add no KV", async () => {
  const v1 = Array.from({ length: 6 }, (_, i) => ({ key: `0.${i + 10}_mid_hum`, amplitude: 0.1, name: `v1 sound ${i}` }));
  const v2 = [1000, 1001, 1002, 1003, 1004, 1005].map((o) => cell(o));
  const a = await h.measure(() => h.call("POST", "/api/knowledge/discoveries", { static_sound: v1 }));
  const b = await h.measure(() => h.call("POST", "/api/knowledge/discoveries", { static_sound: v2 }));
  assert.ok([200, 201].includes(b.result.status), JSON.stringify(b.result.data));
  assert.equal(b.d1Requests, a.d1Requests, "same number of D1 requests as the v1 equivalent");
  assert.ok(b.statements <= a.statements);
  assert.ok(b.rowsWritten <= a.rowsWritten + 1, `v2 rows written ${b.rowsWritten} vs v1 ${a.rowsWritten}`);
  assert.equal(b.kv.put + b.kv.delete + b.kv.get, 0);
  assert.equal(b.result.data.novel.sound_v2, 6);
  assert.equal(b.result.data.novel.static_sound, 0, "v2 cells do not inflate the v1 counter");
  const rows = await h.db.prepare("SELECT COUNT(*) AS n FROM static_sound WHERE sound_key LIKE 's2.%'").first();
  assert.equal(rows.n, 6);
});

test("re-posting a cell only bumps its count; verified upgrades the tier; malformed v2 keys are ignored", async () => {
  const o = 2000;
  await h.call("POST", "/api/knowledge/discoveries", { static_sound: [cell(o)] });
  const again = await h.call("POST", "/api/knowledge/discoveries", { static_sound: [cell(o), { key: "s2.99-9-9-9-9", name: "bad" }] });
  assert.equal(again.data.novel.sound_v2 ?? 0, 0);
  let row = await h.db.prepare("SELECT count, name, depth_breakdown_json FROM static_sound WHERE sound_key = ?").bind(soundV2OrdinalToKey(o)).first();
  assert.equal(row.count, 2);
  assert.equal(row.name, "sound.L1#02000");
  assert.equal(JSON.parse(row.depth_breakdown_json).tier, "observed");
  await h.call("POST", "/api/knowledge/discoveries", { static_sound: [cell(o, { evidence_tier: "verified", depth_breakdown: { ordinal: o, tier: "verified" } })] });
  row = await h.db.prepare("SELECT count, depth_breakdown_json FROM static_sound WHERE sound_key = ?").bind(soundV2OrdinalToKey(o)).first();
  assert.equal(JSON.parse(row.depth_breakdown_json).tier, "verified");
  assert.equal(row.count, 3);
  const bad = await h.db.prepare("SELECT COUNT(*) AS n FROM static_sound WHERE sound_key = 's2.99-9-9-9-9'").first();
  assert.equal(bad.n, 0);
});

test("mission stats report sound v2 coverage by tier with a seen bitmap; v1 sound stats exclude v2 rows", async () => {
  const res = await h.call("GET", "/api/registries/mission?fresh=1");
  assert.equal(res.status, 200, JSON.stringify(res.data).slice(0, 300));
  const v2 = res.data.sound_v2;
  assert.ok(v2, "sound_v2 present");
  assert.equal(v2.space_size, SOUND_V2_SPACE_SIZE);
  assert.equal(v2.covered, 7);
  assert.equal(v2.by_tier.verified, 1);
  assert.equal(v2.by_tier.observed, 6);
  assert.equal(v2.by_tier.declared, 0);
  const seen = decodeSeenBitmap(v2.seen_bitmap);
  assert.equal(seen.size, 7);
  assert.ok(seen.has(1000) && seen.has(2000) && !seen.has(2001));
  assert.match(v2.tier_policy, /declared/);
  assert.equal(res.data.sound.total, 46, "v1 total = 40 seeded + 6 v1 posted; v2 rows excluded");
  const cov = await h.call("GET", "/api/registries/coverage");
  assert.equal(cov.data.sound_v2.covered, 7);
  assert.equal(cov.data.sound_v2.seen_bitmap, undefined);
  assert.ok(cov.data.evidence_tier_policy);
});