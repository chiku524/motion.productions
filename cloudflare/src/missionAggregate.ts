/**
 * Pure helpers for mission / coverage statistics (no Worker runtime imports so they can be
 * unit-tested with plain Node: `node --test cloudflare/test`).
 *
 * Why this exists: mission stats used to be derived from the 800 *most-seen* rows
 * (ORDER BY count DESC LIMIT 800), which hides rare families (e.g. white) and makes
 * "underfilled" targeting meaningless. These helpers aggregate over the whole table instead.
 */

export type FamilyGroupRow = { family: string | null; c: number };

/** Largest-remainder apportionment of `total` across `weights` (integer result sums to total). */
export function apportion(total: number, weights: number[]): number[] {
  const sum = weights.reduce((a, b) => a + b, 0);
  if (!(total > 0) || !(sum > 0)) return weights.map(() => 0);
  const raw = weights.map((w) => (total * w) / sum);
  const out = raw.map((x) => Math.floor(x));
  let left = total - out.reduce((a, b) => a + b, 0);
  const order = raw
    .map((x, i) => ({ i, frac: x - Math.floor(x) }))
    .sort((a, b) => b.frac - a.frac || a.i - b.i);
  for (let k = 0; left > 0 && k < order.length; k++, left--) out[order[k].i] += 1;
  return out;
}

/**
 * Build a count for EVERY family id (zero-filled, so empty families such as white stay visible),
 * from a `GROUP BY family` result. Rows whose family column is NULL (never backfilled) are
 * attributed proportionally to the classification of a bounded sample of those rows.
 */
export function mergeFamilyCounts(
  familyIds: readonly string[],
  grouped: FamilyGroupRow[],
  nullRowSampleFamilies: string[],
): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const id of familyIds) counts[id] = 0;
  let nullTotal = 0;
  for (const row of grouped) {
    const c = Number(row.c) || 0;
    if (row.family == null || row.family === "") {
      nullTotal += c;
    } else if (row.family in counts) {
      counts[row.family] += c;
    }
  }
  if (nullTotal > 0 && nullRowSampleFamilies.length) {
    const tally: Record<string, number> = {};
    for (const f of nullRowSampleFamilies) if (f in counts) tally[f] = (tally[f] || 0) + 1;
    const ids = Object.keys(tally);
    const shares = apportion(
      nullTotal,
      ids.map((id) => tally[id]),
    );
    ids.forEach((id, i) => {
      counts[id] += shares[i];
    });
  }
  return counts;
}

/** SQL that counts, in one table scan, rows touching each sound origin primitive. */
export function buildSoundOriginCountSql(origins: readonly string[]): string {
  const safe = origins.filter((o) => /^[a-z_]+$/.test(o));
  const cols = safe
    .map(
      (o) =>
        `SUM(CASE WHEN json_valid(depth_breakdown_json) AND ` +
        `(COALESCE(json_extract(depth_breakdown_json, '$.origin_noises.${o}'), 0) > 0 OR ` +
        `COALESCE(json_extract(depth_breakdown_json, '$.${o}'), 0) > 0) THEN 1 ELSE 0 END) AS "${o}"`,
    )
    .join(", ");
  return `SELECT COUNT(*) AS total, ${cols} FROM static_sound`;
}

export function parseSoundOriginCounts(
  origins: readonly string[],
  row: Record<string, unknown> | null | undefined,
): { total: number; counts: Record<string, number> } {
  const counts: Record<string, number> = {};
  for (const o of origins) counts[o] = Number(row?.[o]) || 0;
  return { total: Number(row?.total) || 0, counts };
}

/** Origins with at least one row (same "touched" semantics as /api/registries/coverage). */
export function presentOrigins(counts: Record<string, number>): string[] {
  return Object.keys(counts)
    .filter((k) => counts[k] > 0)
    .sort();
}

/** True when a cached stats snapshot (ISO `updated_at`) is younger than `softTtlSec`. */
export function isSnapshotFresh(updatedAt: unknown, nowMs: number, softTtlSec: number): boolean {
  if (typeof updatedAt !== "string") return false;
  const t = Date.parse(updatedAt);
  if (!Number.isFinite(t)) return false;
  const age = nowMs - t;
  return age >= 0 && age < softTtlSec * 1000;
}
