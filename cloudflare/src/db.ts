import type { Env } from "./env";

/** True after we have confirmed the table exists in this isolate (cheap probe) or finished DDL. */
let learnedDynamicMetaTableReady = false;

/**
 * Ensure learned_dynamic_meta exists without relying on wrangler migration import (large remote D1 DBs can hit CPU 7429 during import even for CREATE TABLE).
 * DDL runs in the Worker in separate statements; migrations 0018/0019 are no-op SELECT 1 for apply ordering only.
 */
export async function ensureLearnedDynamicMetaTable(db: D1Database): Promise<void> {
  if (learnedDynamicMetaTableReady) return;
  try {
    await db.prepare("SELECT 1 FROM learned_dynamic_meta LIMIT 1").first();
    learnedDynamicMetaTableReady = true;
    return;
  } catch {
    /* table missing or unreadable */
  }
  try {
    await db
      .prepare(
        `CREATE TABLE IF NOT EXISTS learned_dynamic_meta (
          aspect TEXT NOT NULL,
          profile_key TEXT NOT NULL,
          depth_breakdown_json TEXT,
          updated_at TEXT NOT NULL DEFAULT (datetime('now')),
          PRIMARY KEY (aspect, profile_key)
        )`,
      )
      .run();
  } catch {
    /* retry on next request */
  }
  try {
    await db
      .prepare(
        "CREATE INDEX IF NOT EXISTS idx_learned_dynamic_meta_aspect ON learned_dynamic_meta(aspect)",
      )
      .run();
  } catch {
    /* non-fatal */
  }
  try {
    await db
      .prepare(
        "CREATE INDEX IF NOT EXISTS idx_learned_dynamic_meta_profile ON learned_dynamic_meta(profile_key)",
      )
      .run();
  } catch {
    /* non-fatal */
  }
  try {
    await db.prepare("SELECT 1 FROM learned_dynamic_meta LIMIT 1").first();
    learnedDynamicMetaTableReady = true;
  } catch {
    /* leave false so a later request retries DDL */
  }
}

/** True after learned_colors.depth_breakdown_json is readable (ALTER may run once per isolate; wrangler 0017 is no-op on large D1). */
let learnedColorsDepthReady = false;
let learnedColorsDepthAlterAttempted = false;

/** Returns true if learned_colors.depth_breakdown_json can be queried (column exists). */
export async function ensureLearnedColorsDepthColumn(db: D1Database): Promise<boolean> {
  if (learnedColorsDepthReady) return true;
  try {
    await db.prepare("SELECT depth_breakdown_json FROM learned_colors LIMIT 1").first();
    learnedColorsDepthReady = true;
    return true;
  } catch {
    /* no column or unreadable */
  }
  if (!learnedColorsDepthAlterAttempted) {
    learnedColorsDepthAlterAttempted = true;
    try {
      await db.prepare("ALTER TABLE learned_colors ADD COLUMN depth_breakdown_json TEXT").run();
    } catch {
      /* duplicate column, D1 7429, etc. */
    }
  }
  try {
    await db.prepare("SELECT depth_breakdown_json FROM learned_colors LIMIT 1").first();
    learnedColorsDepthReady = true;
    return true;
  } catch {
    return false;
  }
}

/** Temporal/technical depth: avoid ALTER on large learned_* tables (D1 CPU 7429); use learned_dynamic_meta. */
export async function upsertLearnedDynamicMeta(
  db: D1Database,
  aspect: string,
  profileKey: string,
  depthJson: string | null,
): Promise<void> {
  if (!depthJson) return;
  await ensureLearnedDynamicMetaTable(db);
  try {
    await db
      .prepare(
        `INSERT INTO learned_dynamic_meta (aspect, profile_key, depth_breakdown_json, updated_at) VALUES (?, ?, ?, datetime('now'))
         ON CONFLICT(aspect, profile_key) DO UPDATE SET depth_breakdown_json = excluded.depth_breakdown_json, updated_at = datetime('now')`,
      )
      .bind(aspect, profileKey, depthJson)
      .run();
  } catch {
    /* constraint / transient D1 */
  }
}

/** Derive D1 database (with read replica when available). */
export function getDb(env: Env): D1Database {
  const primaryDb = env.DB;
  const extended = primaryDb as D1Database & { withSession?: (b: string) => D1Database };
  /* withSession returns D1DatabaseSession in typings; runtime API matches D1Database for prepare/batch. */
  return (extended.withSession?.("first-unconstrained") ?? primaryDb) as unknown as D1Database;
}
