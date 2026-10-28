/**
 * Bounded, cursor-based read of the web job queue (GET /api/jobs?status=pending), for the free-tier D1 read budget.
 *
 * Incident: `SELECT ... FROM jobs WHERE status='pending' AND (workflow_type IS NULL OR workflow_type='web') ORDER BY rowid
 * LIMIT ?` read ~31k rows per call (4.19M of ~4.4M rows in 6 h). idx_jobs_status is (status, rowid) only, so the
 * workflow_type filter runs AFTER the index walk, and ~31k loop-owned jobs (workflow_type explorer/exploiter/main/cartoon)
 * that never reached `completed` (rejected duplicate clips, render errors, containers stopped mid-iteration) sit at the
 * low rowids, in front of every web job. LIMIT cannot stop the walk because the rows it skips never qualify.
 *
 * Why a cursor is safe: a job's status only moves pending -> completed/abandoned and its workflow_type never changes,
 * and new rows always get a larger rowid. So once a window of pending rows has been inspected and found unclaimable,
 * nothing at or below that rowid can ever become claimable, and later scans start after it (`rowid > cursor`, a range seek
 * on idx_jobs_status). The cursor lives in this isolate's memory and the Cache API (free, per colo) and expires after
 * CLAIM_CURSOR_TTL_SEC so a reused rowid (retention deleting the newest rows) can only be missed for that long.
 * Worst case after a cold cursor: CLAIM_MAX_WINDOWS x CLAIM_WINDOW_ROWS rows per request, and the cursor advances, so a
 * backlog of N junk rows costs N reads once (not per poll).
 *
 * No double claim: this is a read-only listing. The queue consumer finishes a job through POST /api/jobs/:id/upload|complete,
 * which now update `WHERE id = ? AND status = 'pending'` and report 400 when another worker got there first.
 */
import type { Env } from "./env";
import { getDb } from "./db";
import { getSnapshot } from "./snapshotCache";

export const CLAIM_WINDOW_ROWS = 100;
export const CLAIM_MAX_WINDOWS = 20;
export const CLAIM_FETCH_LIMIT = 100;
export const CLAIM_POSITIVE_TTL_SEC = 5;
export const CLAIM_NEGATIVE_TTL_SEC = 60;
/** A scan that ran out of windows before reaching the end of the queue is NOT proof of emptiness: re-scan soon. */
export const CLAIM_INCOMPLETE_TTL_SEC = 3;
export const CLAIM_STALE_ON_ERROR_SEC = 3600;
/** Retry hint for clients when D1 is quota-blocked and a stale answer is served. */
export const CLAIM_DEGRADED_POLL_SEC = 300;
export const CLAIM_CURSOR_TTL_SEC = 6 * 3600;
export const PENDING_CACHE_KEY = "jobs:claim:v2:pending";
const CURSOR_KEY = "jobs:claim:v2:cursor";
const CURSOR_ORIGIN = "https://jobs-cursor.motion.invalid/";

export interface PendingJob {
  id: string;
  prompt: string;
  duration_seconds: number | null;
  created_at: string;
}

export interface PendingScan {
  jobs: PendingJob[];
  /** true: the scan either found jobs or reached the end of the pending rows (an empty list really means "none"). */
  complete: boolean;
  scanned: number;
}

/** Window query: `rowid > ?` + `status = 'pending'` is a range seek on idx_jobs_status; non-claimable rows return NULL id. */
export const WINDOW_SQL =
  "SELECT rowid AS rid, " +
  "CASE WHEN workflow_type IS NULL OR workflow_type = 'web' THEN id END AS id, " +
  "CASE WHEN workflow_type IS NULL OR workflow_type = 'web' THEN prompt END AS prompt, " +
  "CASE WHEN workflow_type IS NULL OR workflow_type = 'web' THEN duration_seconds END AS duration_seconds, " +
  "CASE WHEN workflow_type IS NULL OR workflow_type = 'web' THEN created_at END AS created_at " +
  "FROM jobs WHERE status = 'pending' AND rowid > ? ORDER BY rowid ASC LIMIT ?";

/** Used instead when the optional partial index (migrations_pending/0102) exists: its WHERE must match this text's terms. */
export const PARTIAL_INDEX_SQL =
  "SELECT rowid AS rid, id, prompt, duration_seconds, created_at FROM jobs " +
  "WHERE status = 'pending' AND (workflow_type IS NULL OR workflow_type = 'web') AND rowid > ? ORDER BY rowid ASC LIMIT ?";

type WindowRow = { rid: number; id: string | null; prompt: string | null; duration_seconds: number | null; created_at: string | null };

const memCursor = { rid: 0, at: 0 };

function cacheApi(): Cache | null {
  try {
    return (globalThis as { caches?: { default?: Cache } }).caches?.default ?? null;
  } catch {
    return null;
  }
}

/** Test hook. */
export function __resetClaimCursor(): void {
  memCursor.rid = 0;
  memCursor.at = 0;
}

export async function readCursor(): Promise<number> {
  const now = Date.now();
  let best = now - memCursor.at < CLAIM_CURSOR_TTL_SEC * 1000 ? memCursor.rid : 0;
  const c = cacheApi();
  if (c) {
    try {
      const hit = await c.match(new Request(CURSOR_ORIGIN + CURSOR_KEY));
      if (hit) {
        const at = Number(hit.headers.get("x-cursor-at") || 0);
        const rid = Number(await hit.text());
        if (at && Number.isFinite(rid) && now - at < CLAIM_CURSOR_TTL_SEC * 1000 && rid > best) {
          best = rid;
          memCursor.rid = rid;
          memCursor.at = at;
        }
      }
    } catch {
      /* Cache API unavailable: memory only */
    }
  }
  return best;
}

async function writeCursor(rid: number): Promise<void> {
  // Monotonic: concurrent isolates may only ever move it forward.
  if (rid <= 0 || (rid <= memCursor.rid && Date.now() - memCursor.at < CLAIM_CURSOR_TTL_SEC * 1000 / 2)) return;
  const now = Date.now();
  memCursor.rid = Math.max(rid, memCursor.rid);
  memCursor.at = now;
  const c = cacheApi();
  if (!c) return;
  try {
    await c.put(
      new Request(CURSOR_ORIGIN + CURSOR_KEY),
      new Response(String(memCursor.rid), {
        headers: { "Cache-Control": `public, max-age=${CLAIM_CURSOR_TTL_SEC}`, "x-cursor-at": String(now) },
      }),
    );
  } catch {
    /* best effort */
  }
}

/** Scan forward from the cursor, window by window, until a claimable job, the end of the queue, or the window budget. */
export async function scanPendingWeb(env: Env, limit = CLAIM_FETCH_LIMIT): Promise<PendingScan> {
  const db = getDb(env);
  const partial = (env as unknown as Record<string, string | undefined>).JOBS_PARTIAL_INDEX === "1";
  const start = partial ? 0 : await readCursor();
  let cur = start;
  let scanned = 0;
  for (let w = 0; w < (partial ? 1 : CLAIM_MAX_WINDOWS); w++) {
    const res = await db
      .prepare(partial ? PARTIAL_INDEX_SQL : WINDOW_SQL)
      .bind(cur, partial ? limit : CLAIM_WINDOW_ROWS)
      .all<WindowRow>();
    const rows = res.results || [];
    scanned += rows.length;
    const hits = rows.filter((r) => r.id != null);
    if (hits.length) {
      // Everything before the first claimable row is unclaimable for good.
      if (!partial) await writeCursor(Math.max(start, hits[0].rid - 1));
      return {
        jobs: hits.slice(0, limit).map((r) => ({
          id: r.id as string,
          prompt: r.prompt as string,
          duration_seconds: r.duration_seconds,
          created_at: r.created_at as string,
        })),
        complete: true,
        scanned,
      };
    }
    if (rows.length) cur = rows[rows.length - 1].rid;
    if (rows.length < (partial ? limit : CLAIM_WINDOW_ROWS)) {
      if (!partial) await writeCursor(cur);
      return { jobs: [], complete: true, scanned };
    }
  }
  await writeCursor(cur);
  return { jobs: [], complete: false, scanned };
}

export const claimSoftTtlSec = (v: PendingScan): number =>
  v.jobs.length ? CLAIM_POSITIVE_TTL_SEC : v.complete ? CLAIM_NEGATIVE_TTL_SEC : CLAIM_INCOMPLETE_TTL_SEC;

export interface PendingListing {
  jobs: PendingJob[];
  scan_complete: boolean;
  /** Seconds the client should wait before asking again (empty queue, partial scan, or degraded D1). */
  poll_after_sec: number;
  degraded?: boolean;
  source: string;
  stale: boolean;
}

export async function listPendingWebJobs(env: Env, limit: number): Promise<PendingListing> {
  const snap = await getSnapshot<PendingScan>(
    env,
    PENDING_CACHE_KEY,
    { softTtlSec: claimSoftTtlSec, hardTtlSec: CLAIM_STALE_ON_ERROR_SEC },
    () => scanPendingWeb(env),
  );
  const jobs = snap.value.jobs.slice(0, limit);
  let poll = jobs.length ? 0 : snap.value.complete ? CLAIM_NEGATIVE_TTL_SEC : CLAIM_INCOMPLETE_TTL_SEC;
  if (snap.degraded) poll = Math.max(poll, CLAIM_DEGRADED_POLL_SEC);
  return {
    jobs,
    scan_complete: snap.value.complete,
    poll_after_sec: poll,
    ...(snap.degraded ? { degraded: true } : {}),
    source: snap.source,
    stale: snap.stale,
  };
}
