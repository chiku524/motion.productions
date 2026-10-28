/**
 * Bounded, cached read of the interpretation queue (GET /api/interpret/queue), for the free-tier D1 read budget.
 *
 * Before: `SELECT ... FROM interpretations WHERE status='pending' ORDER BY CASE WHEN source='web' ... , created_at LIMIT ?`
 * was uncached and the CASE/created_at ordering is not covered by any index, so every call read (index entry + table row)
 * for EVERY pending interpretation and sorted them: ~2 x N rows per poll, 960 polls/day per interpret container
 * (compose delay 90 s) => over 100k rows/day once about 52 interpretations are pending, and the container inserts hundreds
 * per hour.
 *
 * Now:
 *  - `status = 'pending' AND rowid > ? ORDER BY rowid ASC LIMIT ?` is a range seek on idx_interpretations_status
 *    (status, rowid): at most 2 x limit rows (<= 100) per miss, whatever the backlog size. The window is the OLDEST pending
 *    rows after the client's cursor; web-sourced rows are moved to the front of that window in JS (priority is preserved
 *    inside the window; a web row queued behind > limit older non-web rows waits one cycle).
 *  - Clients pass `after=<next_cursor>` (a rowid) so rows they already attempted (e.g. a prompt that failed to interpret and
 *    stayed pending) do not occupy the window forever; an empty answer tells them to wrap to 0.
 *  - Snapshot cache keyed by (limit, after): empty answer 60 s (negative cache), non-empty 5 s, single-flight, stale served
 *    (flagged degraded, poll_after_sec >= 300) when D1 errors. No D1 or KV write. Enqueue / completion invalidate this
 *    isolate's + colo's copies so a fresh web prompt is not hidden behind the 60 s negative cache locally.
 *
 * Double-processing: this is a read-only listing. A prompt is finished by PATCH /api/interpret/:id, which updates
 * `WHERE id = ? AND status = 'pending'` and answers 400 "Already interpreted" when another worker got there first, so a row
 * served twice from cache can never be completed twice.
 */
import type { Env } from "./env";
import { getDb } from "./db";
import { getSnapshot, invalidateSnapshot } from "./snapshotCache";

export const INTERPRET_QUEUE_DEFAULT_LIMIT = 20;
export const INTERPRET_QUEUE_MAX_LIMIT = 50;
export const INTERPRET_QUEUE_POSITIVE_TTL_SEC = 5;
export const INTERPRET_QUEUE_NEGATIVE_TTL_SEC = 60;
export const INTERPRET_QUEUE_STALE_ON_ERROR_SEC = 3600;
/** Hint for clients when the queue is empty: ask again no sooner than this. */
export const INTERPRET_QUEUE_IDLE_POLL_SEC = 120;
/** Hint when D1 is quota-blocked and a stale (or empty) answer was served. */
export const INTERPRET_QUEUE_DEGRADED_POLL_SEC = 300;

export interface QueueItem {
  /** rowid: the cursor value. */
  rid: number;
  id: string;
  prompt: string;
  source: string;
  created_at: string;
}

export interface QueueWindow {
  items: QueueItem[];
  /** Highest rowid in the window (pass back as `after`); equals the request's `after` when the window is empty. */
  next_cursor: number;
  /** false: the window was full, more pending rows may follow. */
  scan_complete: boolean;
}

export const QUEUE_SQL =
  "SELECT rowid AS rid, id, prompt, source, created_at FROM interpretations " +
  "WHERE status = 'pending' AND rowid > ? ORDER BY rowid ASC LIMIT ?";

const knownKeys = new Set<string>();
const KNOWN_KEYS_MAX = 64;

export const queueCacheKey = (limit: number, after: number): string => `interp:queue:v1:${limit}:${after}`;

export function parseQueueParams(url: URL): { limit: number; after: number } {
  const l = parseInt(url.searchParams.get("limit") || "", 10);
  const a = parseInt(url.searchParams.get("after") || "", 10);
  return {
    limit: Math.min(Math.max(Number.isFinite(l) ? l : INTERPRET_QUEUE_DEFAULT_LIMIT, 1), INTERPRET_QUEUE_MAX_LIMIT),
    after: Number.isFinite(a) && a > 0 ? a : 0,
  };
}

export async function scanInterpretQueue(env: Env, limit: number, after: number): Promise<QueueWindow> {
  const res = await getDb(env)
    .prepare(QUEUE_SQL)
    .bind(after, limit)
    .all<QueueItem>();
  const rows = res.results || [];
  // web (user-submitted) first inside the window; rowid order (= oldest first) otherwise
  const items = rows
    .map((r) => ({ rid: Number(r.rid), id: r.id, prompt: r.prompt, source: r.source, created_at: r.created_at }))
    .sort((a, b) => (a.source === "web" ? 0 : 1) - (b.source === "web" ? 0 : 1) || a.rid - b.rid);
  return {
    items,
    next_cursor: rows.length ? Number(rows[rows.length - 1].rid) : after,
    scan_complete: rows.length < limit,
  };
}

export interface QueueListing extends QueueWindow {
  poll_after_sec: number;
  degraded?: boolean;
  source: string;
  stale: boolean;
}

export async function listInterpretQueue(env: Env, limit: number, after: number): Promise<QueueListing> {
  const key = queueCacheKey(limit, after);
  if (knownKeys.size >= KNOWN_KEYS_MAX) knownKeys.clear();
  knownKeys.add(key);
  const snap = await getSnapshot<QueueWindow>(
    env,
    key,
    {
      softTtlSec: (v) => (v.items.length ? INTERPRET_QUEUE_POSITIVE_TTL_SEC : INTERPRET_QUEUE_NEGATIVE_TTL_SEC),
      hardTtlSec: INTERPRET_QUEUE_STALE_ON_ERROR_SEC,
    },
    () => scanInterpretQueue(env, limit, after),
  );
  let poll = snap.value.items.length ? 0 : INTERPRET_QUEUE_IDLE_POLL_SEC;
  if (snap.degraded) poll = Math.max(poll, INTERPRET_QUEUE_DEGRADED_POLL_SEC);
  return {
    ...snap.value,
    poll_after_sec: poll,
    ...(snap.degraded ? { degraded: true } : {}),
    source: snap.source,
    stale: snap.stale,
  };
}

/** Drop every queue window this isolate has served (memory + this colo's Cache API copy). Called on enqueue/complete. */
export async function invalidateInterpretQueue(): Promise<void> {
  const keys = [...knownKeys];
  knownKeys.clear();
  // Always include the default poll so a fresh isolate (empty knownKeys) still clears the common key.
  const dflt = queueCacheKey(INTERPRET_QUEUE_DEFAULT_LIMIT, 0);
  if (!keys.includes(dflt)) keys.push(dflt);
  await Promise.all(keys.map((k) => invalidateSnapshot(k)));
}