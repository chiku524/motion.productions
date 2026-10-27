/**
 * Layered read-through snapshot cache built for Cloudflare Free-tier budgets.
 *
 *   isolate memory  ->  Cache API (caches.default, free, per-colo)  ->  KV (durable stale fallback only)
 *
 * - KV is NEVER written on a hot path: a persisted copy is refreshed at most once per
 *   `kvPersistSec` (default off). KV free tier allows 1,000 writes/day for the whole account.
 * - Concurrent rebuilds in one isolate are collapsed (single-flight).
 * - When a rebuild throws (D1/KV daily limit, 7429, ...) any stale copy (memory, Cache API, KV)
 *   is served and flagged `degraded` instead of failing the request.
 * - `bypass` (fresh=1) is rate limited so a refresh button cannot burn the D1 read budget.
 */
import type { Env } from "./env";
import { isFreeTierLimitError } from "./limits";

export interface SnapshotOptions {
  /** Serve from cache without rebuilding while younger than this. */
  softTtlSec: number;
  /** Serve (flagged stale) on rebuild failure while younger than this. Default 24 h. */
  hardTtlSec?: number;
  /** If set, persist a durable copy in KV at most this often (and read it on cold miss). */
  kvPersistSec?: number | null;
  /** Force a rebuild (still rate limited). */
  bypass?: boolean;
  /** Minimum seconds between honored bypasses for one key. Default 60. */
  bypassMinIntervalSec?: number;
}

export interface SnapshotResult<T> {
  value: T;
  stale: boolean;
  degraded: boolean;
  source: "memory" | "cache" | "kv" | "built";
  ageSec: number;
}

interface Entry<T> {
  at: number;
  value: T;
}

const memory = new Map<string, Entry<unknown>>();
const inflight = new Map<string, Promise<Entry<unknown>>>();
const lastBypass = new Map<string, number>();
const MEMORY_MAX_KEYS = 200;

const DEFAULT_HARD_TTL_SEC = 86400;
const CACHE_ORIGIN = "https://snapshot.motion.invalid/";

/** Test hook: forget all in-isolate state. */
export function __resetSnapshotMemory(): void {
  memory.clear();
  inflight.clear();
  lastBypass.clear();
}

function cacheApi(): Cache | null {
  try {
    const c = (globalThis as { caches?: { default?: Cache } }).caches;
    return c?.default ?? null;
  } catch {
    return null;
  }
}

function remember<T>(key: string, entry: Entry<T>): void {
  if (memory.size >= MEMORY_MAX_KEYS && !memory.has(key)) {
    const first = memory.keys().next().value;
    if (first !== undefined) memory.delete(first);
  }
  memory.set(key, entry as Entry<unknown>);
}

async function readCacheApi<T>(key: string): Promise<Entry<T> | null> {
  const c = cacheApi();
  if (!c) return null;
  try {
    const res = await c.match(new Request(CACHE_ORIGIN + encodeURIComponent(key)));
    if (!res) return null;
    const at = Number(res.headers.get("x-snap-at") || 0);
    if (!at) return null;
    return { at, value: (await res.json()) as T };
  } catch {
    return null;
  }
}

async function writeCacheApi<T>(key: string, entry: Entry<T>, hardTtlSec: number): Promise<void> {
  const c = cacheApi();
  if (!c) return;
  try {
    await c.put(
      new Request(CACHE_ORIGIN + encodeURIComponent(key)),
      new Response(JSON.stringify(entry.value), {
        headers: {
          "Content-Type": "application/json",
          "Cache-Control": `public, max-age=${hardTtlSec}`,
          "x-snap-at": String(entry.at),
        },
      }),
    );
  } catch {
    /* Cache API unavailable (e.g. workers.dev edge cases) - memory + KV still work */
  }
}

const kvKey = (key: string) => `snap:${key}`;

async function readKv<T>(env: Env, key: string): Promise<Entry<T> | null> {
  if (!env.MOTION_KV) return null;
  try {
    const raw = await env.MOTION_KV.get(kvKey(key));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { at?: number; value?: T };
    if (typeof parsed.at !== "number" || parsed.value === undefined) return null;
    return { at: parsed.at, value: parsed.value };
  } catch {
    return null;
  }
}

async function maybePersistKv<T>(
  env: Env,
  key: string,
  entry: Entry<T>,
  kvPersistSec: number,
  hardTtlSec: number,
  known: Entry<T> | null,
): Promise<void> {
  if (!env.MOTION_KV) return;
  try {
    const prev = known ?? (await readKv<T>(env, key));
    if (prev && entry.at - prev.at < kvPersistSec * 1000) return;
    await env.MOTION_KV.put(kvKey(key), JSON.stringify({ at: entry.at, value: entry.value }), {
      expirationTtl: Math.max(60, hardTtlSec),
    });
  } catch {
    /* KV write failed/limit hit - never fail a request over the durable copy */
  }
}

export async function getSnapshot<T>(
  env: Env,
  key: string,
  opts: SnapshotOptions,
  build: () => Promise<T>,
): Promise<SnapshotResult<T>> {
  const now = Date.now();
  const softMs = opts.softTtlSec * 1000;
  const hardSec = opts.hardTtlSec ?? DEFAULT_HARD_TTL_SEC;
  const hardMs = hardSec * 1000;
  const persist = opts.kvPersistSec ?? null;

  let bypass = !!opts.bypass;
  if (bypass) {
    const last = lastBypass.get(key) ?? 0;
    if (now - last < (opts.bypassMinIntervalSec ?? 60) * 1000) bypass = false;
    else lastBypass.set(key, now);
  }

  const mem = memory.get(key) as Entry<T> | undefined;
  if (!bypass && mem && now - mem.at < softMs) {
    return { value: mem.value, stale: false, degraded: false, source: "memory", ageSec: Math.round((now - mem.at) / 1000) };
  }

  let cacheEntry: Entry<T> | null = null;
  if (!bypass) {
    cacheEntry = await readCacheApi<T>(key);
    if (cacheEntry && now - cacheEntry.at < softMs) {
      remember(key, cacheEntry);
      return { value: cacheEntry.value, stale: false, degraded: false, source: "cache", ageSec: Math.round((now - cacheEntry.at) / 1000) };
    }
  }

  let kvEntry: Entry<T> | null = null;
  if (persist != null && !bypass) {
    kvEntry = await readKv<T>(env, key);
    if (kvEntry && now - kvEntry.at < softMs) {
      remember(key, kvEntry);
      void writeCacheApi(key, kvEntry, hardSec);
      return { value: kvEntry.value, stale: false, degraded: false, source: "kv", ageSec: Math.round((now - kvEntry.at) / 1000) };
    }
  }

  // Rebuild (single-flight per isolate).
  let pending = inflight.get(key) as Promise<Entry<T>> | undefined;
  if (!pending) {
    pending = (async () => {
      const value = await build();
      const entry: Entry<T> = { at: Date.now(), value };
      remember(key, entry);
      await writeCacheApi(key, entry, hardSec);
      if (persist != null) await maybePersistKv(env, key, entry, persist, hardSec, kvEntry);
      return entry;
    })();
    inflight.set(key, pending as Promise<Entry<unknown>>);
    void pending.then(
      () => inflight.delete(key),
      () => inflight.delete(key),
    );
  }
  try {
    const entry = await pending;
    return { value: entry.value, stale: false, degraded: false, source: "built", ageSec: Math.round((Date.now() - entry.at) / 1000) };
  } catch (e) {
    // Serve the freshest stale copy we can find.
    const candidates: Array<{ entry: Entry<T>; source: SnapshotResult<T>["source"] }> = [];
    if (mem) candidates.push({ entry: mem, source: "memory" });
    if (cacheEntry) candidates.push({ entry: cacheEntry, source: "cache" });
    if (kvEntry) candidates.push({ entry: kvEntry, source: "kv" });
    if (persist != null && !kvEntry) {
      const k = await readKv<T>(env, key);
      if (k) candidates.push({ entry: k, source: "kv" });
    }
    if (!cacheEntry) {
      const c = await readCacheApi<T>(key);
      if (c) candidates.push({ entry: c, source: "cache" });
    }
    candidates.sort((a, b) => b.entry.at - a.entry.at);
    const best = candidates.find((c) => Date.now() - c.entry.at < hardMs);
    if (best) {
      console.warn(`snapshot ${key}: rebuild failed (${isFreeTierLimitError(e) ? "free-tier limit" : "error"}), serving stale ${best.source}`);
      return {
        value: best.entry.value,
        stale: true,
        degraded: true,
        source: best.source,
        ageSec: Math.round((Date.now() - best.entry.at) / 1000),
      };
    }
    throw e;
  }
}