/**
 * Opportunistic log retention for the D1 free tier (no cron trigger: the account's 5 free cron slots are used).
 *
 * Piggy-backs on the write path (POST /api/knowledge/discoveries, POST /api/learning). For each log table the Worker
 * atomically claims a daily slot in a tiny marker table, then deletes a few small batches of old rows:
 *   learning_runs, events, discovery_runs   older than RETENTION_DAYS (default 3)
 *   jobs                                    same age, no real R2 object (r2_key NULL / skipped: / expired:) and no
 *                                           dependent learning_runs / discovery_runs / events / feedback rows (FKs)
 * Costs when nothing is due: ONE batch of 4 conditional upserts (0 rows written, ~4 rows read), and at most one such
 * check per isolate per 30 min. Costs when due: <= RETENTION_MAX_BATCHES x RETENTION_BATCH_ROWS rows per table, and the
 * whole run stops once RETENTION_WRITE_BUDGET rows-written (as reported by D1 meta, indexes included) is spent.
 * Best-effort: never throws, never blocks a response on error; a DB-full / quota error just skips the run.
 */
import type { Env } from "./env";
import { getDb } from "./db";

export const DAY_SEC = 86400;
const ABSOLUTE_MAX_BATCH_ROWS = 500;

export interface RetentionConfig {
  days: number;
  batchRows: number;
  maxBatches: number;
  writeBudget: number;
  disabled: boolean;
  /** Min seconds between marker checks per isolate (default 1800; 0 = check on every write, used by tests). */
  checkIntervalSec: number;
}

function num(v: unknown, dflt: number, lo: number, hi: number): number {
  const n = Number(v);
  return Number.isFinite(n) && n >= lo ? Math.min(Math.floor(n), hi) : dflt;
}

export function retentionConfig(env: Env): RetentionConfig {
  const e = env as unknown as Record<string, string | undefined>;
  return {
    days: num(e.RETENTION_DAYS, 3, 1, 365),
    batchRows: num(e.RETENTION_BATCH_ROWS, ABSOLUTE_MAX_BATCH_ROWS, 1, ABSOLUTE_MAX_BATCH_ROWS),
    maxBatches: num(e.RETENTION_MAX_BATCHES, 3, 1, 10),
    writeBudget: num(e.RETENTION_WRITE_BUDGET, 6000, 100, 50000),
    disabled: e.RETENTION_DISABLED === "1",
    checkIntervalSec: num(e.RETENTION_CHECK_INTERVAL_SEC, 1800, 0, DAY_SEC),
  };
}

const AGED = "created_at < datetime('now', ?)";
const PLAIN = (t: string) =>
  `DELETE FROM ${t} WHERE id IN (SELECT id FROM ${t} WHERE ${AGED} ORDER BY created_at LIMIT ?)`;

/** Order matters: children before jobs. Each statement binds (ageModifier, limit). */
export const RETENTION_TABLES: Array<{ table: string; sql: string }> = [
  { table: "learning_runs", sql: PLAIN("learning_runs") },
  { table: "events", sql: PLAIN("events") },
  { table: "discovery_runs", sql: PLAIN("discovery_runs") },
  {
    table: "jobs",
    sql: `DELETE FROM jobs WHERE id IN (
      SELECT j.id FROM jobs j
      WHERE j.created_at < datetime('now', ?)
        AND j.status IN ('completed', 'failed', 'error', 'abandoned')
        AND (j.r2_key IS NULL OR j.r2_key LIKE 'skipped:%' OR j.r2_key LIKE 'expired:%')
        AND NOT EXISTS (SELECT 1 FROM learning_runs x WHERE x.job_id = j.id)
        AND NOT EXISTS (SELECT 1 FROM discovery_runs x WHERE x.job_id = j.id)
        AND NOT EXISTS (SELECT 1 FROM events x WHERE x.job_id = j.id)
        AND NOT EXISTS (SELECT 1 FROM feedback x WHERE x.job_id = j.id)
      ORDER BY j.created_at LIMIT ?)`,
  },
];

let lastCheckMs = 0;

/** Test hook: forget per-isolate state. */
export function _resetRetentionState(): void {
  lastCheckMs = 0;
}

const CREATE_MARKER_SQL =
  "CREATE TABLE IF NOT EXISTS retention_marker (table_name TEXT PRIMARY KEY, last_run_at INTEGER NOT NULL, rows_deleted INTEGER NOT NULL DEFAULT 0)";
// Atomic daily claim: the conditional upsert writes 0 rows unless the table is due.
const CLAIM_SQL =
  "INSERT INTO retention_marker (table_name, last_run_at, rows_deleted) VALUES (?, ?, 0) ON CONFLICT(table_name) DO UPDATE SET last_run_at = excluded.last_run_at WHERE retention_marker.last_run_at <= ? RETURNING table_name";

async function claimDue(db: D1Database, nowSec: number): Promise<D1Result[]> {
  const run = () => db.batch(RETENTION_TABLES.map((t) => db.prepare(CLAIM_SQL).bind(t.table, nowSec, nowSec - DAY_SEC)));
  try {
    return await run();
  } catch (e) {
    // First ever run: the marker table is created lazily (no remote migration needed). Anything else propagates.
    if (!/no such table/i.test(String(e))) throw e;
    await db.prepare(CREATE_MARKER_SQL).run();
    return await run();
  }
}

export interface RetentionReport {
  ran: boolean;
  skipped?: string;
  tables: Record<string, { deleted: number; batches: number; rowsWritten: number }>;
  rowsWritten: number;
}

/** Never throws. `nowSec` is injectable for tests. */
export async function maybeRunRetention(env: Env, opts: { nowSec?: number; force?: boolean } = {}): Promise<RetentionReport> {
  const report: RetentionReport = { ran: false, tables: {}, rowsWritten: 0 };
  try {
    const cfg = retentionConfig(env);
    if (cfg.disabled) return { ...report, skipped: "disabled" };
    const nowMs = Date.now();
    if (!opts.force && nowMs - lastCheckMs < cfg.checkIntervalSec * 1000) return { ...report, skipped: "checked recently" };
    lastCheckMs = nowMs;
    const db = getDb(env);
    const nowSec = opts.nowSec ?? Math.floor(nowMs / 1000);

    const claims = await claimDue(db, nowSec);
    const due = RETENTION_TABLES.filter((_, i) => ((claims[i]?.results || []) as unknown[]).length > 0);
    if (!due.length) return { ...report, skipped: "nothing due" };

    report.ran = true;
    const modifier = `-${cfg.days} days`;
    for (const t of due) {
      const stat = { deleted: 0, batches: 0, rowsWritten: 0 };
      report.tables[t.table] = stat;
      for (let b = 0; b < cfg.maxBatches; b++) {
        if (report.rowsWritten >= cfg.writeBudget) break;
        // Never plan a batch that could blow the remaining budget by a lot: shrink the LIMIT to what the budget allows
        // assuming <= 5 written rows per deleted row (row + up to 4 index entries).
        const remaining = cfg.writeBudget - report.rowsWritten;
        const limit = Math.max(1, Math.min(cfg.batchRows, Math.floor(remaining / 5)));
        const res = await db.prepare(t.sql).bind(modifier, limit).run();
        const meta = (res.meta || {}) as { changes?: number; rows_written?: number };
        const changes = meta.changes ?? 0;
        const written = meta.rows_written ?? changes;
        stat.batches++;
        stat.deleted += changes;
        stat.rowsWritten += written;
        report.rowsWritten += written;
        if (changes < limit) break; // caught up
      }
    }
    try {
      await db.batch(
        due.map((t) =>
          db.prepare("UPDATE retention_marker SET rows_deleted = rows_deleted + ? WHERE table_name = ?").bind(report.tables[t.table].deleted, t.table),
        ),
      );
    } catch {
      /* bookkeeping only */
    }
    return report;
  } catch (e) {
    console.warn("retention skipped:", String(e));
    return { ...report, skipped: "error" };
  }
}