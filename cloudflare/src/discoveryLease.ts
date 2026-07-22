/**
 * Single-writer lease for POST /api/knowledge/discoveries.
 * Reduces concurrent D1 stampede from Docker loop workers.
 */
import type { Env } from "./env";

const LEASE_KEY = "discoveries:write_lease";
const LEASE_MS = 25_000;

export type LeaseResult =
  | { ok: true; holder: string }
  | { ok: false; retry_after_ms: number };

export async function acquireDiscoveryLease(env: Env): Promise<LeaseResult> {
  const kv = env.MOTION_KV;
  const holder = crypto.randomUUID();
  if (!kv) return { ok: true, holder };
  try {
    const raw = await kv.get(LEASE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as { holder?: string; exp?: number };
      const exp = typeof parsed.exp === "number" ? parsed.exp : 0;
      if (exp > Date.now()) {
        return { ok: false, retry_after_ms: Math.max(500, exp - Date.now()) };
      }
    }
    const exp = Date.now() + LEASE_MS;
    await kv.put(LEASE_KEY, JSON.stringify({ holder, exp }), { expirationTtl: 45 });
    // Re-read to detect lost race (best-effort)
    const confirm = await kv.get(LEASE_KEY);
    if (confirm) {
      const cur = JSON.parse(confirm) as { holder?: string };
      if (cur.holder && cur.holder !== holder) {
        return { ok: false, retry_after_ms: 1500 };
      }
    }
    return { ok: true, holder };
  } catch {
    return { ok: true, holder };
  }
}

export async function releaseDiscoveryLease(env: Env, holder: string): Promise<void> {
  const kv = env.MOTION_KV;
  if (!kv || !holder) return;
  try {
    const raw = await kv.get(LEASE_KEY);
    if (!raw) return;
    const cur = JSON.parse(raw) as { holder?: string };
    if (cur.holder === holder) await kv.delete(LEASE_KEY);
  } catch {
    /* ignore */
  }
}
