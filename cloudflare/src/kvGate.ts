/**
 * Write gate for KV puts that are allowed but must stay rare (free tier: 1,000 KV writes/day, 1 write/sec/key).
 *
 * `shouldWrite(key, minIntervalSec)` consults an isolate-local map and a Cache API marker (shared by every
 * isolate in the colo), so N isolates do not multiply the write rate. Call `markWritten` after a successful put.
 */
const lastWrite = new Map<string, number>();
const MARKER_ORIGIN = "https://kvgate.motion.invalid/";

function cacheApi(): Cache | null {
  try {
    return (globalThis as { caches?: { default?: Cache } }).caches?.default ?? null;
  } catch {
    return null;
  }
}

export function __resetKvGate(): void {
  lastWrite.clear();
}

export async function shouldWrite(key: string, minIntervalSec: number): Promise<boolean> {
  const now = Date.now();
  const mem = lastWrite.get(key);
  if (mem && now - mem < minIntervalSec * 1000) return false;
  const cache = cacheApi();
  if (cache) {
    try {
      const hit = await cache.match(MARKER_ORIGIN + encodeURIComponent(key));
      if (hit) {
        const at = Number(hit.headers.get("x-written-at") || 0);
        if (at && now - at < minIntervalSec * 1000) {
          lastWrite.set(key, at);
          return false;
        }
      }
    } catch {
      /* Cache API unavailable: isolate-local gate only */
    }
  }
  return true;
}

export async function markWritten(key: string, minIntervalSec: number): Promise<void> {
  const now = Date.now();
  lastWrite.set(key, now);
  const cache = cacheApi();
  if (!cache) return;
  try {
    await cache.put(
      MARKER_ORIGIN + encodeURIComponent(key),
      new Response("1", { headers: { "x-written-at": String(now), "Cache-Control": `public, max-age=${Math.max(1, Math.floor(minIntervalSec))}` } }),
    );
  } catch {
    /* ignore */
  }
}