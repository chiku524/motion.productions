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
import { MISSION_STATS_KEY } from "./browseCache";
import {
  buildSoundOriginCountSql,
  mergeFamilyCounts,
  parseSoundOriginCounts,
  presentOrigins,
  type FamilyGroupRow,
} from "./missionAggregate";

export const MISSION_STATS_CACHE_KEY = MISSION_STATS_KEY;
const MISSION_STATS_TTL_SEC = 300;
/** Max NULL-family rows classified in JS to attribute never-backfilled rows. */
const NULL_FAMILY_SAMPLE = 400;

export type MissionFacet = {
  id: string;
  label: string;
  count: number;
  sample_rgb?: [number, number, number];
};

export type MissionStats = {
  colors: { total: number; families: MissionFacet[]; shades: MissionFacet[]; estimated_rows: number };
  sound: { total: number; origin_counts: Record<string, number>; origins_present: string[] };
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
      .prepare("SELECT depth_breakdown_json FROM static_sound ORDER BY rowid DESC LIMIT 3000")
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

/** Whole-table stats (KV-cached ~5 min; pass fresh=true to bypass). */
export async function loadMissionStats(env: Env, fresh = false): Promise<MissionStats> {
  const kv = env.MOTION_KV;
  if (kv && !fresh) {
    try {
      const cached = await kv.get(MISSION_STATS_CACHE_KEY, "json");
      if (cached && typeof cached === "object") return cached as MissionStats;
    } catch {
      /* rebuild */
    }
  }
  const [colors, sound] = await Promise.all([loadColorStats(env), loadSoundStats(env)]);
  const stats: MissionStats = { colors, sound, scan: "full", updated_at: new Date().toISOString() };
  if (kv) {
    try {
      await kv.put(MISSION_STATS_CACHE_KEY, JSON.stringify(stats), { expirationTtl: MISSION_STATS_TTL_SEC });
    } catch {
      /* ignore */
    }
  }
  return stats;
}