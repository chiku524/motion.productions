/**
 * Full-table mission / coverage statistics for GET /api/registries/mission and
 * GET /api/registries/coverage.
 *
 * Previously these were computed from the 800 most-seen rows only (SCAN_CAP / ORDER BY count DESC),
 * so rare hue families (white!) and sound origins looked "missing" while coverage said "present".
 * Here every aggregate is a GROUP BY / single-scan SUM over the entire table, cached briefly in KV.
 */
import type { Env } from "./env";
import { getPrimaryDb, ensureStaticColorsFamilyColumns } from "./db";
import {
  COLOR_FAMILY_META,
  COLOR_SHADE_META,
  FAMILY_SAMPLE_RGB,
  classifyColorFamily,
  classifyColorShade,
} from "./colorBrowse";
import { SOUND_ORIGIN_PRIMARIES } from "./naming";
import { SOUND_V2_SPACE_SIZE, encodeSeenBitmap, hasSoundV2Prefix, parseSoundV2Key, soundV2Ordinal } from "./soundKeyspace";
import { MISSION_STATS_KEY } from "./browseCache";
import { getSnapshot } from "./snapshotCache";
import {
  buildSoundOriginCountSql,
  mergeFamilyCounts,
  parseSoundOriginCounts,
  presentOrigins,
  type FamilyGroupRow,
} from "./missionAggregate";

export const MISSION_STATS_CACHE_KEY = MISSION_STATS_KEY;
/** Rebuild at most this often (each rebuild scans ~4-5k D1 rows; 12/day = ~60k rows). */
const MISSION_STATS_SOFT_TTL_SEC = 2 * 3600;
/** KV hard expiry: keep the last good snapshot to serve if D1 is failing / rate-limited. */
const MISSION_STATS_HARD_TTL_SEC = 60 * 60 * 24 * 7;
/** Max NULL-family rows classified in JS to attribute never-backfilled rows. */
const NULL_FAMILY_SAMPLE = 400;

export type MissionFacet = {
  id: string;
  label: string;
  count: number;
  sample_rgb?: [number, number, number];
};

/** Evidence tiers (docs/EXHAUSTIVE_REGISTRY_PLAN.md): only observed + verified count as coverage. */
export const EVIDENCE_TIER_POLICY =
  "covered = observed + verified. declared (seeds, spec values, camera/audio-semantic/transition/depth guesses) never covers a cell. " +
  "D1 stores a tier only for sound v2 cells (depth_breakdown_json.tier); other categories are tiered client-side.";

export type SoundV2Stats = {
  space: "sound.L1";
  space_size: number;
  covered: number;
  coverage_pct: number;
  by_tier: { observed: number; verified: number; declared: number };
  /** Hex bitmap of covered cell ordinals (same layout as src/knowledge/sound_v2.py encode_bitmap). */
  seen_bitmap: string;
  tier_policy: string;
};

export type MissionStats = {
  colors: { total: number; families: MissionFacet[]; shades: MissionFacet[]; estimated_rows: number };
  sound: { total: number; origin_counts: Record<string, number>; origins_present: string[] };
  /** Additive (absent in snapshots cached before sound v2). */
  sound_v2?: SoundV2Stats;
  scan: "full";
  updated_at: string;
};

async function loadColorStats(env: Env): Promise<MissionStats["colors"]> {
  const db = getPrimaryDb(env);
  const familyOk = await ensureStaticColorsFamilyColumns(db);
  const familyIds = COLOR_FAMILY_META.map((m) => m.id as string);
  const shadeIds = COLOR_SHADE_META.map((m) => m.id as string);

  let famGroups: FamilyGroupRow[] = [];
  let shadeGroups: FamilyGroupRow[] = [];
  let nullSampleFamilies: string[] = [];
  let nullSampleShades: string[] = [];
  let total = 0;

  if (familyOk) {
    const f = await db
      .prepare("SELECT family AS family, COUNT(*) AS c FROM static_colors GROUP BY family")
      .all<{ family: string | null; c: number }>();
    famGroups = (f.results || []).map((r) => ({ family: r.family, c: r.c }));
    const s = await db
      .prepare("SELECT shade AS family, COUNT(*) AS c FROM static_colors GROUP BY shade")
      .all<{ family: string | null; c: number }>();
    shadeGroups = (s.results || []).map((r) => ({ family: r.family, c: r.c }));
    total = famGroups.reduce((a, r) => a + (Number(r.c) || 0), 0);
    if (famGroups.some((r) => !r.family)) {
      const sample = await db
        .prepare("SELECT r, g, b FROM static_colors WHERE family IS NULL LIMIT ?")
        .bind(NULL_FAMILY_SAMPLE)
        .all<{ r: number; g: number; b: number }>();
      for (const row of sample.results || []) {
        const fam = classifyColorFamily(row.r, row.g, row.b);
        nullSampleFamilies.push(fam);
        nullSampleShades.push(classifyColorShade(row.r, row.g, row.b, fam));
      }
    }
  } else {
    // Legacy schema without family/shade columns: classify a bounded sample, scale to COUNT(*).
    const c = await db.prepare("SELECT COUNT(*) AS c FROM static_colors").first<{ c: number }>();
    total = c?.c ?? 0;
    const sample = await db
      .prepare("SELECT r, g, b FROM static_colors LIMIT ?")
      .bind(NULL_FAMILY_SAMPLE)
      .all<{ r: number; g: number; b: number }>();
    for (const row of sample.results || []) {
      const fam = classifyColorFamily(row.r, row.g, row.b);
      nullSampleFamilies.push(fam);
      nullSampleShades.push(classifyColorShade(row.r, row.g, row.b, fam));
    }
    famGroups = [{ family: null, c: total }];
    shadeGroups = [{ family: null, c: total }];
  }

  const famCounts = mergeFamilyCounts(familyIds, famGroups, nullSampleFamilies);
  const shadeCounts = mergeFamilyCounts(shadeIds, shadeGroups, nullSampleShades);
  const estimated = famGroups.filter((r) => !r.family).reduce((a, r) => a + (Number(r.c) || 0), 0);

  return {
    total,
    estimated_rows: estimated,
    // Every family is listed (count may be 0) so callers can target the empty ones.
    families: COLOR_FAMILY_META.map((m) => ({
      id: m.id,
      label: m.label,
      count: famCounts[m.id] || 0,
      sample_rgb: FAMILY_SAMPLE_RGB[m.id],
    })),
    shades: COLOR_SHADE_META.map((m) => ({ id: m.id, label: m.label, count: shadeCounts[m.id] || 0 })),
  };
}

/** Sound v2 coverage from the (<= 6144) `s2.` rows of static_sound; part of the cached 2 h snapshot. */
export async function loadSoundV2Stats(env: Env): Promise<SoundV2Stats> {
  const db = getPrimaryDb(env);
  const ordinals: number[] = [];
  const by = { observed: 0, verified: 0, declared: 0 };
  try {
    const rows = await db
      .prepare(
        "SELECT sound_key, CASE WHEN json_valid(depth_breakdown_json) THEN json_extract(depth_breakdown_json, '$.tier') END AS tier " +
          "FROM static_sound WHERE sound_key LIKE 's2.%'",
      )
      .all<{ sound_key: string; tier: string | null }>();
    for (const r of rows.results || []) {
      const bins = hasSoundV2Prefix(r.sound_key) ? parseSoundV2Key(r.sound_key) : null;
      if (!bins) continue;
      const tier = r.tier === "verified" ? "verified" : r.tier === "declared" ? "declared" : "observed";
      by[tier] += 1;
      if (tier !== "declared") ordinals.push(soundV2Ordinal(bins));
    }
  } catch (e) {
    console.error("mission sound v2 scan failed:", e);
  }
  const covered = by.observed + by.verified;
  return {
    space: "sound.L1",
    space_size: SOUND_V2_SPACE_SIZE,
    covered,
    coverage_pct: Math.round((100 * covered) / SOUND_V2_SPACE_SIZE * 1000) / 1000,
    by_tier: by,
    seen_bitmap: encodeSeenBitmap(ordinals),
    tier_policy: EVIDENCE_TIER_POLICY,
  };
}

async function loadSoundStats(env: Env): Promise<MissionStats["sound"]> {
  const db = getPrimaryDb(env);
  const origins = SOUND_ORIGIN_PRIMARIES as readonly string[];
  try {
    const row = await db.prepare(buildSoundOriginCountSql(origins)).first<Record<string, unknown>>();
    const { total, counts } = parseSoundOriginCounts(origins, row);
    return { total, origin_counts: counts, origins_present: presentOrigins(counts) };
  } catch (e) {
    console.error("mission sound origin scan failed; falling back to bounded JS scan:", e);
  }
  // Fallback (json_extract unavailable / malformed JSON): bounded scan in JS, newest rows first.
  const counts: Record<string, number> = {};
  for (const o of origins) counts[o] = 0;
  let total = 0;
  try {
    const rows = await db
      .prepare("SELECT depth_breakdown_json FROM static_sound WHERE sound_key NOT LIKE 's2.%' ORDER BY rowid DESC LIMIT 3000")
      .all<{ depth_breakdown_json: string | null }>();
    for (const r of rows.results || []) {
      total += 1;
      if (!r.depth_breakdown_json) continue;
      try {
        const d = JSON.parse(r.depth_breakdown_json) as Record<string, unknown>;
        const oc = (d.origin_noises || {}) as Record<string, unknown>;
        for (const o of origins) {
          const v = Number(oc[o] ?? d[o]);
          if (v > 0) counts[o] += 1;
        }
      } catch {
        /* ignore malformed row */
      }
    }
  } catch {
    /* static_sound may not exist */
  }
  return { total, origin_counts: counts, origins_present: presentOrigins(counts) };
}

/**
 * Whole-table stats. Cached in KV; rebuilt at most every MISSION_STATS_SOFT_TTL_SEC (pass fresh=true
 * to bypass). If a rebuild fails (e.g. D1 free-tier row-read limit) the last good snapshot is served
 * instead of failing the request.
 */
export async function loadMissionStats(env: Env, fresh = false): Promise<MissionStats> {
  const snap = await getSnapshot<MissionStats>(
    env,
    MISSION_STATS_CACHE_KEY,
    {
      softTtlSec: MISSION_STATS_SOFT_TTL_SEC,
      hardTtlSec: MISSION_STATS_HARD_TTL_SEC,
      kvPersistSec: 6 * 3600,
      bypass: fresh,
      bypassMinIntervalSec: 300,
    },
    async () => {
      const [colors, sound, sound_v2] = await Promise.all([loadColorStats(env), loadSoundStats(env), loadSoundV2Stats(env)]);
      return { colors, sound, sound_v2, scan: "full", updated_at: new Date().toISOString() } as MissionStats;
    },
  );
  return snap.value;
}
