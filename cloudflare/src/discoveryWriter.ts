/**
 * Batched, deduplicated, upsert-based writer for POST /api/knowledge/discoveries.
 *
 * Replaces the old per-item SELECT -> UPDATE/INSERT (+ unindexed name-uniqueness scans) loop.
 * Cost model per request (Cloudflare Free D1: 100k rows written / 5M rows read per day):
 *   - 0-1 `SELECT ... FROM name_reserve WHERE name IN (...)` (primary-key lookups) when items need names
 *   - ONE db.batch() holding one upsert per UNIQUE (table, key): `INSERT .. ON CONFLICT DO UPDATE
 *     SET count = count + ? RETURNING count`  -> 1 row written per unique key, no row scans
 *   - learned_blends: deterministic id (sha256 of domain + normalized output) + INSERT OR IGNORE => a repeated blend
 *     writes 0 rows (previously every clip re-inserted ~13 rows + 2 index rows)
 *   - 0-1 `INSERT OR IGNORE INTO name_reserve` batch for novel generated names
 *   - 0 KV operations (no lease, no cache invalidation, no per-post count bump)
 * "Novel" = the RETURNING count equals the delta we sent (a fresh row starts at `delta`).
 */
import type { Env } from "./env";
import {
  getDb,
  ensureLearnedColorsDepthColumn,
  ensureStaticColorsFamilyColumns,
  ensureLearnedDynamicMetaTable,
  bumpRegistryCounts,
} from "./db";
import { uuid } from "./http";
import { blendId } from "./blendId";
import { maybeRunRetention } from "./retention";
import { inventSemanticWord, titleCaseLabel, toTitleCase, sanitizePureSoundKey } from "./naming";
import { classifyColorFamily, classifyColorShade } from "./colorBrowse";

/* eslint-disable @typescript-eslint/no-explicit-any */
type AnyItem = Record<string, any>;
export type DiscoveriesBody = Record<string, any> & { narrative?: Record<string, AnyItem[]>; job_id?: string };

export const DEFAULT_DISCOVERIES_MAX_ITEMS = 40;
const NARRATIVE_ASPECTS = ["genre", "mood", "plots", "settings", "themes", "style", "scene_type"];
const RESULT_KEYS = [
  "static_colors", "static_sound", "narrative", "colors", "blends", "motion", "lighting", "composition",
  "graphics", "temporal", "technical", "audio_semantic", "time", "gradient", "camera", "transition", "depth", "entities",
] as const;

export function maxItemsFromEnv(env: Env): number {
  const raw = Number((env as { DISCOVERIES_MAX_ITEMS?: string }).DISCOVERIES_MAX_ITEMS);
  if (Number.isFinite(raw) && raw >= 3) return Math.min(Math.floor(raw), 80);
  return DEFAULT_DISCOVERIES_MAX_ITEMS;
}

interface Planned {
  cat: string;
  table: string;
  keyCols: string[];
  keyVals: unknown[];
  cols: Record<string, unknown>; // extra insert columns (not id/count/sources_json/name)
  sources: string | null;
  providedName: string | null;
  autoName: "semantic" | "narrative";
  narrativeLabel?: string;
  extraUpdate: string[]; // fragments for ON CONFLICT DO UPDATE SET
  meta?: { aspect: string; depthJson: string };
  delta: number;
  name?: string;
  novel?: boolean;
}

const src = (p?: string) => (p ? JSON.stringify([String(p).slice(0, 80)]) : null);
const nm = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);
const depthOf = (d: unknown): string | null => (d && typeof d === "object" ? JSON.stringify(d) : null);
const COALESCE_DEPTH = "depth_breakdown_json = COALESCE(excluded.depth_breakdown_json, depth_breakdown_json)";

function plan(items: Planned[], seen: Map<string, Planned>, p: Planned): void {
  const id = `${p.table}\u0000${p.keyVals.join("\u0001")}`;
  const prev = seen.get(id);
  if (prev) {
    prev.delta += 1;
    // later depth wins, like the old sequential UPDATE
    if (p.cols.depth_breakdown_json != null) prev.cols.depth_breakdown_json = p.cols.depth_breakdown_json;
    if (p.cols.entity_json != null) prev.cols.entity_json = p.cols.entity_json;
    if (p.meta) prev.meta = p.meta;
    return;
  }
  seen.set(id, p);
  items.push(p);
}

function candidateName(seedBase: number, round: number): string {
  const words: string[] = [];
  const n = round === 0 ? 1 : round < 3 ? 2 : 3;
  for (let i = 0; i < n; i++) {
    let w = inventSemanticWord(seedBase + i * 104729 + round * 7919 + Math.floor(Math.random() * 1e6));
    if (w.length < 4) w = "haven";
    words.push(toTitleCase(w));
  }
  return words.join(" ");
}

async function takenNames(db: D1Database, names: string[]): Promise<Set<string>> {
  const out = new Set<string>();
  const uniq = [...new Set(names)];
  for (let i = 0; i < uniq.length; i += 60) {
    const part = uniq.slice(i, i + 60);
    const res = await db
      .prepare(`SELECT name FROM name_reserve WHERE name IN (${part.map(() => "?").join(",")})`)
      .bind(...part)
      .all<{ name: string }>();
    for (const r of res.results || []) out.add(r.name);
  }
  return out;
}

/** Assign `name` to every planned item that needs one, verifying against name_reserve (PK lookups only). */
async function assignNames(db: D1Database, planned: Planned[], blendNames: Array<{ base: string }>): Promise<string[]> {
  const used = new Set<string>();
  for (const p of planned) {
    if (p.providedName) used.add(p.providedName);
  }
  // 1) Draft names
  const need = planned.filter((p) => !p.providedName);
  const drafts = new Map<Planned, string>();
  for (const p of need) {
    drafts.set(
      p,
      p.autoName === "narrative" ? titleCaseLabel(p.narrativeLabel || "") || candidateName(0, 0) : candidateName(Math.floor(Math.random() * 1e6), 0),
    );
  }
  const blendDrafts = blendNames.map((b) =>
    b.base ? toTitleCase(b.base.trim()) : candidateName(Math.floor(Math.random() * 1e6), 0),
  );
  // 2) Resolve collisions with reserve (<=3 rounds, one statement per round)
  for (let round = 0; round < 3; round++) {
    const all = [...drafts.values(), ...blendDrafts];
    if (!all.length) break;
    const taken = await takenNames(db, all);
    const seenNow = new Set<string>();
    let collided = false;
    const bump = (cur: string, regen: () => string): string => {
      if (taken.has(cur) || seenNow.has(cur) || used.has(cur)) {
        collided = true;
        return regen();
      }
      seenNow.add(cur);
      return cur;
    };
    for (const p of need) {
      if (p.autoName === "narrative") {
        // narrative names are deterministic labels; keep (old behaviour, no uniqueness requirement)
        continue;
      }
      drafts.set(p, bump(drafts.get(p)!, () => candidateName(Math.floor(Math.random() * 1e6), round + 1)));
    }
    for (let i = 0; i < blendDrafts.length; i++) {
      const base = blendNames[i].base;
      blendDrafts[i] = bump(blendDrafts[i], () =>
        base
          ? toTitleCase(inventSemanticWord(Math.abs(hash(base) + (round + 1) * 7919 + i + Math.floor(Math.random() * 1e6))))
          : candidateName(Math.floor(Math.random() * 1e6), round + 1),
      );
    }
    if (!collided) break;
  }
  for (const [p, n] of drafts) p.name = n;
  return blendDrafts;
}

function hash(s: string): number {
  let h = 2166136261;
  for (let c = 0; c < s.length; c++) h = Math.imul(h ^ s.charCodeAt(c), 16777619);
  return Math.abs(h | 0) % 0x7fffffff;
}

export interface DiscoveriesOutcome {
  status: number;
  body: Record<string, unknown>;
}

export async function writeDiscoveries(env: Env, body: DiscoveriesBody): Promise<DiscoveriesOutcome> {
  const db = getDb(env);
  const maxItems = maxItemsFromEnv(env);
  const results: Record<string, number> = Object.fromEntries(RESULT_KEYS.map((k) => [k, 0]));
  let itemsProcessed = 0;
  let truncated = false;
  let dupBlends = 0;

  const jobId = typeof body.job_id === "string" ? body.job_id.trim() : "";
  const narrativeHasItems = Object.values(body.narrative || {}).some((a) => Array.isArray(a) && a.length > 0);
  const listKeys = ["static_colors", "static_sound", "colors", "blends", "motion", "lighting", "composition", "graphics", "temporal", "technical", "audio_semantic", "time", "gradient", "camera", "transition", "depth", "entities"];
  const listHasItems = listKeys.some((k) => Array.isArray(body[k]) && body[k].length > 0);
  if (!listHasItems && !narrativeHasItems) {
    return { status: 201, body: { status: "recorded", results, items_processed: 0 } };
  }

  const familyColsOk = (body.static_colors || []).length > 0 ? await ensureStaticColorsFamilyColumns(db) : false;
  if ((body.colors || []).length > 0) {
    if (!(await ensureLearnedColorsDepthColumn(db))) {
      return { status: 503, body: { error: "learned_colors.depth_breakdown_json is not available yet (D1 ALTER pending). Retry later or add the column in the D1 dashboard." } };
    }
  }

  const planned: Planned[] = [];
  const seen = new Map<string, Planned>();
  const blends: Array<{ b: AnyItem; base: string; id: string }> = [];
  const blendSeen = new Set<string>();

  const take = (_cat: string): boolean => {
    if (itemsProcessed >= maxItems) {
      truncated = true;
      return false;
    }
    return true;
  };
  const done = (cat: string) => {
    results[cat]++;
    itemsProcessed++;
  };

  outer: {
    for (const c of body.static_colors || []) {
      if (!take("static_colors")) break outer;
      const family = classifyColorFamily(c.r, c.g, c.b);
      const cols: Record<string, unknown> = {
        r: c.r, g: c.g, b: c.b,
        brightness: c.brightness ?? null,
        luminance: c.luminance ?? c.brightness ?? null,
        contrast: c.contrast ?? null,
        saturation: c.saturation ?? null,
        chroma: c.chroma ?? c.saturation ?? null,
        hue: c.hue ?? null,
        color_variance: c.color_variance ?? null,
        opacity: c.opacity ?? null,
        depth_breakdown_json: c.depth_breakdown ? JSON.stringify(c.depth_breakdown) : null,
      };
      if (familyColsOk) {
        cols.family = family;
        cols.shade = classifyColorShade(c.r, c.g, c.b, family);
      }
      plan(planned, seen, { cat: "static_colors", table: "static_colors", keyCols: ["color_key"], keyVals: [c.key], cols, sources: src(c.source_prompt), providedName: nm(c.name), autoName: "semantic", extraUpdate: [], delta: 1 });
      done("static_colors");
    }
    for (const s of body.static_sound || []) {
      if (!take("static_sound")) break outer;
      const key = sanitizePureSoundKey(s.key || "");
      plan(planned, seen, {
        cat: "static_sound", table: "static_sound", keyCols: ["sound_key"], keyVals: [key],
        cols: { amplitude: s.amplitude ?? null, weight: s.weight ?? null, tone: s.tone ?? null, timbre: s.timbre ?? null, depth_breakdown_json: s.depth_breakdown ? JSON.stringify(s.depth_breakdown) : null, strength_pct: s.strength_pct ?? s.amplitude ?? s.weight ?? null },
        sources: src(s.source_prompt), providedName: nm(s.name), autoName: "semantic", extraUpdate: [], delta: 1,
      });
      done("static_sound");
    }
    for (const aspect of NARRATIVE_ASPECTS) {
      for (const item of body.narrative?.[aspect] || []) {
        if (!take("narrative")) break outer;
        const key = (item.key || "").trim().toLowerCase();
        if (!key) continue;
        const valueStr = String(item.value ?? item.key ?? key).slice(0, 200);
        plan(planned, seen, {
          cat: "narrative", table: "narrative_entries", keyCols: ["aspect", "entry_key"], keyVals: [aspect, key],
          cols: { value: valueStr }, sources: src(item.source_prompt), providedName: nm(item.name), autoName: "narrative", narrativeLabel: valueStr || key, extraUpdate: [], delta: 1,
        });
        done("narrative");
      }
    }
    for (const c of body.colors || []) {
      if (!take("colors")) break outer;
      plan(planned, seen, {
        cat: "colors", table: "learned_colors", keyCols: ["color_key"], keyVals: [c.key],
        cols: { r: c.r, g: c.g, b: c.b, depth_breakdown_json: depthOf(c.depth_breakdown) },
        sources: src(c.source_prompt), providedName: nm(c.name), autoName: "semantic", extraUpdate: [COALESCE_DEPTH], delta: 1,
      });
      done("colors");
    }
    for (const b of body.blends || []) {
      if (!take("blends")) break outer;
      const id = await blendId(b.domain, b.output);
      if (blendSeen.has(id)) {
        dupBlends++;
      } else {
        blendSeen.add(id);
        blends.push({ b, base: nm(b.name) || "", id });
      }
      done("blends");
    }
    const simple = (cat: string, table: string, keyCol: string, list: AnyItem[] | undefined, cols: (i: AnyItem) => Record<string, unknown>, extra: string[] = [], meta?: (i: AnyItem) => Planned["meta"]) => {
      for (const i of list || []) {
        if (!take(cat)) return false;
        plan(planned, seen, { cat, table, keyCols: [keyCol], keyVals: [i.key], cols: cols(i), sources: src(i.source_prompt), providedName: nm(i.name), autoName: "semantic", extraUpdate: extra, meta: meta?.(i), delta: 1 });
        done(cat);
      }
      return true;
    };
    if (!simple("time", "learned_time", "profile_key", body.time, (t) => ({ duration: t.duration, fps: t.fps }))) break outer;
    if (!simple("motion", "learned_motion", "profile_key", body.motion, (m) => ({ motion_level: m.motion_level ?? 0, motion_std: m.motion_std ?? 0, motion_trend: m.motion_trend ?? "steady", motion_direction: m.motion_direction ?? "neutral", motion_rhythm: m.motion_rhythm ?? "steady", depth_breakdown_json: depthOf(m.depth_breakdown) }), [COALESCE_DEPTH])) break outer;
    if (!simple("lighting", "learned_lighting", "profile_key", body.lighting, (l) => ({ brightness: l.brightness, contrast: l.contrast, saturation: l.saturation, depth_breakdown_json: depthOf(l.depth_breakdown) }), [COALESCE_DEPTH])) break outer;
    const metaOf = (aspect: string) => (i: AnyItem) => {
      const d = depthOf(i.depth_breakdown);
      return d ? { aspect, depthJson: d } : undefined;
    };
    if (!simple("composition", "learned_composition", "profile_key", body.composition, (c) => ({ center_x: c.center_x, center_y: c.center_y, luminance_balance: c.luminance_balance }), [], metaOf("composition"))) break outer;
    if (!simple("graphics", "learned_graphics", "profile_key", body.graphics, (g) => ({ edge_density: g.edge_density, spatial_variance: g.spatial_variance, busyness: g.busyness }), [], metaOf("graphics"))) break outer;
    if (!simple("temporal", "learned_temporal", "profile_key", body.temporal, (t) => ({ duration: t.duration, motion_trend: t.motion_trend }), [], metaOf("temporal"))) break outer;
    if (!simple("technical", "learned_technical", "profile_key", body.technical, (t) => ({ width: t.width, height: t.height, fps: t.fps }), [], metaOf("technical"))) break outer;
    if (!simple("audio_semantic", "learned_audio_semantic", "profile_key", body.audio_semantic, (a) => ({ role: a.role || "ambient" }))) break outer;
    if (!simple("gradient", "learned_gradient", "profile_key", body.gradient, (g) => ({ gradient_type: g.gradient_type ?? "angled", strength: g.strength ?? null, depth_breakdown_json: depthOf(g.depth_breakdown) }), [COALESCE_DEPTH])) break outer;
    if (!simple("camera", "learned_camera", "profile_key", body.camera, (c) => ({ motion_type: c.motion_type ?? "static", speed: c.speed ?? null, depth_breakdown_json: depthOf(c.depth_breakdown) }), [COALESCE_DEPTH])) break outer;
    if (!simple("transition", "learned_transition", "profile_key", body.transition, (t) => ({ type: t.type ?? "cut", duration_seconds: t.duration_seconds ?? null }))) break outer;
    if (!simple("depth", "learned_depth", "profile_key", body.depth, (d) => ({ parallax_strength: d.parallax_strength ?? null, layer_count: d.layer_count ?? null }))) break outer;
    simple(
      "entities", "learned_entities", "profile_key", body.entities,
      (e) => ({ kind: e.kind || "circle", trajectory: e.trajectory ?? "none", bounce: e.bounce === true || e.bounce === 1 ? 1 : 0, color_hint: e.color_hint ?? null, label: e.label ?? null, directionality: e.directionality ?? "none", entity_json: e.entity_json && typeof e.entity_json === "object" ? JSON.stringify(e.entity_json) : null }),
      ["entity_json = COALESCE(excluded.entity_json, entity_json)"],
    );
  }

  const blendNameList = blends.map((x) => ({ base: x.base }));
  const resolvedBlendNames = blends.length || planned.some((p) => !p.providedName) ? await assignNames(db, planned, blendNameList) : [];
  // blends whose client supplied no name get a generated one
  const stmts: D1PreparedStatement[] = [];
  const upsertIdx: number[] = [];
  for (const p of planned) {
    const colNames = Object.keys(p.cols);
    const allCols = ["id", ...p.keyCols, ...colNames, "count", "sources_json", "name"];
    const vals = [uuid(), ...p.keyVals, ...colNames.map((k) => p.cols[k]), p.delta, p.sources, p.providedName ?? p.name ?? null];
    const sql = `INSERT INTO ${p.table} (${allCols.join(", ")}) VALUES (${allCols.map(() => "?").join(", ")}) ON CONFLICT(${p.keyCols.join(", ")}) DO UPDATE SET count = count + excluded.count${p.extraUpdate.length ? ", " + p.extraUpdate.join(", ") : ""} RETURNING count`;
    upsertIdx.push(stmts.length);
    stmts.push(db.prepare(sql).bind(...vals));
  }
  const metaPlans = planned.filter((p) => p.meta);
  if (metaPlans.length) await ensureLearnedDynamicMetaTable(db);
  for (const p of metaPlans) {
    stmts.push(
      db
        .prepare(
          `INSERT INTO learned_dynamic_meta (aspect, profile_key, depth_breakdown_json, updated_at) VALUES (?, ?, ?, datetime('now'))
           ON CONFLICT(aspect, profile_key) DO UPDATE SET depth_breakdown_json = excluded.depth_breakdown_json, updated_at = datetime('now')
           WHERE learned_dynamic_meta.depth_breakdown_json IS NOT excluded.depth_breakdown_json`,
        )
        .bind(p.meta!.aspect, p.keyVals[0], p.meta!.depthJson),
    );
  }
  const blendIdx: number[] = [];
  blends.forEach((x, i) => {
    const b = x.b;
    blendIdx.push(stmts.length);
    stmts.push(
      db
        .prepare("INSERT OR IGNORE INTO learned_blends (id, name, domain, inputs_json, output_json, primitive_depths_json, source_prompt) VALUES (?, ?, ?, ?, ?, ?, ?)")
        .bind(x.id, resolvedBlendNames[i] || "Haven", b.domain, JSON.stringify(b.inputs), JSON.stringify(b.output), b.primitive_depths ? JSON.stringify(b.primitive_depths) : null, String(b.source_prompt || "").slice(0, 120)),
    );
  });
  if (jobId) {
    // One row per job (idx_discovery_runs_job_id lookup), and only when the job exists: a missing job used to be a
  // swallowed FK error; inside an atomic batch it would roll back every upsert, so it must be a no-op instead.
  stmts.push(
    db
      .prepare(
        "INSERT INTO discovery_runs (id, job_id) SELECT ?, ? WHERE EXISTS (SELECT 1 FROM jobs WHERE id = ?) AND NOT EXISTS (SELECT 1 FROM discovery_runs WHERE job_id = ?)",
      )
      .bind(uuid(), jobId, jobId, jobId),
  );
  }

  let novel: Record<string, number> = { static_colors: 0, static_sound: 0, learned_colors: 0 };
  const reserveNames: string[] = [];
  let out: D1Result[] | undefined;
  if (stmts.length) {
    const res = await db.batch(stmts);
    out = res;
    planned.forEach((p, i) => {
      const row = (res[upsertIdx[i]]?.results || [])[0] as { count?: number } | undefined;
      p.novel = !!row && row.count === p.delta;
      if (p.novel) {
        if (p.cat === "static_colors") novel.static_colors++;
        if (p.cat === "static_sound") novel.static_sound++;
        if (p.cat === "colors") novel.learned_colors++;
        if (!p.providedName && p.name && p.autoName === "semantic") reserveNames.push(p.name);
      }
    });
  }
  // Only reserve generated names of blends that were actually inserted (an ignored duplicate keeps its older name).
  let newBlends = 0;
  blends.forEach((x, i) => {
    const inserted = !stmts.length || ((out?.[blendIdx[i]]?.meta as { changes?: number } | undefined)?.changes ?? 1) > 0;
    if (inserted) newBlends++;
    if (inserted && !x.base && resolvedBlendNames[i]) reserveNames.push(resolvedBlendNames[i]);
  });
  if (reserveNames.length) {
    try {
      await db.batch(reserveNames.map((n) => db.prepare("INSERT OR IGNORE INTO name_reserve (name) VALUES (?)").bind(n)));
    } catch {
      /* reserve is best-effort, like before */
    }
  }
  if (novel.static_colors || novel.static_sound || novel.learned_colors) {
    await bumpRegistryCounts(env, novel);
  }
  const resp: Record<string, unknown> = { status: "recorded", results, items_processed: itemsProcessed, unique_rows: planned.length + blends.length, deduped_blends: dupBlends, new_blends: newBlends, novel };
  if (truncated) resp.truncated = true;
  // Opportunistic log retention (no cron available on the free plan); at most once/day/table, tiny write budget, never throws.
  await maybeRunRetention(env);
  return { status: 201, body: resp };
}