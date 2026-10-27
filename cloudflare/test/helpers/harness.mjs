/**
 * Local Worker harness: bundles src/index.ts with esbuild, runs it in Miniflare (local D1 + KV),
 * and wraps env.DB / env.MOTION_KV in counting proxies so tests can assert on D1 statements,
 * rows read/written and KV get/put/delete per request. Never talks to Cloudflare.
 */
import { build } from "esbuild";
import { Miniflare } from "miniflare";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

const ENTRY_SHIM = (indexPath, extraEnv) => `
import worker from ${JSON.stringify(indexPath)};
const stats = { d1: [], kv: { get: 0, put: 0, delete: 0, list: 0 }, r2: { get: 0, put: 0, delete: 0, list: 0, head: 0 }, d1Requests: 0 };
globalThis.__stats = stats;
const FAIL = { d1: null, kv: null };
globalThis.__fail = FAIL;

function record(sql, meta) {
  stats.d1.push({ sql, rows_read: meta?.rows_read ?? 0, rows_written: meta?.rows_written ?? 0 });
}
function failD1() {
  if (FAIL.d1) throw new Error(FAIL.d1);
}
function wrapStmt(stmt, sql) {
  const w = {
    bind: (...a) => wrapStmt(stmt.bind(...a), sql),
    async run() { failD1(); stats.d1Requests++; const r = await stmt.run(); record(sql, r.meta); return r; },
    async all() { failD1(); stats.d1Requests++; const r = await stmt.all(); record(sql, r.meta); return r; },
    async raw(o) { failD1(); stats.d1Requests++; const r = await stmt.raw(o); record(sql, null); return r; },
    async first(col) {
      failD1(); stats.d1Requests++;
      const r = await stmt.all();
      record(sql, r.meta);
      const row = (r.results || [])[0] ?? null;
      if (row == null) return null;
      return col ? row[col] ?? null : row;
    },
    __stmt: stmt,
    __sql: sql,
  };
  return w;
}
function wrapDb(db) {
  return {
    prepare: (sql) => wrapStmt(db.prepare(sql), sql),
    async batch(stmts) {
      failD1(); stats.d1Requests++;
      const res = await db.batch(stmts.map((s) => s.__stmt));
      res.forEach((r, i) => record(stmts[i].__sql, r.meta));
      return res;
    },
    async exec(sql) { return db.exec(sql); },
  };
}
function wrapKv(kv) {
  const failKv = () => { if (FAIL.kv) throw new Error(FAIL.kv); };
  return {
    async get(k, o) { failKv(); stats.kv.get++; return kv.get(k, o); },
    async put(k, v, o) { failKv(); stats.kv.put++; return kv.put(k, v, o); },
    async delete(k) { failKv(); stats.kv.delete++; return kv.delete(k); },
    async list(o) { failKv(); stats.kv.list++; return kv.list(o); },
  };
}
function wrapR2(b) {
  return {
    async get(k, o) { stats.r2.get++; return b.get(k, o); },
    async head(k) { stats.r2.head++; return b.head(k); },
    async put(k, v, o) { stats.r2.put++; return b.put(k, v, o); },
    async delete(k) { stats.r2.delete++; return b.delete(k); },
    async list(o) { stats.r2.list++; return b.list(o); },
  };
}
export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (url.pathname === "/__stats") return Response.json(stats);
    if (url.pathname === "/__reset") {
      stats.d1.length = 0; stats.d1Requests = 0;
      stats.kv.get = stats.kv.put = stats.kv.delete = stats.kv.list = 0;
      for (const k of Object.keys(stats.r2)) stats.r2[k] = 0;
      return Response.json({ ok: true });
    }
    if (url.pathname === "/__fail") {
      FAIL.d1 = url.searchParams.get("d1") || null;
      FAIL.kv = url.searchParams.get("kv") || null;
      return Response.json({ ok: true, FAIL });
    }
    const wrapped = {
      ...env,
      DB: wrapDb(env.DB),
      MOTION_KV: wrapKv(env.MOTION_KV),
      VIDEOS: wrapR2(env.VIDEOS),
      ASSETS: { fetch: async () => new Response("asset", { status: 404 }) },
      ...${JSON.stringify(extraEnv || {})},
    };
    return worker.fetch(request, wrapped, ctx);
  },
};
`;

export async function createHarness({ root, bindings = {}, seed } = {}) {
  const projectRoot = root || path.resolve(import.meta.dirname, "..", "..");
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "motion-harness-"));
  const shimPath = path.join(tmp, "shim.ts");
  const indexPath = path.join(projectRoot, "src", "index.ts").replace(/\\/g, "/");
  fs.writeFileSync(shimPath, ENTRY_SHIM(indexPath, bindings));
  const outFile = path.join(tmp, "worker.mjs");
  await build({
    entryPoints: [shimPath],
    outfile: outFile,
    bundle: true,
    format: "esm",
    platform: "neutral",
    mainFields: ["module", "main"],
    conditions: ["workerd", "worker", "browser"],
    external: ["node:*", "cloudflare:*"],
    target: "es2022",
    logLevel: "error",
    nodePaths: [path.join(projectRoot, "node_modules"), ...(process.env.HARNESS_NODE_PATH ? [process.env.HARNESS_NODE_PATH] : [])],
  });
  const mf = new Miniflare({
    modules: true,
    script: fs.readFileSync(outFile, "utf8"),
    compatibilityDate: "2025-01-01",
    compatibilityFlags: ["nodejs_compat"],
    d1Databases: { DB: "harness-db" },
    kvNamespaces: ["MOTION_KV"],
    r2Buckets: ["VIDEOS"],
    bindings: { ...bindings },
  });
  const db = await mf.getD1Database("DB");
  const kv = await mf.getKVNamespace("MOTION_KV");
  const migDir = path.join(projectRoot, "migrations");
  for (const f of fs.readdirSync(migDir).filter((n) => n.endsWith(".sql")).sort()) {
    const sql = fs.readFileSync(path.join(migDir, f), "utf8");
    // D1 exec wants one statement per line group; split on semicolons at statement ends.
    const stmts = sql
      .replace(/--.*$/gm, "")
      .split(/;\s*(?:\n|$)/)
      .map((s) => s.trim())
      .filter(Boolean);
    for (const s of stmts) {
      try {
        await db.prepare(s).run();
      } catch (e) {
        // duplicate ALTER etc. are fine for harness purposes
        if (!/duplicate column|already exists/i.test(String(e))) throw new Error(`${f}: ${e}\n${s}`);
      }
    }
  }
  if (seed) await seed({ db, kv, mf });

  async function call(method, pathname, body, headers = {}) {
    const res = await mf.dispatchFetch("http://localhost" + pathname, {
      method,
      headers: { "content-type": "application/json", ...headers },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const text = await res.text();
    let data = null;
    try { data = JSON.parse(text); } catch { data = text; }
    return { status: res.status, data, headers: res.headers };
  }
  async function callRaw(method, pathname, body, headers = {}) {
    const res = await mf.dispatchFetch("http://localhost" + pathname, { method, headers, body });
    const text = await res.text();
    let data = null;
    try { data = JSON.parse(text); } catch { data = text; }
    return { status: res.status, data, headers: res.headers };
  }
  async function stats() {
    const s = (await mf.dispatchFetch("http://localhost/__stats").then((r) => r.json()));
    return {
      statements: s.d1.length,
      d1Requests: s.d1Requests,
      rowsRead: s.d1.reduce((a, x) => a + x.rows_read, 0),
      rowsWritten: s.d1.reduce((a, x) => a + x.rows_written, 0),
      kv: s.kv,
      r2: s.r2,
      sqls: s.d1,
    };
  }
  async function reset() { await mf.dispatchFetch("http://localhost/__reset"); }
  async function fail({ d1, kv: kvMsg } = {}) {
    const q = new URLSearchParams();
    if (d1) q.set("d1", d1);
    if (kvMsg) q.set("kv", kvMsg);
    await mf.dispatchFetch("http://localhost/__fail?" + q.toString());
  }
  /** Run fn, return {result, stats} for exactly the traffic inside. */
  async function measure(fn) {
    await reset();
    const result = await fn();
    return { result, ...(await stats()) };
  }
  async function dispose() {
    await mf.dispose();
    fs.rmSync(tmp, { recursive: true, force: true });
  }
  return { mf, db, kv, call, callRaw, stats, reset, fail, measure, dispose };
}

/** Deterministic seed approximating a mature production DB (sizes are tunable). */
export async function seedRegistry({ db }, sizes = {}) {
  const n = { static_colors: 1300, static_sound: 400, learned_blends: 4000, learned_motion: 300, learned_lighting: 200, learned_composition: 150, learned_graphics: 150, learned_temporal: 200, learned_technical: 60, learned_gradient: 80, learned_camera: 60, learned_transition: 40, learned_audio_semantic: 120, learned_time: 40, narrative: 300, learned_entities: 100, ...sizes };
  const stmts = [];
  const ins = (sql, ...a) => stmts.push(db.prepare(sql).bind(...a));
  for (let i = 0; i < n.static_colors; i++) {
    const r = (i * 25) % 250, g = (Math.floor(i / 11) * 25) % 250, b = (Math.floor(i / 121) * 25) % 250;
    ins("INSERT OR IGNORE INTO static_colors (id, color_key, r, g, b, opacity, count, name) VALUES (?, ?, ?, ?, ?, 1, ?, ?)", `sc${i}`, `seed_${r}_${g}_${b}_${i}`, r, g, b, 1 + (i % 17), `SeedColor${i}`);
  }
  for (let i = 0; i < n.static_sound; i++) ins("INSERT OR IGNORE INTO static_sound (id, sound_key, count, name) VALUES (?, ?, ?, ?)", `ss${i}`, `seedsound_${i}`, 1 + (i % 9), `SeedSound${i}`);
  for (let i = 0; i < n.learned_blends; i++) ins("INSERT INTO learned_blends (id, name, domain, inputs_json, output_json) VALUES (?, ?, 'color', '{}', '{}')", `lb${i}`, `SeedBlend${i}`);
  const dyn = [
    ["learned_motion", "profile_key", "learned_motion"],
    ["learned_lighting", "profile_key", "learned_lighting"],
    ["learned_composition", "profile_key", "learned_composition"],
    ["learned_graphics", "profile_key", "learned_graphics"],
    ["learned_temporal", "profile_key", "learned_temporal"],
    ["learned_technical", "profile_key", "learned_technical"],
    ["learned_gradient", "profile_key", "learned_gradient"],
    ["learned_camera", "profile_key", "learned_camera"],
    ["learned_transition", "profile_key", "learned_transition"],
    ["learned_audio_semantic", "profile_key", "learned_audio_semantic"],
    ["learned_time", "profile_key", "learned_time"],
    ["learned_entities", "profile_key", "learned_entities"],
  ];
  for (const [table, keyCol, nk] of dyn) {
    for (let i = 0; i < (n[nk] || 50); i++) {
      try { ins(`INSERT OR IGNORE INTO ${table} (id, ${keyCol}, count, name) VALUES (?, ?, ?, ?)`, `${table}${i}`, `seed_${table}_${i}`, 1 + (i % 7), `Seed${table}${i}`); } catch { /* skip */ }
    }
  }
  for (let i = 0; i < n.narrative; i++) {
    const aspect = ["genre", "mood", "plots", "settings", "themes", "style", "scene_type"][i % 7];
    ins("INSERT OR IGNORE INTO narrative_entries (id, aspect, entry_key, value, count, name) VALUES (?, ?, ?, ?, ?, ?)", `ne${i}`, aspect, `seed_${i}`, `seed ${i}`, 1 + (i % 5), `SeedNarr${i}`);
  }
  for (let i = 0; i < stmts.length; i += 80) {
    try { await db.batch(stmts.slice(i, i + 80)); } catch (e) {
      // dynamic tables with NOT NULL columns would fail here; seed individually and ignore failures
      for (const s of stmts.slice(i, i + 80)) { try { await s.run(); } catch { /* ignore */ } }
    }
  }
}

/**
 * A representative per-clip discoveries payload (what grow_and_sync_to_api posts for one clip):
 * a few static colors/sounds (some already known), dynamic windows, narrative tags, and ~10 blends.
 * `clip` makes keys partially novel/partially repeated like real runs.
 */
export function clipPayload(clip = 0, { jobId } = {}) {
  const p = (k) => `clip${clip}_${k}`;
  return {
    static_colors: [
      { key: `seed_0_0_0_0`, r: 0, g: 0, b: 0, name: "Seed", source_prompt: "p" },
      { key: `seed_25_0_0_1`, r: 25, g: 0, b: 0, source_prompt: "p" },
      { key: p("c3"), r: 25 * (clip % 10), g: 50, b: 75, source_prompt: "a calm sea" },
    ],
    static_sound: [
      { key: "seedsound_1", amplitude: 0.2 },
      { key: "seedsound_2", amplitude: 0.3 },
      { key: p("s3"), amplitude: 0.55, tone: "warm", source_prompt: "a calm sea" },
    ],
    narrative: {
      mood: [{ key: "seed_1", value: "calm" }, { key: "seed_8", value: "tense" }],
      genre: [{ key: "seed_0", value: "drama" }],
      settings: [{ key: "seed_2", value: "beach" }, { key: p("n"), value: "harbor" }],
    },
    blends: Array.from({ length: 10 }, (_, i) => ({
      name: `Blend ${clip}-${i}`,
      domain: ["color", "motion", "lighting", "sound"][i % 4],
      inputs: { a: i, b: clip },
      output: { v: i * clip },
      source_prompt: "a calm sea",
    })),
    motion: [{ key: "seed_learned_motion_1", motion_level: 0.3, motion_std: 0.1, motion_trend: "steady" }, { key: p("m"), motion_level: 0.5, motion_std: 0.2, motion_trend: "rising" }],
    lighting: [{ key: "seed_learned_lighting_2", brightness: 1, contrast: 1, saturation: 1 }, { key: p("l"), brightness: 0.5, contrast: 0.5, saturation: 0.5 }],
    composition: [{ key: "seed_learned_composition_3", center_x: 0.5, center_y: 0.5, luminance_balance: 0.5 }],
    graphics: [{ key: "seed_learned_graphics_4", edge_density: 0.1, spatial_variance: 0.1, busyness: 0.1 }],
    temporal: [{ key: "seed_learned_temporal_5", duration: 4, motion_trend: "steady" }],
    technical: [{ key: "seed_learned_technical_6", width: 640, height: 360, fps: 24 }],
    gradient: [{ key: "seed_learned_gradient_7", gradient_type: "angled" }],
    camera: [{ key: "seed_learned_camera_8", motion_type: "static" }],
    transition: [{ key: "seed_learned_transition_9", type: "cut" }],
    audio_semantic: [{ key: "seed_learned_audio_semantic_10", role: "ambient" }],
    ...(jobId ? { job_id: jobId } : {}),
  };
}

/** Mirror of src/knowledge/remote_sync.py::_chunk_discoveries (blends weigh 3). */
export function chunkDiscoveries(payload, maxWeight = 8, blendWeight = 3) {
  const chunks = [];
  let cur = {}; let w = 0;
  const flush = () => { if (w > 0) chunks.push(cur); cur = {}; w = 0; };
  const add = (cat, item, weight, aspect) => {
    if (w > 0 && w + weight > maxWeight) flush();
    if (aspect) { cur.narrative = cur.narrative || {}; (cur.narrative[aspect] = cur.narrative[aspect] || []).push(item); }
    else (cur[cat] = cur[cat] || []).push(item);
    w += weight;
  };
  for (const [cat, items] of Object.entries(payload)) {
    if (cat === "job_id") continue;
    if (cat === "narrative") { for (const [asp, arr] of Object.entries(items)) for (const it of arr) add("narrative", it, 1, asp); continue; }
    for (const it of items) add(cat, it, cat === "blends" ? blendWeight : 1);
  }
  flush();
  if (payload.job_id && chunks.length) chunks[chunks.length - 1].job_id = payload.job_id;
  return chunks;
}

export { pathToFileURL };

/** Bundle one src module for plain-Node unit tests (no workerd) and import it. */
export async function bundleModule(relPath, root = path.resolve(import.meta.dirname, "..", "..")) {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "motion-unit-"));
  const out = path.join(tmp, path.basename(relPath).replace(/\.ts$/, ".mjs"));
  await build({ entryPoints: [path.join(root, relPath)], outfile: out, bundle: true, format: "esm", platform: "node", target: "es2022", logLevel: "error" });
  const mod = await import(pathToFileURL(out).href + "?t=" + Date.now());
  return { mod, cleanup: () => fs.rmSync(tmp, { recursive: true, force: true }) };
}
