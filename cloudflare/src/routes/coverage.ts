/**
 * Exact colour-cell coverage (bit-chunk sync + report + cell lookup). Additive; nothing else depends on it.
 *
 *   POST /api/coverage/color/chunks   OR-merge up to MAX_CHUNKS_PER_REQUEST 64 KiB chunks (auth required)
 *   GET  /api/coverage/color          observed / verified / declared counts (reads 32 tiny count rows, cached)
 *   GET  /api/coverage/color/cell     ?rgb=r,g,b | ?hex=#rrggbb | ?id=N | ?ids=1,2,3  (<= 64): recorded tier per cell
 *
 * Free-tier discipline: one row per CHUNK (never per colour); merges write only chunks whose bits changed; every
 * handler degrades to a 200 {available:false} when migrations_pending/0101_color_coverage_chunks.sql is not applied.
 */
import type { Env } from "../env";
import { getDb } from "../db";
import { json, err } from "../http";
import { getSnapshot } from "../snapshotCache";
import { dbFullResponse, isDbFullError, isFreeTierLimitError, limitResponse } from "../limits";
import {
  COLOR_N_CHUNKS,
  COLOR_PLANES,
  COLOR_SPACE_ID,
  COLOR_SPACE_SIZE,
  COLOR_SPACE_VERSION,
  chunkOf,
  decodePlane,
  idToHex,
  idToRgb,
  mergeChunk,
  parseCell,
  rowId,
  tierOf,
  toBytes,
  type ChunkPlanes,
} from "../colorCells";

/** CPU guard: a merge is ~50k word ops per chunk; 8 chunks stay far under the 10 ms free-tier budget. */
export const MAX_CHUNKS_PER_REQUEST = 8;
const MAX_LOOKUP_IDS = 64;
const SUMMARY_SOFT_TTL_SEC = 300;
const CHUNK_CACHE_TTL_MS = 5 * 60 * 1000;
const CHUNK_CACHE_MAX = 8;

const chunkCache = new Map<number, { at: number; planes: ChunkPlanes | null }>();
export function __resetColorChunkCache(): void {
  chunkCache.clear();
}

function isMissingTable(e: unknown): boolean {
  return /no such table/i.test(String((e as { message?: string })?.message ?? e));
}

function unavailable(extra: Record<string, unknown> = {}): Response {
  return json({ available: false, reason: "table_missing", space: COLOR_SPACE_ID, migration: "migrations_pending/0101_color_coverage_chunks.sql", ...extra });
}

interface CountsRow {
  chunk_idx: number;
  version: number;
  observed_n: number;
  verified_n: number;
  declared_n: number;
  covered_n: number;
  declared_only_n: number;
  updated_at: string | null;
}

async function buildSummary(env: Env, perChunk: boolean): Promise<Record<string, unknown>> {
  const db = getDb(env);
  const res = await db
    .prepare(
      "SELECT chunk_idx, version, observed_n, verified_n, declared_n, covered_n, declared_only_n, updated_at FROM color_coverage_chunks WHERE space_id = ? ORDER BY chunk_idx",
    )
    .bind(COLOR_SPACE_ID)
    .all<CountsRow>();
  const rows = res.results || [];
  const sum = (k: keyof CountsRow) => rows.reduce((a, r) => a + (Number(r[k]) || 0), 0);
  const covered = sum("covered_n");
  let updated: string | null = null;
  for (const r of rows) if (r.updated_at && (!updated || r.updated_at > updated)) updated = r.updated_at;
  const out: Record<string, unknown> = {
    available: true,
    space: COLOR_SPACE_ID,
    version: COLOR_SPACE_VERSION,
    total_cells: COLOR_SPACE_SIZE,
    observed: sum("observed_n"),
    verified: sum("verified_n"),
    declared: sum("declared_n"),
    declared_only: sum("declared_only_n"),
    covered,
    covered_pct: Math.round((covered / COLOR_SPACE_SIZE) * 1e8) / 1e6,
    chunks_synced: rows.length,
    chunks_total: COLOR_N_CHUNKS,
    updated_at: updated,
    note: "covered = observed OR verified (declared alone never counts as coverage)",
  };
  if (perChunk) {
    out.chunks = rows.map((r) => ({ idx: r.chunk_idx, observed: r.observed_n, verified: r.verified_n, declared: r.declared_n, covered: r.covered_n }));
  }
  return out;
}

async function loadChunk(env: Env, idx: number): Promise<ChunkPlanes | null> {
  const hit = chunkCache.get(idx);
  if (hit && Date.now() - hit.at < CHUNK_CACHE_TTL_MS) return hit.planes;
  const row = await getDb(env)
    .prepare("SELECT observed, verified, declared FROM color_coverage_chunks WHERE id = ?")
    .bind(rowId(idx))
    .first<{ observed: unknown; verified: unknown; declared: unknown }>();
  const planes: ChunkPlanes | null = row ? { observed: toBytes(row.observed), verified: toBytes(row.verified), declared: toBytes(row.declared) } : null;
  if (chunkCache.size >= CHUNK_CACHE_MAX) chunkCache.delete(chunkCache.keys().next().value as number);
  chunkCache.set(idx, { at: Date.now(), planes });
  return planes;
}

interface ChunkBody {
  idx: number;
  observed?: string;
  verified?: string;
  declared?: string;
}

async function handlePush(request: Request, env: Env): Promise<Response> {
  let body: { space?: string; version?: number; enc?: string; chunks?: ChunkBody[] };
  try {
    body = await request.json();
  } catch {
    return err("Invalid JSON", 400);
  }
  if (body.space !== COLOR_SPACE_ID) return err(`space must be ${COLOR_SPACE_ID}`, 400);
  if (body.version !== COLOR_SPACE_VERSION) {
    return json({ error: "version_mismatch", expected: COLOR_SPACE_VERSION, got: body.version ?? null, space: COLOR_SPACE_ID }, 409);
  }
  const chunks = Array.isArray(body.chunks) ? body.chunks : [];
  if (chunks.length === 0) return err("chunks required", 400);
  if (chunks.length > MAX_CHUNKS_PER_REQUEST) {
    return json({ error: "too_many_chunks", max: MAX_CHUNKS_PER_REQUEST, got: chunks.length }, 413);
  }
  const enc = body.enc || "zlib";
  if (enc !== "zlib" && enc !== "raw") return err("enc must be zlib or raw", 400);
  const seen = new Set<number>();
  const decoded: { idx: number; planes: Partial<ChunkPlanes> }[] = [];
  try {
    for (const c of chunks) {
      if (!Number.isInteger(c.idx) || c.idx < 0 || c.idx >= COLOR_N_CHUNKS || seen.has(c.idx)) return err("bad or duplicate chunk idx", 400);
      seen.add(c.idx);
      const planes: Partial<ChunkPlanes> = {};
      for (const p of COLOR_PLANES) {
        const bytes = await decodePlane(c[p], enc);
        if (bytes) planes[p] = bytes;
      }
      decoded.push({ idx: c.idx, planes });
    }
  } catch (e) {
    return err(String((e as Error).message || e), 400);
  }

  const db = getDb(env);
  try {
    const stmts: D1PreparedStatement[] = [];
    const changedIdx: number[] = [];
    const newBits = { observed: 0, verified: 0, declared: 0 };
    for (const { idx, planes } of decoded) {
      chunkCache.delete(idx);
      const row = await db
        .prepare("SELECT observed, verified, declared, observed_n, verified_n, declared_n FROM color_coverage_chunks WHERE id = ?")
        .bind(rowId(idx))
        .first<{ observed: unknown; verified: unknown; declared: unknown; observed_n: number; verified_n: number; declared_n: number }>();
      const existing: ChunkPlanes | null = row ? { observed: toBytes(row.observed), verified: toBytes(row.verified), declared: toBytes(row.declared) } : null;
      const { merged, changed, counts } = mergeChunk(existing, planes);
      if (!changed) continue; // nothing new: ZERO writes for this chunk
      changedIdx.push(idx);
      newBits.observed += counts.observed_n - (row?.observed_n ?? 0);
      newBits.verified += counts.verified_n - (row?.verified_n ?? 0);
      newBits.declared += counts.declared_n - (row?.declared_n ?? 0);
      stmts.push(
        db
          .prepare(
            `INSERT INTO color_coverage_chunks
               (id, space_id, chunk_idx, version, observed, verified, declared,
                observed_n, verified_n, declared_n, covered_n, declared_only_n, updated_at)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
             ON CONFLICT(id) DO UPDATE SET
               version = excluded.version, observed = excluded.observed, verified = excluded.verified,
               declared = excluded.declared, observed_n = excluded.observed_n, verified_n = excluded.verified_n,
               declared_n = excluded.declared_n, covered_n = excluded.covered_n,
               declared_only_n = excluded.declared_only_n, updated_at = excluded.updated_at`,
          )
          .bind(
            rowId(idx), COLOR_SPACE_ID, idx, COLOR_SPACE_VERSION,
            merged.observed.buffer, merged.verified.buffer, merged.declared.buffer,
            counts.observed_n, counts.verified_n, counts.declared_n, counts.covered_n, counts.declared_only_n,
          ),
      );
    }
    if (stmts.length) await db.batch(stmts);
    return json({
      recorded: true,
      space: COLOR_SPACE_ID,
      version: COLOR_SPACE_VERSION,
      chunks_received: decoded.length,
      chunks_changed: changedIdx.length,
      changed: changedIdx,
      rows_written: stmts.length,
      new_bits: newBits,
    });
  } catch (e) {
    if (isMissingTable(e)) return unavailable({ recorded: false });
    if (isDbFullError(e)) return dbFullResponse("POST", { recorded: false });
    if (isFreeTierLimitError(e)) return limitResponse("POST", { recorded: false });
    throw e;
  }
}

async function handleLookup(url: URL, env: Env): Promise<Response> {
  const sp = url.searchParams;
  const ids: number[] = [];
  const multi = !!sp.get("ids");
  if (multi) {
    const parts = sp.get("ids")!.split(",").filter(Boolean);
    if (parts.length > MAX_LOOKUP_IDS) return err(`at most ${MAX_LOOKUP_IDS} ids`, 400);
    for (const p of parts) {
      const id = parseCell({ id: p });
      if (id == null) return err("invalid id: " + p, 400);
      ids.push(id);
    }
  } else {
    const id = parseCell({ id: sp.get("id"), rgb: sp.get("rgb"), hex: sp.get("hex") });
    if (id == null) return err("give id=N, rgb=r,g,b or hex=#rrggbb (or ids=a,b,c)", 400);
    ids.push(id);
  }
  try {
    const cells = [];
    for (const id of ids) {
      const planes = await loadChunk(env, chunkOf(id));
      const t = planes ? tierOf(planes, id) : { tier: "none" as const, observed: false, verified: false, declared: false };
      cells.push({ id, rgb: idToRgb(id), hex: idToHex(id), ...t, chunk: chunkOf(id), chunk_synced: planes != null });
    }
    const base = { available: true, space: COLOR_SPACE_ID, version: COLOR_SPACE_VERSION };
    const res = json(multi ? { ...base, cells } : { ...base, ...cells[0] });
    res.headers.set("Cache-Control", "public, max-age=300");
    return res;
  } catch (e) {
    if (isMissingTable(e)) return unavailable();
    if (isFreeTierLimitError(e)) return limitResponse("GET");
    throw e;
  }
}

export async function handleCoverageRoutes(request: Request, env: Env, path: string): Promise<Response | null> {
  if (!path.startsWith("/api/coverage/color")) return null;
  const url = new URL(request.url);
  if (path === "/api/coverage/color/chunks") {
    if (request.method !== "POST") return err("Method not allowed", 405);
    return handlePush(request, env);
  }
  if (request.method !== "GET") return err("Method not allowed", 405);
  if (path === "/api/coverage/color/cell") return handleLookup(url, env);
  if (path === "/api/coverage/color") {
    const perChunk = url.searchParams.get("chunks") === "1";
    try {
      const snap = await getSnapshot(env, `coverage:color:${perChunk ? "chunks" : "sum"}`, { softTtlSec: SUMMARY_SOFT_TTL_SEC, hardTtlSec: 86400 }, () => buildSummary(env, perChunk));
      const res = json(snap.value);
      res.headers.set("Cache-Control", "public, max-age=120");
      return res;
    } catch (e) {
      if (isMissingTable(e)) return unavailable();
      if (isFreeTierLimitError(e)) return limitResponse("GET");
      throw e;
    }
  }
  return null;
}