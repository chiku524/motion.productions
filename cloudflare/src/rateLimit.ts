/**
 * Per-client rate limit on the Cache API (free, per-colo, NO D1 / KV writes).
 *
 * Best effort by design: the counter is a cached Response keyed by (scope, ip, window). get-then-put is not atomic and
 * colos do not share counters, so this blunts hammering of an uncached/unauthenticated endpoint, it is not a security
 * boundary. If the Cache API is unavailable the in-isolate Map is used instead. Fails open.
 */
const ORIGIN = "https://ratelimit.motion.invalid/";
const local = new Map<string, number>();

/** Test hook. */
export function __resetRateLimit(): void {
  local.clear();
}

function cacheApi(): Cache | null {
  try {
    const c = (globalThis as { caches?: { default?: Cache } }).caches;
    return c?.default ?? null;
  } catch {
    return null;
  }
}

export function clientIp(request: Request): string {
  return (request.headers.get("CF-Connecting-IP") || request.headers.get("X-Forwarded-For") || "anon").split(",")[0].trim() || "anon";
}

export interface RateResult {
  allowed: boolean;
  count: number;
  retryAfterSec: number;
}

export async function hitRateLimit(request: Request, scope: string, limit: number, windowSec = 60): Promise<RateResult> {
  const nowSec = Math.floor(Date.now() / 1000);
  const bucket = Math.floor(nowSec / windowSec);
  const retryAfterSec = Math.max(1, (bucket + 1) * windowSec - nowSec);
  const key = `${scope}:${clientIp(request)}:${bucket}`;
  const c = cacheApi();
  let count = 1;
  let usedCache = false;
  if (c) {
    try {
      const req = new Request(ORIGIN + encodeURIComponent(key));
      const hit = await c.match(req);
      const prev = hit ? Number(await hit.text()) || 0 : 0;
      count = prev + 1;
      await c.put(req, new Response(String(count), { headers: { "Cache-Control": `public, max-age=${windowSec + 5}` } }));
      usedCache = true;
    } catch {
      usedCache = false;
    }
  }
  if (!usedCache) {
    if (local.size > 5000) local.clear();
    count = (local.get(key) ?? 0) + 1;
    local.set(key, count);
  }
  return { allowed: count <= limit, count, retryAfterSec };
}
