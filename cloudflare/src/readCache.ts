/**
 * Read-path cache helpers for the D1 free tier (5M rows read / day).
 *
 * Everything here is a thin layer over snapshotCache.ts (memory -> Cache API -> optional KV, single-flight,
 * stale-on-error). Nothing writes to D1 or KV on a hot path.
 */
import type { Env } from "./env";
import { getDb } from "./db";
import { getSnapshot } from "./snapshotCache";

/** Cache rows/objects built from D1; on a D1 error (quota 7500, db full, ...) the freshest stale copy is served. */
export async function cachedRows<T>(
  env: Env,
  key: string,
  softTtlSec: number,
  build: () => Promise<T>,
  hardTtlSec = 86400,
): Promise<T> {
  const snap = await getSnapshot<T>(env, key, { softTtlSec, hardTtlSec }, build);
  return snap.value;
}

export interface InterpretationRow {
  id: string;
  prompt: string;
  instruction_json: string | null;
  updated_at: string;
}

/**
 * Most recently completed interpretations.
 *
 * `ORDER BY rowid DESC` walks idx_interpretations_status (status, rowid) backwards and stops after `limit` rows.
 * The old `ORDER BY updated_at DESC` had no (status, updated_at) index, so every call sorted all ~'done' rows.
 * rowid order = insertion order, a close proxy for "recently interpreted" (rows are inserted pending, then updated).
 */
export async function recentDoneInterpretations(env: Env, limit: number): Promise<InterpretationRow[]> {
  const n = Math.max(1, Math.min(Math.floor(limit) || 1, 5000));
  return cachedRows<InterpretationRow[]>(env, `interp:done:recent:v1:${n}`, 300, async () => {
    const rows = await getDb(env)
      .prepare(
        "SELECT id, prompt, instruction_json, updated_at FROM interpretations WHERE status = 'done' AND instruction_json IS NOT NULL ORDER BY rowid DESC LIMIT ?",
      )
      .bind(n)
      .all<InterpretationRow>();
    return rows.results || [];
  });
}
