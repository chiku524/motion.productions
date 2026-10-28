import type { Env } from "./env";
import { isFreeTierLimitError } from "./limits";
import { getSnapshot } from "./snapshotCache";

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

let staticColorsFamilyReady = false;
let staticColorsFamilyAlterAttempted = false;

/** Returns true if static_colors.family / shade columns are usable. */
export async function ensureStaticColorsFamilyColumns(db: D1Database): Promise<boolean> {
  if (staticColorsFamilyReady) return true;
  try {
    await db.prepare("SELECT family, shade FROM static_colors LIMIT 1").first();
    staticColorsFamilyReady = true;
    return true;
  } catch {
    /* no columns yet */
  }
  if (!staticColorsFamilyAlterAttempted) {
    staticColorsFamilyAlterAttempted = true;
    for (const sql of [
      "ALTER TABLE static_colors ADD COLUMN family TEXT",
      "ALTER TABLE static_colors ADD COLUMN shade TEXT",
    ]) {
      try {
        await db.prepare(sql).run();
      } catch {
        /* duplicate / 7429 */
      }
    }
    // Index builds on ~28k-row static_colors burn D1 CPU (7429). Prefer migration 0022 offline;
    // do not CREATE INDEX on the request path under loop load.
  }
  try {
    await db.prepare("SELECT family, shade FROM static_colors LIMIT 1").first();
    staticColorsFamilyReady = true;
    return true;
  } catch {
    return false;
  }
}

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

/** Derive D1 database (with read replica when available). Prefer for list/read paths. */
export function getDb(env: Env): D1Database {
  const primaryDb = env.DB;
  const extended = primaryDb as D1Database & { withSession?: (b: string) => D1Database };
  /* withSession returns D1DatabaseSession in typings; runtime API matches D1Database for prepare/batch. */
  return (extended.withSession?.("first-unconstrained") ?? primaryDb) as unknown as D1Database;
}

/** Primary D1 only — use for COUNT(*) / coverage so replica lag or replica CPU 7429 cannot zero out metrics. */
export function getPrimaryDb(env: Env): D1Database {
  return env.DB;
}


const REGISTRY_COUNTS_KV_KEY = "registries:counts:v1";
/** KV writes are capped (free tier: 1,000/day). Persist the counts blob at most this often. */
const REGISTRY_COUNTS_PERSIST_MIN_SEC = 30 * 60;
const REGISTRY_COUNTS_MEMORY_SEC = 60;

export type RegistryCounts = {
  static_colors: number;
  static_sound: number;
  learned_colors: number;
  updated_at: string;
};

type CountDelta = Partial<Pick<RegistryCounts, "static_colors" | "static_sound" | "learned_colors">>;

/** Isolate-local state: last known counts (from KV or an exact recount) + not-yet-persisted deltas. */
let countsMemory: { at: number; counts: RegistryCounts | null } | null = null;
const pendingCounts = { static_colors: 0, static_sound: 0, learned_colors: 0 };

/** Test hook. */
export function __resetRegistryCountsMemory(): void {
  countsMemory = null;
  pendingCounts.static_colors = pendingCounts.static_sound = pendingCounts.learned_colors = 0;
}

function withPending(c: RegistryCounts | null): RegistryCounts | null {
  if (!c) return null;
  return {
    static_colors: Math.max(0, c.static_colors + pendingCounts.static_colors),
    static_sound: Math.max(0, c.static_sound + pendingCounts.static_sound),
    learned_colors: Math.max(0, c.learned_colors + pendingCounts.learned_colors),
    updated_at: c.updated_at,
  };
}

export async function readRegistryCounts(env: Env): Promise<RegistryCounts | null> {
  if (countsMemory && Date.now() - countsMemory.at < REGISTRY_COUNTS_MEMORY_SEC * 1000) {
    return withPending(countsMemory.counts);
  }
  let counts: RegistryCounts | null = null;
  if (env.MOTION_KV) {
    try {
      const raw = await env.MOTION_KV.get(REGISTRY_COUNTS_KV_KEY);
      if (raw) {
        const parsed = JSON.parse(raw) as RegistryCounts;
        if (typeof parsed.static_colors === "number") counts = parsed;
      }
    } catch {
      /* KV read failure/limit: fall back to memory */
      if (countsMemory) return withPending(countsMemory.counts);
    }
  }
  countsMemory = { at: Date.now(), counts };
  return withPending(counts);
}

/**
 * Store exact counts (e.g. after a recount). Memory is updated immediately; the KV copy is refreshed at
 * most once per REGISTRY_COUNTS_PERSIST_MIN_SEC (read-before-write gate, so many isolates cannot multiply writes).
 */
export async function writeRegistryCounts(env: Env, counts: RegistryCounts): Promise<void> {
  pendingCounts.static_colors = pendingCounts.static_sound = pendingCounts.learned_colors = 0;
  countsMemory = { at: Date.now(), counts };
  if (!env.MOTION_KV) return;
  try {
    const prevRaw = await env.MOTION_KV.get(REGISTRY_COUNTS_KV_KEY);
    if (prevRaw) {
      const prev = JSON.parse(prevRaw) as RegistryCounts;
      const age = Date.now() - Date.parse(prev.updated_at || "");
      if (Number.isFinite(age) && age < REGISTRY_COUNTS_PERSIST_MIN_SEC * 1000) return;
    }
    await env.MOTION_KV.put(REGISTRY_COUNTS_KV_KEY, JSON.stringify(counts), { expirationTtl: 60 * 60 * 24 * 30 });
  } catch {
    /* KV limit or outage: memory copy still serves this isolate */
  }
}

/**
 * Note novel inserts. Memory only: ZERO KV operations (previously one KV get + put per POST).
 * The deltas are folded into reads and replaced by the next exact recount.
 */
export async function bumpRegistryCounts(_env: Env, delta: CountDelta): Promise<void> {
  pendingCounts.static_colors += delta.static_colors || 0;
  pendingCounts.static_sound += delta.static_sound || 0;
  pendingCounts.learned_colors += delta.learned_colors || 0;
}

/**
 * True row counts (COUNT(*), not a query-limited sample length) for every registry
 * surfaced by /api/registries. Served from a layered snapshot (memory -> Cache API -> rarely-written KV)
 * so the ~20 COUNT(*) queries run at most about once per TRUE_TOTALS_SOFT_TTL_SEC, and a D1 limit error
 * serves the stale copy instead of caching false zeros. Always reads the primary DB per the
 * coverage/health precedent (replica COUNT on large tables can return false zeros or hit CPU limit 7429).
 */
const TRUE_REGISTRY_TOTALS_KEY = "registries:true_totals:v2";
// ~20 COUNT(*)s incl. learned_blends (~280k rows) cost >300k rows per rebuild: 12 h => at most 2 rebuilds/day per colo
// (was hourly = up to 24). Display-only numbers; ?fresh=1 (rate limited) still forces a refresh.
export const TRUE_TOTALS_SOFT_TTL_SEC = 12 * 3600;

export type TrueRegistryTotals = {
  static_colors: number;
  static_sound: number;
  interpretation: number;
  linguistic: number;
  dynamic: Record<string, number>;
  narrative: Record<string, number>;
  computed_at: string;
  degraded?: boolean;
};

/** dynamic-section key -> backing D1 table (mirrors dynamicPayload keys in routes/registries.ts). */
const DYNAMIC_TOTAL_TABLES: Record<string, string> = {
  colors: "learned_colors",
  motion: "learned_motion",
  gradient: "learned_gradient",
  camera: "learned_camera",
  sound: "learned_audio_semantic",
  lighting: "learned_lighting",
  composition: "learned_composition",
  graphics: "learned_graphics",
  temporal: "learned_temporal",
  technical: "learned_technical",
  blends: "learned_blends",
  entities: "learned_entities",
};

const NARRATIVE_TOTAL_ASPECTS = ["genre", "mood", "themes", "plots", "settings", "style", "scene_type"];

async function computeTrueTotals(primaryDb: D1Database): Promise<TrueRegistryTotals> {
  const count = async (sql: string, bind?: string): Promise<number> => {
    try {
      const stmt = bind !== undefined ? primaryDb.prepare(sql).bind(bind) : primaryDb.prepare(sql);
      const row = await stmt.first<{ c: number }>();
      return row?.c ?? 0;
    } catch (e) {
      // A daily-limit error must not become a cached zero: surface it so the snapshot serves stale data.
      if (isFreeTierLimitError(e)) throw e;
      return 0;
    }
  };
  const [static_colors, static_sound, interpretation, linguistic] = await Promise.all([
    count("SELECT COUNT(*) as c FROM static_colors"),
    count("SELECT COUNT(*) as c FROM static_sound WHERE sound_key NOT LIKE 's2.%'"),
    count("SELECT COUNT(*) as c FROM interpretations WHERE status = 'done' AND instruction_json IS NOT NULL"),
    count("SELECT COUNT(*) as c FROM linguistic_registry"),
  ]);
  const dynamicEntries = await Promise.all(
    Object.entries(DYNAMIC_TOTAL_TABLES).map(
      async ([key, table]) => [key, await count(`SELECT COUNT(*) as c FROM ${table}`)] as const,
    ),
  );
  const narrativeEntries = await Promise.all(
    NARRATIVE_TOTAL_ASPECTS.map(
      async (aspect) => [aspect, await count("SELECT COUNT(*) as c FROM narrative_entries WHERE aspect = ?", aspect)] as const,
    ),
  );
  return {
    static_colors,
    static_sound,
    interpretation,
    linguistic,
    dynamic: Object.fromEntries(dynamicEntries),
    narrative: Object.fromEntries(narrativeEntries),
    computed_at: new Date().toISOString(),
  };
}

export async function getTrueRegistryTotals(
  env: Env,
  primaryDb: D1Database,
  opts: { fresh?: boolean } = {},
): Promise<TrueRegistryTotals | null> {
  try {
    const snap = await getSnapshot<TrueRegistryTotals>(
      env,
      TRUE_REGISTRY_TOTALS_KEY,
      {
        softTtlSec: TRUE_TOTALS_SOFT_TTL_SEC,
        hardTtlSec: 7 * 86400,
        kvPersistSec: 6 * 3600,
        bypass: opts.fresh,
        bypassMinIntervalSec: 300,
      },
      () => computeTrueTotals(primaryDb),
    );
    return snap.degraded ? { ...snap.value, degraded: true } : snap.value;
  } catch {
    return null;
  }
}