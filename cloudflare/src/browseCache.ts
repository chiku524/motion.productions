/**
 * KV cache keys + invalidation for registry browse and for-creation snapshots.
 */
import type { Env } from "./env";

export const BROWSE_COLORS_CACHE_KEY = "registries:browse:static_colors:v1";
export const BROWSE_COLOR_FACETS_KEY = "registries:browse:facets:static_colors:v1";
export const BROWSE_SOUND_CACHE_KEY = "registries:browse:static_sound:v1";
export const FOR_CREATION_GEN_KEY = "knowledge:for-creation:gen";

const BROWSE_KEYS = [
  BROWSE_COLORS_CACHE_KEY,
  BROWSE_COLOR_FACETS_KEY,
  BROWSE_SOUND_CACHE_KEY,
] as const;

/** Drop browse list/facet caches so the next GET rebuilds from D1. */
export async function invalidateBrowseCaches(env: Env): Promise<void> {
  const kv = env.MOTION_KV;
  if (!kv) return;
  await Promise.all(
    BROWSE_KEYS.map(async (key) => {
      try {
        await kv.delete(key);
      } catch {
        /* ignore */
      }
    }),
  );
}

/**
 * Bump for-creation generation so cached snapshots under old keys go stale.
 * Cache keys include this gen; we do not need to list/delete old entries.
 */
export async function bumpForCreationGeneration(env: Env): Promise<string> {
  const kv = env.MOTION_KV;
  if (!kv) return "0";
  try {
    const prev = parseInt((await kv.get(FOR_CREATION_GEN_KEY)) || "0", 10) || 0;
    const next = String(prev + 1);
    await kv.put(FOR_CREATION_GEN_KEY, next, { expirationTtl: 60 * 60 * 24 * 90 });
    return next;
  } catch {
    return "0";
  }
}

export async function readForCreationGeneration(env: Env): Promise<string> {
  const kv = env.MOTION_KV;
  if (!kv) return "0";
  try {
    return (await kv.get(FOR_CREATION_GEN_KEY)) || "0";
  } catch {
    return "0";
  }
}

/** Call after novel registry writes (discoveries, name backfill, sound sanitize). */
export async function invalidateRegistryReadCaches(env: Env): Promise<void> {
  await invalidateBrowseCaches(env);
  await bumpForCreationGeneration(env);
  // Coverage cache — short TTL already; delete for immediate consistency
  if (env.MOTION_KV) {
    try {
      await env.MOTION_KV.delete("registries:coverage");
    } catch {
      /* ignore */
    }
  }
}
