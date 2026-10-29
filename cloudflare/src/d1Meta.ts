/**
 * D1 reports `meta.rows_written` per statement, index entries included (the number Cloudflare bills against the free
 * 100k/day). Every write route returns the sum as `rows_written` so clients can keep an exact ledger instead of guessing.
 */
export function rowsWrittenOf(res: unknown): number {
  if (Array.isArray(res)) return res.reduce((s: number, r) => s + rowsWrittenOf(r), 0);
  const n = Number(((res as { meta?: { rows_written?: number } } | null | undefined)?.meta)?.rows_written);
  return Number.isFinite(n) && n > 0 ? n : 0;
}
