/**
 * Opacity-plane + cross-axis coverage aggregates (compact: <= 32 rows, one per allow-listed key).
 *
 *   POST /api/coverage/axes   {items:[{key, seen, universe}]}  upsert changed keys only (auth required, global)
 *   GET  /api/coverage/axes   all aggregates (snapshot-cached with stale-on-error, Cache-Control 300 s)
 *
 * Degrades to 200 {available:false} until migrations_pending/0104_axis_coverage.sql is applied.
 */
import type { Env } from "../env";
import { getDb } from "../db";
import { rowsWrittenOf } from "../d1Meta";
import { json, err } from "../http";
import { getSnapshot } from "../snapshotCache";
import { dbFullResponse, isDbFullError, isFreeTierLimitError, limitResponse } from "../limits";

export const OPACITY_LEVELS = 16;
export const OPACITY_SIZE = 524288;
export const CROSS_AXES = ["audio_mood", "camera_motion", "genre", "lighting_preset", "motion_type", "palette_name"] as const;

function buildKeys(): string[] {
  const keys: string[] = ["opacity.total"];
  for (let i = 0; i < OPACITY_LEVELS; i++) keys.push(`opacity.level.${i}`);
  const ax = [...CROSS_AXES].sort();
  for (let i = 0; i < ax.length; i++) for (let j = i + 1; j < ax.length; j++) keys.push(`pair.${ax[i]}x${ax[j]}`);
  return keys;
}
export const AXES_KEYS: readonly string[] = buildKeys();
const KEY_ID = new Map(AXES_KEYS.map((k, i) => [k, i] as const));
const MAX_COUNT = 1_000_000_000;
const SOFT_TTL_SEC = 600;

function isMissingTable(e: unknown): boolean {
  return /no such table/i.test(String((e as { message?: string })?.message ?? e));
}
function unavailable(extra: Record<string, unknown> = {}): Response {
  return json({ available: false, reason: "table_missing", migration: "migrations_pending/0104_axis_coverage.sql", ...extra });
}

interface Row { id: number; key: string; seen: number; universe: number; updated_at: string | null }

async function buildSummary(env: Env): Promise<Record<string, unknown>> {
  const res = await getDb(env).prepare("SELECT id, key, seen, universe, updated_at FROM axis_coverage ORDER BY id").all<Row>();
  const rows = res.results || [];
  const by = new Map(rows.map((r) => [r.key, r]));
  let updated: string | null = null;
  for (const r of rows) if (r.updated_at && (!updated || r.updated_at > updated)) updated = r.updated_at;
  const pct = (s: number, u: number) => (u > 0 ? Math.round((s / u) * 1e4) / 1e2 : 0);
  const tot = by.get("opacity.total");
  const levels = [];
  for (let i = 0; i < OPACITY_LEVELS; i++) {
    const r = by.get(`opacity.level.${i}`);
    levels.push({ level: i, alpha_min: i * 16, alpha_max: i * 16 + 15, seen: r?.seen ?? 0, universe: r?.universe ?? OPACITY_SIZE / OPACITY_LEVELS });
  }
  const pairs = AXES_KEYS.filter((k) => k.startsWith("pair.")).map((k) => {
    const r = by.get(k);
    const [a, b] = k.slice(5).split("x");
    return { pair: k.slice(5), a, b, seen: r?.seen ?? 0, universe: r?.universe ?? 0, pct: pct(r?.seen ?? 0, r?.universe ?? 0) };
  });
  return {
    available: true,
    opacity: { space: "color.L1.a4o", size: OPACITY_SIZE, covered: tot?.seen ?? 0, pct: pct(tot?.seen ?? 0, OPACITY_SIZE), levels },
    cross_axis: { pairs, note: "universe = product of distinct values seen on each axis (grows as axes grow)" },
    keys_synced: rows.length,
    updated_at: updated,
  };
}

async function handlePush(request: Request, env: Env): Promise<Response> {
  let body: { items?: { key?: string; seen?: number; universe?: number }[] };
  try {
    body = await request.json();
  } catch {
    return err("Invalid JSON", 400);
  }
  const items = Array.isArray(body.items) ? body.items : [];
  if (items.length === 0) return err("items required", 400);
  if (items.length > AXES_KEYS.length) return json({ error: "too_many_items", max: AXES_KEYS.length }, 413);
  const clean = new Map<number, { key: string; seen: number; universe: number }>();
  for (const it of items) {
    const id = KEY_ID.get(String(it.key ?? ""));
    const seen = Number(it.seen), universe = Number(it.universe ?? 0);
    if (id === undefined) return err("unknown key: " + String(it.key), 400);
    if (!Number.isInteger(seen) || seen < 0 || seen > MAX_COUNT || !Number.isInteger(universe) || universe < 0 || universe > MAX_COUNT) {
      return err("seen/universe must be non-negative integers", 400);
    }
    clean.set(id, { key: it.key as string, seen, universe });
  }
  const db = getDb(env);
  try {
    const existing = await db.prepare("SELECT id, seen, universe FROM axis_coverage").all<{ id: number; seen: number; universe: number }>();
    const cur = new Map((existing.results || []).map((r) => [r.id, r]));
    const stmts: D1PreparedStatement[] = [];
    for (const [id, v] of clean) {
      const old = cur.get(id);
      const seen = Math.max(old?.seen ?? 0, v.seen);
      const universe = Math.max(old?.universe ?? 0, v.universe);
      if (old && old.seen === seen && old.universe === universe) continue; // unchanged: zero writes
      const kind = v.key.startsWith("pair.") ? "pair" : "opacity";
      stmts.push(
        db
          .prepare(
            `INSERT INTO axis_coverage (id, kind, key, seen, universe, updated_at) VALUES (?, ?, ?, ?, ?, datetime('now'))
             ON CONFLICT(id) DO UPDATE SET seen = excluded.seen, universe = excluded.universe, updated_at = excluded.updated_at`,
          )
          .bind(id, kind, v.key, seen, universe),
      );
    }
    const written = stmts.length ? await db.batch(stmts) : [];
    return json({ recorded: true, items_received: clean.size, items_changed: stmts.length, rows_written: rowsWrittenOf(written) });
  } catch (e) {
    if (isMissingTable(e)) return unavailable({ recorded: false, rows_written: 0 });
    if (isDbFullError(e)) return dbFullResponse("POST", { recorded: false });
    if (isFreeTierLimitError(e)) return limitResponse("POST", { recorded: false });
    throw e;
  }
}

export async function handleAxesCoverageRoutes(request: Request, env: Env, path: string): Promise<Response | null> {
  if (path !== "/api/coverage/axes") return null;
  if (request.method === "POST") return handlePush(request, env);
  if (request.method !== "GET") return err("Method not allowed", 405);
  try {
    const snap = await getSnapshot(env, "coverage:axes", { softTtlSec: SOFT_TTL_SEC, hardTtlSec: 86400, swrSec: 3600 }, () => buildSummary(env));
    const res = json(snap.value);
    res.headers.set("Cache-Control", "public, max-age=300");
    return res;
  } catch (e) {
    if (isMissingTable(e)) return unavailable();
    if (isFreeTierLimitError(e)) return limitResponse("GET");
    throw e;
  }
}
