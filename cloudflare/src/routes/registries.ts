/**
 * Registries export, coverage, health, backfill API routes.
 */
import type { Env } from "../env";
import {
  getDb,
  getPrimaryDb,
  readRegistryCounts,
  writeRegistryCounts,
  ensureLearnedDynamicMetaTable,
  ensureLearnedColorsDepthColumn,
} from "../db";
import { json, err, normalizeOpacityToPercent } from "../http";
import { COLOR_PRIMARIES_FOR_API, COLOR_PRIMITIVE_NAMES } from "../colorPrimaries.generated";
import {
  STATIC_COLOR_ESTIMATED_CELLS,
  ENTITY_ESTIMATED_CELLS,
  SETTING_ESTIMATED_CELLS,
  SETTING_PRIMITIVES,
  NARRATIVE_ORIGIN_SIZES,
  DYNAMIC_CANONICAL,
} from "../registryConstants.generated";
import {
  SOUND_ORIGIN_PRIMARIES,
  inventSemanticWord,
  toTitleCase,
  isGibberishName,
  titleCaseLabel,
  shouldBackfillNarrativeName,
  rgbToSemanticHint,
  cascadeNameUpdate,
  shouldBackfillColorName,
  sanitizePureSoundKey,
  pureSoundKeyHasLeak,
  computeMotionDepth,
  RGB_COLOR_VOCAB,
} from "../naming";
import { handleRegistryBrowse } from "./registryBrowse";
import { invalidateRegistryReadCaches } from "../browseCache";

const SOUND_PRIMARIES_FOR_COVERAGE = [...SOUND_ORIGIN_PRIMARIES] as string[];

export async function handleRegistriesRoutes(
  request: Request,
  env: Env,
  path: string,
): Promise<Response | null> {
  const browseResp = await handleRegistryBrowse(request, env, path);
  if (browseResp) return browseResp;

  // Coverage / health COUNTs must hit primary — replica COUNT on large static_colors hits 7429 / false zeros.
  const db =
    path === "/api/registries/coverage" || path === "/api/registries/health"
      ? getPrimaryDb(env)
      : getDb(env);

// POST /api/registries/backfill-names — replace gibberish/inauthentic names with semantic ones
if (path === "/api/registries/backfill-names" && request.method === "POST") {
  const url = new URL(request.url);
  const dryRun = url.searchParams.get("dry_run") === "1";
  const maxRows = Math.min(parseInt(url.searchParams.get("limit") || "100", 10), 500);
  const tableFilter = url.searchParams.get("table")?.toLowerCase().trim() || null;
  let updated = 0;
  const usedNames = new Set<string>();
  const pickUniqueName = async (): Promise<string> => {
    for (let i = 0; i < 50; i++) {
      const seed = Math.floor(Math.random() * 1000000) + i * 7919;
      const word = inventSemanticWord(seed);
      const name = toTitleCase(word);
      if (usedNames.has(name)) continue;
      const inDb = await db.prepare("SELECT 1 FROM learned_blends WHERE name = ?").bind(name).first();
      if (inDb) continue;
      usedNames.add(name);
      return name;
    }
    return "Novel" + (Math.floor(Math.random() * 100000) + 1).toString().padStart(5, "0");
  };
  const rgbToSemanticColorName = (r: number, g: number, b: number, existing: Set<string>): string => {
    const hint = rgbToSemanticHint(r, g, b);
    const vocab = RGB_COLOR_VOCAB[hint] ?? [hint];
    for (const w of vocab) {
      const c = w.length > 1 ? w[0].toUpperCase() + w.slice(1).toLowerCase() : w.toUpperCase();
      if (!existing.has(c)) return c;
    }
    const seed = Math.abs((r * 31 + g * 37 + b * 41) % 0x7fffffff) + existing.size * 7919;
    const word = inventSemanticWord(seed);
    const name = toTitleCase(word);
    if (!existing.has(name)) return name;
    return "Novel" + (Math.abs(seed) % 100000).toString().padStart(5, "0");
  };
  try {
    // Color tables: use RGB-driven semantic naming
    const colorTables = (["static_colors", "learned_colors"] as const).filter(
      (t) => !tableFilter || t === tableFilter
    );
    for (const table of colorTables) {
      try {
        const rows = await db.prepare(
          `SELECT id, name, r, g, b FROM ${table} WHERE name GLOB 'dsc_*' OR name GLOB 'Novel*' OR name GLOB 'color_*'
           OR name GLOB '*[0-9][0-9]*' OR LENGTH(TRIM(name)) > 9 LIMIT ?`
        ).bind(maxRows).all<{ id: string; name: string; r: number; g: number; b: number }>();
        for (const r of rows.results || []) {
          const row = r as { id: string; name: string | null; r: number; g: number; b: number };
          if (updated >= maxRows) break;
          if (shouldBackfillColorName(row.name)) {
            const oldName = row.name;
            const newName = rgbToSemanticColorName(row.r ?? 0, row.g ?? 0, row.b ?? 0, usedNames);
            usedNames.add(newName);
            if (!dryRun) {
              await db.prepare(`UPDATE ${table} SET name = ? WHERE id = ?`)
                .bind(newName, row.id)
                .run();
              await cascadeNameUpdate(env, oldName ?? "", newName);
            }
            updated++;
          }
        }
      } catch {
        /* table may not exist */
      }
    }
    // Narrative: replace gibberish or unrelated names with readable title-case value
    if (!tableFilter || tableFilter === "narrative_entries") {
      try {
        const rows = await db.prepare(
          `SELECT id, aspect, entry_key, value, name FROM narrative_entries
           WHERE name IS NULL OR TRIM(name) = ''
           OR name GLOB 'dsc_*' OR name GLOB 'Novel*'
           OR name GLOB 'theme_*' OR name GLOB 'plot_*' OR name GLOB 'setting_*'
           OR name GLOB 'scene_*' OR name GLOB 'genre_*' OR name GLOB 'mood_*' OR name GLOB 'style_*'
           OR name GLOB '*[0-9][0-9]*' OR LENGTH(TRIM(name)) > 9
           OR (LENGTH(TRIM(entry_key)) >= 3 AND INSTR(LOWER(TRIM(COALESCE(name, ''))), LOWER(TRIM(entry_key))) = 0)
           LIMIT ?`
        ).bind(maxRows).all<{ id: string; aspect: string; entry_key: string; value: string | null; name: string | null }>();
        for (const r of rows.results || []) {
          const row = r as { id: string; aspect: string; entry_key: string; value: string | null; name: string | null };
          if (updated >= maxRows) break;
          const readable = titleCaseLabel((row.value || row.entry_key || "").trim());
          if (!readable) continue;
          const current = (row.name || "").trim();
          if (current === readable) continue;
          if (!shouldBackfillNarrativeName(current, row.entry_key, row.value || row.entry_key)) continue;
          const oldName = row.name;
          if (!dryRun) {
            await db.prepare("UPDATE narrative_entries SET name = ? WHERE id = ?").bind(readable, row.id).run();
            await cascadeNameUpdate(env, oldName ?? "", readable);
          }
          updated++;
        }
      } catch {
        /* table may not exist */
      }
    }
    // Non-color tables: generic semantic names
    const otherTablesAll = [
      { table: "learned_motion", idCol: "id", nameCol: "name" },
      { table: "learned_blends", idCol: "id", nameCol: "name" },
      { table: "learned_gradient", idCol: "id", nameCol: "name" },
      { table: "learned_camera", idCol: "id", nameCol: "name" },
      { table: "learned_lighting", idCol: "id", nameCol: "name" },
      { table: "learned_composition", idCol: "id", nameCol: "name" },
      { table: "learned_graphics", idCol: "id", nameCol: "name" },
      { table: "learned_temporal", idCol: "id", nameCol: "name" },
      { table: "learned_technical", idCol: "id", nameCol: "name" },
      { table: "learned_audio_semantic", idCol: "id", nameCol: "name" },
      { table: "learned_time", idCol: "id", nameCol: "name" },
      { table: "learned_transition", idCol: "id", nameCol: "name" },
      { table: "learned_depth", idCol: "id", nameCol: "name" },
      { table: "static_sound", idCol: "id", nameCol: "name" },
    ];
    const otherTables = tableFilter
      ? otherTablesAll.filter((o) => o.table === tableFilter)
      : otherTablesAll;
    for (const { table, idCol, nameCol } of otherTables) {
      try {
        // Include dsc_*, Novel*, and long names (9+ chars) that may be gibberish
        const rows = await db.prepare(
          `SELECT ${idCol}, ${nameCol} FROM ${table} WHERE ${nameCol} GLOB 'dsc_*' OR ${nameCol} GLOB 'Novel*'
           OR ${nameCol} GLOB '*[0-9][0-9]*' OR LENGTH(TRIM(${nameCol})) > 9 LIMIT ?`
        ).bind(maxRows).all<{ id: string; name: string }>();
        for (const r of rows.results || []) {
          const row = r as { id: string; name: string | null };
          if (updated >= maxRows) break;
          if (isGibberishName(row.name)) {
            const oldName = row.name;
            const newName = await pickUniqueName();
            if (!dryRun) {
              await db.prepare(`UPDATE ${table} SET ${nameCol} = ? WHERE ${idCol} = ?`)
                .bind(newName, row.id)
                .run();
              await cascadeNameUpdate(env, oldName ?? "", newName);
            }
            updated++;
          }
        }
      } catch {
        /* table may not exist */
      }
    }
    if (!dryRun && updated > 0) {
      try {
        await invalidateRegistryReadCaches(env);
      } catch {
        /* ignore */
      }
    }
    return json({ updated, dry_run: dryRun, limit: maxRows });
  } catch (e) {
    console.error("Backfill names failed:", e);
    return json({ error: "Backfill failed", details: String(e) }, 500);
  }
}

// GET /api/registries/backfill-rows — raw rows for depth recalculation (Python script)
if (path === "/api/registries/backfill-rows" && request.method === "GET") {
  const url = new URL(request.url);
  const table = url.searchParams.get("table") || "";
  const limit = Math.min(parseInt(url.searchParams.get("limit") || "50", 10), 200);
  if (!table) return err("table required");
  const valid = ["static_colors", "learned_colors", "learned_motion", "learned_lighting"];
  if (!valid.includes(table)) return err("table must be one of: " + valid.join(", "));
  try {
    let rows: unknown[] = [];
    if (table === "static_colors") {
      const r = await db.prepare(
        "SELECT id, r, g, b FROM static_colors LIMIT ?"
      ).bind(limit).all<{ id: string; r: number; g: number; b: number }>();
      rows = r.results || [];
    } else if (table === "learned_colors") {
      const r = await db.prepare(
        "SELECT id, color_key, r, g, b FROM learned_colors LIMIT ?"
      ).bind(limit).all<{ id: string; color_key: string; r: number; g: number; b: number }>();
      rows = r.results || [];
    } else if (table === "learned_motion") {
      const r = await db.prepare(
        "SELECT id, motion_level, motion_trend FROM learned_motion WHERE depth_breakdown_json IS NULL LIMIT ?"
      ).bind(limit).all<{ id: string; motion_level: number; motion_trend: string }>();
      rows = r.results || [];
    } else if (table === "learned_lighting") {
      const r = await db.prepare(
        "SELECT id, brightness, contrast, saturation FROM learned_lighting WHERE depth_breakdown_json IS NULL LIMIT ?"
      ).bind(limit).all<{ id: string; brightness: number; contrast: number; saturation: number }>();
      rows = r.results || [];
    }
    return json({ table, rows });
  } catch (e) {
    console.error("GET backfill-rows failed:", e);
    return json({ error: "Backfill rows failed", details: String(e) }, 500);
  }
}

// POST /api/registries/backfill-depths — update depth_breakdown (from Python script)
if (path === "/api/registries/backfill-depths" && request.method === "POST") {
  let body: { updates?: Array<{ table: string; id: string; depth_breakdown: Record<string, number> }> };
  try {
    body = (await request.json()) as typeof body;
  } catch {
    return err("Invalid JSON");
  }
  const updates = body.updates || [];
  if (updates.some((u) => u.table === "learned_colors")) {
    const depthOk = await ensureLearnedColorsDepthColumn(db);
    if (!depthOk) {
      return json(
        {
          error:
            "learned_colors.depth_breakdown_json is not available yet (D1 ALTER pending). Retry later or add the column in the D1 dashboard.",
        },
        503,
      );
    }
  }
  const dryRun = new URL(request.url).searchParams.get("dry_run") === "1";
  let updated = 0;
  const depthTables: Record<string, string> = {
    static_colors: "depth_breakdown_json",
    learned_colors: "depth_breakdown_json",
    learned_motion: "depth_breakdown_json",
    learned_lighting: "depth_breakdown_json",
  };
  for (const u of updates) {
    const col = depthTables[u.table];
    if (!col) continue;
    try {
      if (!dryRun) {
        await db.prepare(
          `UPDATE ${u.table} SET ${col} = ? WHERE id = ?`
        )
          .bind(JSON.stringify(u.depth_breakdown), u.id)
          .run();
      }
      updated++;
    } catch {
      /* skip */
    }
  }
  return json({ updated, dry_run: dryRun });
}

// GET /api/registries/health — readability and data-quality issue counts
if (path === "/api/registries/health" && request.method === "GET") {
  let pureSoundSemanticKeys = 0;
  let pureSoundTotal = 0;
  let motionMissingDepth = 0;
  let motionTotal = 0;
  let lightingMissingDepth = 0;
  let lightingTotal = 0;
  let gibberishNames = 0;
  let narrativeNameMismatches = 0;
  try {
    const ss = await db.prepare("SELECT sound_key FROM static_sound LIMIT 1000")
      .all<{ sound_key: string }>();
    for (const r of ss.results || []) {
      pureSoundTotal++;
      if (pureSoundKeyHasLeak(r.sound_key)) pureSoundSemanticKeys++;
    }
  } catch { /* static_sound may not exist */ }
  try {
    const lm = await db.prepare("SELECT profile_key, depth_breakdown_json FROM learned_motion LIMIT 1000")
      .all<{ profile_key: string; depth_breakdown_json: string | null }>();
    for (const r of lm.results || []) {
      motionTotal++;
      if (!r.depth_breakdown_json) motionMissingDepth++;
    }
  } catch { /* ignore */ }
  try {
    const ll = await db.prepare("SELECT profile_key, depth_breakdown_json FROM learned_lighting LIMIT 1000")
      .all<{ profile_key: string; depth_breakdown_json: string | null }>();
    for (const r of ll.results || []) {
      lightingTotal++;
      if (!r.depth_breakdown_json) lightingMissingDepth++;
    }
  } catch { /* ignore */ }
  const nameTables = [
    { table: "learned_motion", col: "name" },
    { table: "learned_lighting", col: "name" },
    { table: "learned_colors", col: "name" },
    { table: "learned_blends", col: "name" },
    { table: "static_sound", col: "name" },
    { table: "learned_composition", col: "name" },
    { table: "learned_graphics", col: "name" },
  ];
  for (const { table, col } of nameTables) {
    try {
      const rows = await db.prepare(`SELECT ${col} as name FROM ${table} LIMIT 500`)
        .all<{ name: string | null }>();
      for (const r of rows.results || []) {
        if (isGibberishName(r.name)) gibberishNames++;
      }
    } catch { /* table may not exist */ }
  }
  const narrativeAspects = ["genre", "mood", "themes", "plots", "settings", "style", "scene_type"];
  for (const aspect of narrativeAspects) {
    try {
      const rows = await db.prepare(
        "SELECT entry_key, value, name FROM narrative_entries WHERE aspect = ? LIMIT 200"
      ).bind(aspect).all<{ entry_key: string; value: string | null; name: string | null }>();
      for (const r of rows.results || []) {
        if (shouldBackfillNarrativeName(r.name, r.entry_key, r.value || r.entry_key)) narrativeNameMismatches++;
      }
    } catch { /* ignore */ }
  }
  const recommendations: string[] = [];
  if (pureSoundSemanticKeys > 0) {
    recommendations.push(`Run POST /api/registries/sanitize-sound-keys to fix ${pureSoundSemanticKeys} Pure sound keys with mood leakage`);
  }
  if (motionMissingDepth > 0) {
    recommendations.push(`Run registry_cleanup.py depths --table learned_motion (${motionMissingDepth} missing depth)`);
  }
  if (gibberishNames > 0) {
    recommendations.push(`Run registry_cleanup.py names to fix ~${gibberishNames} gibberish display names`);
  }
  return json({
    ok: pureSoundSemanticKeys === 0 && motionMissingDepth === 0 && narrativeNameMismatches === 0,
    issues: {
      pure_sound_semantic_keys: pureSoundSemanticKeys,
      pure_sound_total: pureSoundTotal,
      blended_motion_missing_depth: motionMissingDepth,
      blended_motion_total: motionTotal,
      blended_lighting_missing_depth: lightingMissingDepth,
      blended_lighting_total: lightingTotal,
      gibberish_names_estimate: gibberishNames,
      narrative_name_mismatches: narrativeNameMismatches,
    },
    recommendations,
  });
}

// POST /api/registries/sanitize-sound-keys — canonicalize Pure sound keys (merge duplicates)
if (path === "/api/registries/sanitize-sound-keys" && request.method === "POST") {
  const dryRun = new URL(request.url).searchParams.get("dry_run") === "1";
  let updated = 0;
  let merged = 0;
  try {
    const rows = await db.prepare("SELECT id, sound_key, count FROM static_sound").all<{ id: string; sound_key: string; count: number }>();
    for (const row of rows.results || []) {
      const canonical = sanitizePureSoundKey(row.sound_key);
      if (canonical === row.sound_key) continue;
      const target = await db.prepare("SELECT id, count FROM static_sound WHERE sound_key = ?").bind(canonical).first<{ id: string; count: number }>();
      if (!dryRun) {
        if (target) {
          await db.prepare("UPDATE static_sound SET count = count + ? WHERE sound_key = ?").bind(row.count, canonical).run();
          await db.prepare("DELETE FROM static_sound WHERE id = ?").bind(row.id).run();
          merged++;
        } else {
          await db.prepare("UPDATE static_sound SET sound_key = ? WHERE id = ?").bind(canonical, row.id).run();
          updated++;
        }
      } else {
        if (target) merged++; else updated++;
      }
    }
  } catch (e) {
    return json({ error: "Sanitize failed", details: String(e) }, 500);
  }
  return json({ updated, merged, dry_run: dryRun });
}

// GET /api/registries/coverage — counts and coverage % per registry for completion targeting (§2.1, §2.8)
if (path === "/api/registries/coverage" && request.method === "GET") {
  const coverageCacheKey = "registries:coverage";
  const bypassCache = new URL(request.url).searchParams.get("fresh") === "1";
  if (env.MOTION_KV && !bypassCache) {
    const cached = await env.MOTION_KV.get(coverageCacheKey);
    if (cached) {
      try {
        const parsed = JSON.parse(cached) as { static_colors_count?: number; static_sound_count?: number };
        // Never serve a poisoned cache from a transient D1 COUNT failure (0 colors while sound exists).
        const colorsOk = (parsed.static_colors_count ?? 0) > 0 || (parsed.static_sound_count ?? 0) === 0;
        if (colorsOk) {
          return new Response(cached, { headers: { "Content-Type": "application/json", "X-Cache": "HIT" } });
        }
      } catch {
        /* rebuild */
      }
    }
  }
  // Sizes from registryConstants.generated.ts (full NARRATIVE_ORIGINS / cell space).
  const narrativeAspects = Object.keys(NARRATIVE_ORIGIN_SIZES);

  let staticColorsCount = 0;
  let staticSoundCount = 0;
  let learnedColorsCount = 0;
  let countsReliable = true;
  let countsSource: "d1" | "kv" | "mixed" = "d1";
  const soundPrimitives = new Set<string>();

  const kvCounts = await readRegistryCounts(env);

  async function countTable(sql: string): Promise<number | null> {
    try {
      const row = await db.prepare(sql).first<{ c: number }>();
      return row?.c ?? 0;
    } catch {
      return null;
    }
  }

  // Prefer cheap KV counters when present; refresh from D1 only when missing or ?fresh=1.
  if (kvCounts && !bypassCache) {
    staticColorsCount = kvCounts.static_colors;
    staticSoundCount = kvCounts.static_sound;
    learnedColorsCount = kvCounts.learned_colors;
    countsSource = "kv";
  } else {
    const scCount = await countTable("SELECT COUNT(*) as c FROM static_colors");
    const ssCount = await countTable("SELECT COUNT(*) as c FROM static_sound");
    const lcCount = await countTable("SELECT COUNT(*) as c FROM learned_colors");
    if (scCount == null || ssCount == null) {
      countsReliable = false;
      if (kvCounts) {
        staticColorsCount = kvCounts.static_colors;
        staticSoundCount = kvCounts.static_sound;
        learnedColorsCount = kvCounts.learned_colors;
        countsSource = "kv";
        countsReliable = true;
      }
    } else {
      staticColorsCount = scCount;
      staticSoundCount = ssCount;
      learnedColorsCount = lcCount ?? (kvCounts?.learned_colors ?? 0);
      countsSource = "d1";
      await writeRegistryCounts(env, {
        static_colors: staticColorsCount,
        static_sound: staticSoundCount,
        learned_colors: learnedColorsCount,
        updated_at: new Date().toISOString(),
      });
    }
  }

  // Guard: if colors look empty but sound exists, try probe + KV before trusting zero.
  if (staticColorsCount === 0 && staticSoundCount > 0) {
    try {
      const probe = await db.prepare("SELECT 1 as ok FROM static_colors LIMIT 1").first<{ ok: number }>();
      if (probe && kvCounts && kvCounts.static_colors > 0) {
        staticColorsCount = kvCounts.static_colors;
        countsSource = "mixed";
      } else if (probe) {
        // Table non-empty but COUNT failed — avoid caching a false zero.
        countsReliable = false;
        if (kvCounts && kvCounts.static_colors > 0) {
          staticColorsCount = kvCounts.static_colors;
          countsSource = "kv";
        }
      }
    } catch { /* ignore */ }
  }

  try {
    const rows = await db.prepare("SELECT depth_breakdown_json FROM static_sound LIMIT 200")
      .all<{ depth_breakdown_json: string | null }>();
    for (const r of rows.results || []) {
      if (!r.depth_breakdown_json) continue;
      try {
        const d = JSON.parse(r.depth_breakdown_json) as Record<string, unknown>;
        const oc = d.origin_noises as Record<string, unknown> | undefined;
        if (oc && typeof oc === "object") {
          for (const k of Object.keys(oc)) soundPrimitives.add(k.toLowerCase());
        }
        for (const k of Object.keys(d)) {
          if (k !== "origin_noises" && typeof d[k] === "number") soundPrimitives.add(k.toLowerCase());
        }
      } catch { /* ignore */ }
    }
  } catch { /* ignore */ }

  const staticColorsCoveragePct = STATIC_COLOR_ESTIMATED_CELLS > 0
    ? Math.min(100, Math.round((100 * staticColorsCount) / STATIC_COLOR_ESTIMATED_CELLS * 100) / 100)
    : 0;
  const narrative: Record<string, { count: number; origin_size: number; coverage_pct: number; entry_keys: string[] }> = {};
  for (const aspect of narrativeAspects) {
    const originSize = NARRATIVE_ORIGIN_SIZES[aspect] ?? 0;
    try {
      const r = await db.prepare(
        "SELECT entry_key FROM narrative_entries WHERE aspect = ?"
      ).bind(aspect).all<{ entry_key: string }>();
      const entryKeys = [...new Set((r.results || []).map((x) => x.entry_key))];
      const count = entryKeys.length;
      narrative[aspect] = {
        count,
        origin_size: originSize,
        coverage_pct: originSize > 0 ? Math.min(100, Math.round((100 * count) / originSize * 100) / 100) : 0,
        entry_keys: entryKeys,
      };
    } catch {
      narrative[aspect] = { count: 0, origin_size: originSize, coverage_pct: 0, entry_keys: [] };
    }
  }

  const plotsCov = narrative["plots"]?.coverage_pct ?? 0;
  const styleCov = narrative["style"]?.coverage_pct ?? 0;
  const narrativePlotsStyleMinCoveragePct = Math.min(plotsCov, styleCov);

  let learnedEntitiesCount = 0;
  try {
    const er = await countTable("SELECT COUNT(*) as c FROM learned_entities");
    learnedEntitiesCount = er ?? 0;
  } catch {
    learnedEntitiesCount = 0;
  }
  const entitiesCoveragePct =
    ENTITY_ESTIMATED_CELLS > 0
      ? Math.min(100, Math.round((100 * learnedEntitiesCount) / ENTITY_ESTIMATED_CELLS * 100) / 100)
      : 0;

  // Setting backdrop coverage: distinct narrative settings that match SETTING_PRIMITIVES
  const settingKeys = new Set(
    (narrative["settings"]?.entry_keys || []).map((k) => String(k).toLowerCase()),
  );
  const settingsPresent = SETTING_PRIMITIVES.filter((s) => settingKeys.has(s));
  const settingsCoveragePct =
    SETTING_ESTIMATED_CELLS > 0
      ? Math.min(100, Math.round((100 * settingsPresent.length) / SETTING_ESTIMATED_CELLS * 100) / 100)
      : 0;

  const coverage = {
    static_colors_count: staticColorsCount,
    static_colors_estimated_cells: STATIC_COLOR_ESTIMATED_CELLS,
    /** Progress vs full quantized RGB×opacity cell space (~28k); low values are normal without dense sweep. */
    static_colors_coverage_pct: staticColorsCoveragePct,
    primitive_color_catalog_size: COLOR_PRIMARIES_FOR_API.length,
    static_sound_count: staticSoundCount,
    counts_source: countsSource,
    counts_reliable: countsReliable,
    static_sound_primitives_present: SOUND_PRIMARIES_FOR_COVERAGE.filter((p) => soundPrimitives.has(p)),
    static_sound_primitives_missing: SOUND_PRIMARIES_FOR_COVERAGE.filter((p) => !soundPrimitives.has(p)),
    static_sound_has_silence: soundPrimitives.has("silence"),
    static_sound_has_rumble: soundPrimitives.has("rumble"),
    static_sound_has_tone: soundPrimitives.has("tone"),
    static_sound_has_hiss: soundPrimitives.has("hiss"),
    static_sound_primitive_count: SOUND_PRIMARIES_FOR_COVERAGE.filter((p) => soundPrimitives.has(p)).length,
    static_sound_all_primitives: SOUND_PRIMARIES_FOR_COVERAGE.every((p) => soundPrimitives.has(p)),
    static_sound_num_primitives: SOUND_PRIMARIES_FOR_COVERAGE.length,
    static_sound_coverage_pct: SOUND_PRIMARIES_FOR_COVERAGE.length
      ? Math.round(
          (100 * SOUND_PRIMARIES_FOR_COVERAGE.filter((p) => soundPrimitives.has(p)).length) /
            SOUND_PRIMARIES_FOR_COVERAGE.length *
            100,
        ) / 100
      : 0,
    learned_colors_count: learnedColorsCount,
    learned_entities_count: learnedEntitiesCount,
    learned_entities_estimated_cells: ENTITY_ESTIMATED_CELLS,
    learned_entities_coverage_pct: entitiesCoveragePct,
    setting_primitives_present: settingsPresent,
    setting_primitives_missing: SETTING_PRIMITIVES.filter((s) => !settingKeys.has(s)),
    setting_estimated_cells: SETTING_ESTIMATED_CELLS,
    setting_coverage_pct: settingsCoveragePct,
    narrative,
    /** plots aspect stores tension_curve origins (flat/slow_build/standard/immediate). */
    tension_curve_note: "narrative.plots == NARRATIVE_ORIGINS.tension_curve",
    narrative_min_coverage_pct: narrativeAspects.length
      ? Math.min(...narrativeAspects.map((a) => narrative[a]?.coverage_pct ?? 0))
      : 0,
    narrative_plots_style_min_coverage_pct: narrativePlotsStyleMinCoveragePct,
    plots_coverage_pct: plotsCov,
    style_coverage_pct: styleCov,
    /** Mirrors src/knowledge/completion_targets.py for UI progress bars. */
    targets: {
      static_color_estimated_cells: STATIC_COLOR_ESTIMATED_CELLS,
      static_sound_num_primitives: SOUND_PRIMARIES_FOR_COVERAGE.length,
      entity_estimated_cells: ENTITY_ESTIMATED_CELLS,
      setting_estimated_cells: SETTING_ESTIMATED_CELLS,
      narrative_origin_sizes: { ...NARRATIVE_ORIGIN_SIZES },
      dynamic_canonical_sizes: {
        gradient: DYNAMIC_CANONICAL.gradient_type.length,
        camera: DYNAMIC_CANONICAL.camera_motion.length,
        motion: DYNAMIC_CANONICAL.motion.length,
        audio_tempo: DYNAMIC_CANONICAL.sound_tempo.length,
        audio_mood: DYNAMIC_CANONICAL.sound_mood.length,
        audio_presence: DYNAMIC_CANONICAL.sound_presence.length,
        entity_kind: (DYNAMIC_CANONICAL as { entity_kind?: readonly string[] }).entity_kind?.length ?? 4,
      },
      target_pct: 95,
    },
  };
  const coverageBody = JSON.stringify(coverage);
  // Only cache when COUNT queries succeeded and color count is non-zero (or both empty).
  const cacheSafe =
    countsReliable &&
    ((staticColorsCount > 0) || (staticSoundCount === 0 && staticColorsCount === 0));
  if (env.MOTION_KV && cacheSafe) {
    try {
      await env.MOTION_KV.put(coverageCacheKey, coverageBody, { expirationTtl: 120 });
    } catch { /* ignore */ }
  }
  return new Response(coverageBody, {
    headers: {
      "Content-Type": "application/json",
      "X-Cache": "MISS",
      ...(cacheSafe ? {} : { "X-Coverage-Unreliable": "1" }),
    },
  });
}

// GET /api/registries — pure (STATIC) vs non-pure (DYNAMIC + NARRATIVE); depth % vs primitives always
// Pure = single frame/pixel (static). Non-pure = multi-frame blends (gradient, motion, camera → dynamic).
if (path === "/api/registries" && request.method === "GET") {
  const regUrl = new URL(request.url);
  const regLimit = Math.min(Math.max(parseInt(regUrl.searchParams.get("limit") || "100", 10) || 100, 1), 200);
  const regOffset = Math.max(parseInt(regUrl.searchParams.get("offset") || "0", 10) || 0, 0);
  const sectionRaw = (regUrl.searchParams.get("section") || "all").toLowerCase();
  const section = ["all", "static", "dynamic", "narrative", "interpretation", "linguistic", "meta"].includes(sectionRaw)
    ? sectionRaw
    : "all";
  const pageSlice = <T>(arr: T[]): { items: T[]; total: number; truncated: boolean } => {
    const total = arr.length;
    const items = arr.slice(regOffset, regOffset + regLimit);
    return { items, total, truncated: regOffset + items.length < total };
  };
  // Pure primitives — synced from static_registry.py via scripts/gen_color_primaries_ts.py
  const staticPrimitives = {
    color_primaries: [...COLOR_PRIMARIES_FOR_API],
    sound_primaries: [...SOUND_PRIMARIES_FOR_COVERAGE],
  };
  // Blended canonical — generated from origins.py via scripts/gen_registry_constants_ts.py
  const dynamicCanonical = {
    gradient_type: [...DYNAMIC_CANONICAL.gradient_type],
    camera_motion: [...DYNAMIC_CANONICAL.camera_motion],
    motion: [...DYNAMIC_CANONICAL.motion],
    motion_speed: [...DYNAMIC_CANONICAL.motion_speed],
    motion_rhythm: [...DYNAMIC_CANONICAL.motion_rhythm],
    motion_smoothness: [...DYNAMIC_CANONICAL.motion_smoothness],
    motion_directionality: [...DYNAMIC_CANONICAL.motion_directionality],
    motion_acceleration: [...DYNAMIC_CANONICAL.motion_acceleration],
    sound: [...DYNAMIC_CANONICAL.sound],
    sound_tempo: [...DYNAMIC_CANONICAL.sound_tempo],
    sound_mood: [...DYNAMIC_CANONICAL.sound_mood],
    sound_presence: [...DYNAMIC_CANONICAL.sound_presence],
  };
  // Fast path: UI bootstrap must not touch D1 (DDL probes / full build cause 503 under loop load).
  if (section === "meta") {
    return json({
      limit: regLimit,
      offset: regOffset,
      section: "meta",
      truncated: false,
      totals: {},
      static_primitives: staticPrimitives,
      dynamic_canonical: dynamicCanonical,
    });
  }
  await ensureLearnedDynamicMetaTable(db);
  const learnedColorsDepthOk = await ensureLearnedColorsDepthColumn(db);
  // Canonical color key: always "r,g,b" (strip optional _opacity suffix from static keys for consistent export)
  const normalizeColorKey = (key: string): string => {
    const i = key.indexOf("_");
    return i > 0 ? key.slice(0, i) : key;
  };
  // Color primitives only (depth_breakdown must reference these; theme/preset names go to theme_breakdown; opacity to opacity_pct)
  type DepthSplit = { depth_breakdown: Record<string, number>; opacity_pct?: number; theme_breakdown?: Record<string, number> };
  const splitDepthBreakdown = (raw: Record<string, number> | null): DepthSplit => {
    const depth_breakdown: Record<string, number> = {};
    let opacity_pct: number | undefined;
    const theme_breakdown: Record<string, number> = {};
    if (!raw || typeof raw !== "object") return { depth_breakdown };
    for (const [k, v] of Object.entries(raw)) {
      if (k === "opacity") {
        opacity_pct = normalizeOpacityToPercent(v);
        continue;
      }
      const num = typeof v === "number" ? (v <= 1 ? Math.round(v * 100) : Math.round(v)) : 0;
      if (COLOR_PRIMITIVE_NAMES.has(k)) depth_breakdown[k] = num;
      else theme_breakdown[k] = num;
    }
    const out: DepthSplit = { depth_breakdown };
    if (opacity_pct != null) out.opacity_pct = opacity_pct;
    if (Object.keys(theme_breakdown).length > 0) out.theme_breakdown = theme_breakdown;
    return out;
  };
  // Depth vs black/white for a single RGB (e.g. grey = 50% white + 50% black)
  const colorDepthVsPrimitives = (r: number, g: number, b: number): { depth_pct: number; depth_breakdown: Record<string, number> } => {
    const L = Math.max(0, Math.min(1, (r + g + b) / (3 * 255)));
    const black = Math.round((1 - L) * 100) / 100;
    const white = Math.round(L * 100) / 100;
    const depth_breakdown: Record<string, number> = {};
    if (black > 0.01) depth_breakdown["black"] = black * 100;
    if (white > 0.01) depth_breakdown["white"] = white * 100;
    const depth_pct = Math.max(black, white) * 100;
    return { depth_pct, depth_breakdown };
  };
  // Make display names unique by appending " (key)" for duplicates
  const ensureUniqueColorNames = <T extends { name: string; key: string }>(items: T[]): T[] => {
    const seen = new Map<string, number>();
    return items.map((item) => {
      const name = item.name || item.key;
      const n = (seen.get(name) ?? 0) + 1;
      seen.set(name, n);
      const displayName = n > 1 ? `${name} (${item.key})` : name;
      return { ...item, name: displayName };
    });
  };
  // Correct known typos in narrative/semantic names (prefix + suffix)
  const NARRATIVE_NAME_TYPOS: Record<string, string> = {
    genre_starer: "genre_star", genre_starow: "genre_star",
    mood_amace: "mood_amber", mood_lumera: "mood_lumina", mood_luneber: "mood_lunar", mood_glowish: "mood_glow", mood_starwood: "mood_star",
  };
  const fixNarrativeName = (name: string): string => NARRATIVE_NAME_TYPOS[name] ?? name;
  const titleCaseLabel = (value: string): string => {
    const v = (value || "").trim();
    if (!v) return "";
    return v.split(/[\s_-]+/).filter(Boolean).map((w) => (w.length > 1 ? w[0].toUpperCase() + w.slice(1).toLowerCase() : w.toUpperCase())).join(" ");
  };
  const narrativeDisplayName = (entryKey: string, value: string, storedName: string | null): string => {
    const readable = titleCaseLabel(value || entryKey);
    if (!storedName || !storedName.trim()) return readable;
    const fixed = fixNarrativeName(storedName.trim());
    if (isGibberishName(fixed) || /^(theme|plot|setting|scene|genre|mood|style)_/i.test(fixed)) return readable;
    const ek = (entryKey || "").toLowerCase();
    if (ek.length >= 3 && !fixed.toLowerCase().includes(ek)) return readable;
    return fixed;
  };
  const formatReadableBlendKey = (key: string): string => {
    if (!key) return key;
    try {
      const parsed = JSON.parse(key) as Record<string, unknown>;
      if (parsed && typeof parsed === "object" && "r" in parsed && "g" in parsed && "b" in parsed) {
        const r = Math.round(Number(parsed.r));
        const g = Math.round(Number(parsed.g));
        const b = Math.round(Number(parsed.b));
        return `rgb(${r},${g},${b})`;
      }
    } catch { /* not JSON */ }
    return key.length > 60 ? key.slice(0, 57) + "…" : key;
  };
  // Section-scoped early returns: avoid full multi-table D1 build for tab loads.
  if (section === "static") {
    const staticColorsOnly = await db.prepare(
      "SELECT color_key, r, g, b, name, count, depth_breakdown_json FROM static_colors ORDER BY count DESC LIMIT ?"
    ).bind(regLimit).all<{ color_key: string; r: number; g: number; b: number; name: string; count: number; depth_breakdown_json: string | null }>();
    const staticSoundOnly = await db.prepare(
      "SELECT sound_key, name, count, depth_breakdown_json, strength_pct FROM static_sound ORDER BY count DESC LIMIT ?"
    ).bind(regLimit).all<{ sound_key: string; name: string; count: number; depth_breakdown_json: string | null; strength_pct: number | null }>();
    const colors = ensureUniqueColorNames((staticColorsOnly.results || []).map((r) => {
      let depth_pct = 0;
      let depth_breakdown: Record<string, number> = {};
      let opacity_pct: number | undefined;
      let theme_breakdown: Record<string, number> | undefined;
      if (r.depth_breakdown_json) {
        try {
          const stored = JSON.parse(r.depth_breakdown_json) as Record<string, unknown>;
          const raw: Record<string, number> = {};
          const oc = stored.origin_colors as Record<string, number> | undefined;
          if (oc && typeof oc === "object") {
            for (const [k, v] of Object.entries(oc)) {
              raw[k] = k === "opacity" ? normalizeOpacityToPercent(v) : (typeof v === "number" ? (v <= 1 ? Math.round(v * 100) : Math.round(v)) : 0);
            }
          }
          for (const [k, v] of Object.entries(stored)) {
            if (k === "origin_colors") continue;
            if (typeof v === "number") raw[k] = k === "opacity" ? normalizeOpacityToPercent(v) : (v <= 1 ? Math.round(v * 100) : Math.round(v));
          }
          const split = splitDepthBreakdown(raw);
          depth_breakdown = split.depth_breakdown;
          opacity_pct = split.opacity_pct;
          theme_breakdown = split.theme_breakdown;
          depth_pct = Object.keys(depth_breakdown).length || Object.keys(theme_breakdown || {}).length ? 100 : 0;
        } catch {
          const comp = colorDepthVsPrimitives(r.r, r.g, r.b);
          depth_pct = comp.depth_pct;
          depth_breakdown = comp.depth_breakdown;
        }
      } else {
        const comp = colorDepthVsPrimitives(r.r, r.g, r.b);
        depth_pct = comp.depth_pct;
        depth_breakdown = comp.depth_breakdown;
      }
      return {
        key: normalizeColorKey(r.color_key),
        name: r.name,
        r: r.r,
        g: r.g,
        b: r.b,
        count: r.count,
        depth_pct,
        depth_breakdown,
        ...(opacity_pct != null ? { opacity_pct } : {}),
        ...(theme_breakdown ? { theme_breakdown } : {}),
      };
    }));
    const SOUND_PRIMITIVES = [...SOUND_PRIMARIES_FOR_COVERAGE];
    const stripSoundPrefix = (n: string | null) => (n || "").replace(/^(Silent|Low|Mid|High)\s+/i, "").trim() || (n || "");
    const sound = (() => {
      const fromDb = (staticSoundOnly.results || []).map((r) => {
        let depth_breakdown: Record<string, number> = {};
        if (r.depth_breakdown_json) {
          try {
            const d = JSON.parse(r.depth_breakdown_json) as Record<string, unknown>;
            const oc = d.origin_noises as Record<string, number> | undefined;
            if (oc && typeof oc === "object") {
              for (const [k, v] of Object.entries(oc)) depth_breakdown[k] = typeof v === "number" ? (v <= 1 ? Math.round(v * 100) : Math.round(v)) : 0;
            }
            for (const [k, v] of Object.entries(d)) {
              if (k !== "origin_noises" && typeof v === "number") depth_breakdown[k] = v <= 1 ? Math.round(v * 100) : Math.round(v);
            }
          } catch { /* ignore */ }
        }
        const canonicalKey = sanitizePureSoundKey(r.sound_key);
        return {
          key: r.sound_key,
          canonical_key: canonicalKey !== r.sound_key ? canonicalKey : undefined,
          key_leak: pureSoundKeyHasLeak(r.sound_key),
          name: stripSoundPrefix(r.name),
          count: r.count,
          strength_pct: r.strength_pct ?? undefined,
          depth_breakdown,
        };
      });
      return fromDb.filter((s) => !((SOUND_PRIMITIVES as string[]).includes(s.key) && (s.count ?? 0) === 0));
    })();
    return json({
      limit: regLimit,
      offset: regOffset,
      section: "static",
      truncated: colors.length >= regLimit || sound.length >= regLimit,
      totals: { static_colors: colors.length, static_sound: sound.length },
      static: { colors, sound },
    });
  }

  if (section === "narrative") {
    const narrativeAspectsEarly = ["genre", "mood", "themes", "plots", "settings", "style", "scene_type"];
    const narrativeEarly: Record<string, Array<{ entry_key: string; value: string; name: string; count: number }>> = {};
    const narrativeTotals: Record<string, number> = {};
    for (const aspect of narrativeAspectsEarly) {
      const rows = await db.prepare(
        "SELECT entry_key, value, name, count FROM narrative_entries WHERE aspect = ? ORDER BY count DESC LIMIT ?"
      ).bind(aspect, regLimit).all<{ entry_key: string; value: string | null; name: string; count: number }>();
      narrativeEarly[aspect] = (rows.results || []).map((r) => {
        const value = r.value || r.entry_key;
        return { entry_key: r.entry_key, value, name: narrativeDisplayName(r.entry_key, value, r.name), count: r.count };
      });
      narrativeTotals[aspect] = narrativeEarly[aspect].length;
    }
    return json({
      limit: regLimit,
      offset: regOffset,
      section: "narrative",
      truncated: Object.values(narrativeEarly).some((rows) => rows.length >= regLimit),
      totals: { narrative: narrativeTotals },
      narrative: narrativeEarly,
    });
  }

  if (section === "interpretation" || section === "linguistic") {
    const interpretationRowsEarly = section === "interpretation"
      ? await db.prepare(
          "SELECT id, prompt, instruction_json, updated_at FROM interpretations WHERE status = 'done' AND instruction_json IS NOT NULL ORDER BY updated_at DESC LIMIT ?"
        ).bind(Math.min(regLimit, 100)).all<{ id: string; prompt: string; instruction_json: string; updated_at: string }>()
      : { results: [] as { id: string; prompt: string; instruction_json: string; updated_at: string }[] };
    const interpretationEarly = (interpretationRowsEarly.results || []).map((r) => ({
      id: r.id,
      prompt: r.prompt,
      instruction: r.instruction_json ? (JSON.parse(r.instruction_json) as Record<string, unknown>) : null,
      updated_at: r.updated_at,
    }));
    let linguisticEarly: Array<{ span: string; canonical: string; domain: string; variant_type: string; count: number }> = [];
    try {
      const lingRows = await db.prepare(
        "SELECT span, canonical, domain, variant_type, count FROM linguistic_registry ORDER BY count DESC LIMIT ?"
      ).bind(Math.min(regLimit, 200)).all<{ span: string; canonical: string; domain: string; variant_type: string; count: number }>();
      linguisticEarly = lingRows.results || [];
    } catch { /* optional table */ }
    return json({
      limit: regLimit,
      offset: regOffset,
      section,
      truncated: interpretationEarly.length >= Math.min(regLimit, 100) || linguisticEarly.length >= Math.min(regLimit, 200),
      totals: { interpretation: interpretationEarly.length, linguistic: linguisticEarly.length },
      interpretation: interpretationEarly,
      linguistic: linguisticEarly,
    });
  }

  const staticColors = await db.prepare(
    "SELECT color_key, r, g, b, name, count, depth_breakdown_json FROM static_colors ORDER BY count DESC LIMIT ?"
  ).bind(regLimit).all<{ color_key: string; r: number; g: number; b: number; name: string; count: number; depth_breakdown_json: string | null }>();
  const staticSound = await db.prepare(
    "SELECT sound_key, name, count, depth_breakdown_json, strength_pct FROM static_sound ORDER BY count DESC LIMIT ?"
  ).bind(regLimit).all<{ sound_key: string; name: string; count: number; depth_breakdown_json: string | null; strength_pct: number | null }>();
  const learnedColors = learnedColorsDepthOk
    ? await db
        .prepare(
          "SELECT color_key, r, g, b, name, count, depth_breakdown_json FROM learned_colors ORDER BY count DESC LIMIT ?",
        )
        .bind(regLimit)
        .all<{
          color_key: string;
          r: number;
          g: number;
          b: number;
          name: string;
          count: number;
          depth_breakdown_json: string | null;
        }>()
    : await db
        .prepare(
          "SELECT color_key, r, g, b, name, count FROM learned_colors ORDER BY count DESC LIMIT ?",
        )
        .bind(regLimit)
        .all<{ color_key: string; r: number; g: number; b: number; name: string; count: number }>()
        .then((r) => ({
          results: (r.results || []).map((row) => ({ ...row, depth_breakdown_json: null as string | null })),
        }));
  const learnedMotion = await db.prepare(
    "SELECT profile_key, motion_level, motion_trend, name, count, depth_breakdown_json FROM learned_motion ORDER BY count DESC LIMIT ?"
  ).bind(regLimit).all<{ profile_key: string; motion_level: number; motion_trend: string; name: string | null; count: number; depth_breakdown_json: string | null }>();
  const blends = await db.prepare(
    "SELECT name, domain, output_json, primitive_depths_json FROM learned_blends ORDER BY created_at DESC LIMIT ?"
  ).bind(regLimit).all<{ name: string; domain: string; output_json: string; primitive_depths_json: string | null }>();
  // Merge discovery tables into dynamic (living plan §1.2 / Priority 1): per-window discoveries appear in export
  const learnedGradientRows = await db.prepare(
    "SELECT profile_key, gradient_type, name, count, depth_breakdown_json FROM learned_gradient ORDER BY count DESC LIMIT ?"
  ).bind(regLimit).all<{ profile_key: string; gradient_type: string; name: string; count: number; depth_breakdown_json: string | null }>();
  const learnedCameraRows = await db.prepare(
    "SELECT profile_key, motion_type, name, count, depth_breakdown_json FROM learned_camera ORDER BY count DESC LIMIT ?"
  ).bind(regLimit).all<{ profile_key: string; motion_type: string; name: string; count: number; depth_breakdown_json: string | null }>();
  let learnedEntityRows: Array<{
    profile_key: string;
    kind: string;
    trajectory: string | null;
    bounce: number;
    color_hint: string | null;
    label: string | null;
    name: string | null;
    count: number;
  }> = [];
  try {
    const er = await db.prepare(
      "SELECT profile_key, kind, trajectory, bounce, color_hint, label, name, count FROM learned_entities ORDER BY count DESC LIMIT ?"
    ).bind(regLimit).all<{
      profile_key: string;
      kind: string;
      trajectory: string | null;
      bounce: number;
      color_hint: string | null;
      label: string | null;
      name: string | null;
      count: number;
    }>();
    learnedEntityRows = er.results || [];
  } catch {
    // learned_entities may not exist until migration 0021
  }
  let learnedAudioSemanticRows: Array<{ profile_key: string; role: string; name: string; count: number }> = [];
  try {
    const r = await db.prepare(
      "SELECT profile_key, role, name, count FROM learned_audio_semantic ORDER BY count DESC LIMIT ?"
    ).bind(regLimit).all<{ profile_key: string; role: string; name: string; count: number }>();
    learnedAudioSemanticRows = r.results || [];
  } catch {
    // table may not exist
  }
  const narrativeAspects = ["genre", "mood", "themes", "plots", "settings", "style", "scene_type"];
  const narrative: Record<string, Array<{ entry_key: string; value: string; name: string; count: number }>> = {};
  for (const aspect of narrativeAspects) {
    const rows = await db.prepare(
      "SELECT entry_key, value, name, count FROM narrative_entries WHERE aspect = ? ORDER BY count DESC LIMIT ?"
    ).bind(aspect, regLimit).all<{ entry_key: string; value: string | null; name: string; count: number }>();
    narrative[aspect] = (rows.results || []).map((r) => {
      const value = r.value || r.entry_key;
      const displayName = narrativeDisplayName(r.entry_key, value, r.name);
      return {
        entry_key: r.entry_key,
        value,
        name: displayName,
        count: r.count,
      };
    });
  }
  const interpretationRows = await db.prepare(
    "SELECT id, prompt, instruction_json, updated_at FROM interpretations WHERE status = 'done' AND instruction_json IS NOT NULL ORDER BY updated_at DESC LIMIT ?"
  ).bind(Math.min(regLimit, 100)).all<{ id: string; prompt: string; instruction_json: string; updated_at: string }>();
  const interpretation = (interpretationRows.results || []).map((r) => ({
    id: r.id,
    prompt: r.prompt,
    instruction: r.instruction_json ? (JSON.parse(r.instruction_json) as Record<string, unknown>) : null,
    updated_at: r.updated_at,
  }));
  let linguistic: Array<{ span: string; canonical: string; domain: string; variant_type: string; count: number }> = [];
  try {
    const lingRows = await db.prepare(
      "SELECT span, canonical, domain, variant_type, count FROM linguistic_registry ORDER BY count DESC LIMIT ?"
    ).bind(Math.min(regLimit, 200)).all<{ span: string; canonical: string; domain: string; variant_type: string; count: number }>();
    linguistic = lingRows.results || [];
  } catch {
    // linguistic_registry may not exist in older deployments
  }
  const depthFromBlendDepths = (depths: Record<string, unknown> | null): { depth_pct: number; depth_breakdown: Record<string, number> } => {
    const depth_breakdown: Record<string, number> = {};
    if (!depths || typeof depths !== "object") return { depth_pct: 0, depth_breakdown };
    const flatten = (obj: Record<string, unknown>, prefix = ""): void => {
      for (const [k, v] of Object.entries(obj)) {
        if (typeof v === "number") {
          const key = prefix ? `${prefix}.${k}` : k;
          depth_breakdown[key] = v <= 1 ? Math.round(v * 100) : Math.round(v);
        } else if (v && typeof v === "object" && !Array.isArray(v)) {
          flatten(v as Record<string, unknown>, prefix ? `${prefix}.${k}` : k);
        }
      }
    };
    flatten(depths);
    const vals = Object.values(depth_breakdown);
    const depth_pct = vals.length ? Math.max(...vals) : 0;
    return { depth_pct, depth_breakdown };
  };
  const gradientFromBlends = (blends.results || []).filter((b) => b.domain === "gradient").map((b) => {
    const out = JSON.parse(b.output_json) as Record<string, unknown>;
    const depths = b.primitive_depths_json ? (JSON.parse(b.primitive_depths_json) as Record<string, unknown>) : null;
    const { depth_pct, depth_breakdown } = depthFromBlendDepths(depths);
    return { name: b.name, key: String(out.gradient_type ?? b.domain), depth_pct, depth_breakdown };
  });
  const gradientFromTable = (learnedGradientRows.results || []).map((r) => {
    const depths = r.depth_breakdown_json ? (JSON.parse(r.depth_breakdown_json) as Record<string, unknown>) : null;
    const { depth_pct, depth_breakdown } = depthFromBlendDepths(depths);
    return { name: r.name || r.gradient_type, key: r.gradient_type, depth_pct, depth_breakdown };
  });
  const gradientKeys = new Set(gradientFromBlends.map((g) => g.key));
  const gradientBlends = [...gradientFromBlends];
  for (const g of gradientFromTable) {
    if (!gradientKeys.has(g.key)) {
      gradientKeys.add(g.key);
      gradientBlends.push(g);
    }
  }
  for (const canonical of dynamicCanonical.gradient_type) {
    if (!gradientKeys.has(canonical)) {
      gradientKeys.add(canonical);
      gradientBlends.push({ name: canonical, key: canonical, depth_pct: 0, depth_breakdown: {} as Record<string, number> });
    }
  }
  const cameraFromBlends = (blends.results || []).filter((b) => b.domain === "camera").map((b) => {
    const out = JSON.parse(b.output_json) as Record<string, unknown>;
    const depths = b.primitive_depths_json ? (JSON.parse(b.primitive_depths_json) as Record<string, unknown>) : null;
    const { depth_pct, depth_breakdown } = depthFromBlendDepths(depths);
    return { name: b.name, key: String(out.camera_motion ?? b.domain), depth_pct, depth_breakdown };
  });
  const cameraFromTable = (learnedCameraRows.results || []).map((r) => {
    const depths = r.depth_breakdown_json ? (JSON.parse(r.depth_breakdown_json) as Record<string, unknown>) : null;
    const { depth_pct, depth_breakdown } = depthFromBlendDepths(depths);
    return { name: r.name || r.motion_type, key: r.motion_type, depth_pct, depth_breakdown };
  });
  const cameraKeys = new Set(cameraFromBlends.map((c) => c.key));
  const cameraBlends = [...cameraFromBlends];
  for (const c of cameraFromTable) {
    if (!cameraKeys.has(c.key)) {
      cameraKeys.add(c.key);
      cameraBlends.push(c);
    }
  }
  for (const canonical of dynamicCanonical.camera_motion) {
    if (!cameraKeys.has(canonical)) {
      cameraKeys.add(canonical);
      cameraBlends.push({ name: canonical, key: canonical, depth_pct: 0, depth_breakdown: {} as Record<string, number> });
    }
  }
  const audioFromBlends = (blends.results || []).filter((b) => b.domain === "audio").map((b) => {
    const out = JSON.parse(b.output_json) as Record<string, unknown>;
    const depths = b.primitive_depths_json ? (JSON.parse(b.primitive_depths_json) as Record<string, unknown>) : null;
    const { depth_pct, depth_breakdown } = depthFromBlendDepths(depths);
    const key = [out.tempo, out.mood, out.presence].filter(Boolean).join(" / ") || b.output_json.slice(0, 60);
    return { name: b.name, key, tempo: out.tempo, mood: out.mood, presence: out.presence, depth_pct, depth_breakdown };
  });
  const audioFromSemantic = learnedAudioSemanticRows.map((r) => ({
    name: r.name || r.role,
    key: r.profile_key || r.role,
    depth_pct: 0,
    depth_breakdown: {} as Record<string, number>,
  }));
  const audioBlends = [...audioFromBlends, ...audioFromSemantic];
  const DEDICATED_BLEND_DOMAINS = ["color", "motion", "lighting", "composition", "graphics", "temporal", "technical"];
  const toBlendRow = (b: { name: string; domain: string; output_json: string; primitive_depths_json: string | null }) => {
    const depths = b.primitive_depths_json ? (JSON.parse(b.primitive_depths_json) as Record<string, unknown>) : null;
    const { depth_pct, depth_breakdown } = depthFromBlendDepths(depths);
    const rawKey = b.output_json.slice(0, 80);
    return { name: b.name, domain: b.domain, key: formatReadableBlendKey(rawKey), depth_pct, depth_breakdown };
  };
  type LearnedRow = { name: string; key: string; depth_pct: number; depth_breakdown: Record<string, number> };
  const mergeTableIntoBlends = (fromBlends: LearnedRow[], fromTable: LearnedRow[]): LearnedRow[] => {
    const keysPresent = new Set(fromBlends.map((b) => b.key));
    const out = [...fromBlends];
    for (const r of fromTable) {
      if (!keysPresent.has(r.key)) {
        keysPresent.add(r.key);
        out.push(r);
      }
    }
    return out;
  };
  let learnedLightingRows: LearnedRow[] = [];
  let learnedCompositionRows: LearnedRow[] = [];
  let learnedGraphicsRows: LearnedRow[] = [];
  let learnedTemporalRows: LearnedRow[] = [];
  let learnedTechnicalRows: LearnedRow[] = [];
  try {
    const l = await db.prepare(
      "SELECT profile_key, name, depth_breakdown_json FROM learned_lighting ORDER BY count DESC LIMIT ?"
    ).bind(regLimit).all<{ profile_key: string; name: string; depth_breakdown_json: string | null }>();
    learnedLightingRows = (l.results || []).map((r) => {
      const depths = r.depth_breakdown_json ? (JSON.parse(r.depth_breakdown_json) as Record<string, unknown>) : null;
      const { depth_pct, depth_breakdown } = depthFromBlendDepths(depths);
      return { name: r.name || r.profile_key, key: r.profile_key, depth_pct, depth_breakdown };
    });
  } catch {
    // table may not exist
  }
  try {
    const c = await db.prepare(
      "SELECT profile_key, name FROM learned_composition ORDER BY count DESC LIMIT ?"
    ).bind(regLimit).all<{ profile_key: string; name: string }>();
    learnedCompositionRows = (c.results || []).map((r) => ({
      name: r.name || r.profile_key,
      key: r.profile_key,
      depth_pct: 0,
      depth_breakdown: {} as Record<string, number>,
    }));
  } catch {
    // table may not exist
  }
  try {
    const g = await db.prepare(
      "SELECT profile_key, name FROM learned_graphics ORDER BY count DESC LIMIT ?"
    ).bind(regLimit).all<{ profile_key: string; name: string }>();
    learnedGraphicsRows = (g.results || []).map((r) => ({
      name: r.name || r.profile_key,
      key: r.profile_key,
      depth_pct: 0,
      depth_breakdown: {} as Record<string, number>,
    }));
  } catch {
    // table may not exist
  }
  try {
    const t = await db.prepare(
      "SELECT profile_key, name FROM learned_temporal ORDER BY count DESC LIMIT ?"
    ).bind(regLimit).all<{ profile_key: string; name: string }>();
    const temporalMetaByKey = new Map<string, string>();
    try {
      const meta = await db.prepare(
        "SELECT profile_key, depth_breakdown_json FROM learned_dynamic_meta WHERE aspect = ?"
      )
        .bind("temporal")
        .all<{ profile_key: string; depth_breakdown_json: string | null }>();
      for (const row of meta.results || []) {
        if (row.depth_breakdown_json) temporalMetaByKey.set(row.profile_key, row.depth_breakdown_json);
      }
    } catch {
      /* learned_dynamic_meta missing until migration 0018 */
    }
    learnedTemporalRows = (t.results || []).map((r) => {
      const raw = temporalMetaByKey.get(r.profile_key);
      const depths = raw ? (JSON.parse(raw) as Record<string, unknown>) : null;
      const { depth_pct, depth_breakdown } = depthFromBlendDepths(depths);
      return { name: r.name || r.profile_key, key: r.profile_key, depth_pct, depth_breakdown };
    });
  } catch {
    // learned_temporal may not exist
  }
  try {
    const tech = await db.prepare(
      "SELECT profile_key, name FROM learned_technical ORDER BY count DESC LIMIT ?"
    ).bind(regLimit).all<{ profile_key: string; name: string }>();
    const technicalMetaByKey = new Map<string, string>();
    try {
      const meta = await db.prepare(
        "SELECT profile_key, depth_breakdown_json FROM learned_dynamic_meta WHERE aspect = ?"
      )
        .bind("technical")
        .all<{ profile_key: string; depth_breakdown_json: string | null }>();
      for (const row of meta.results || []) {
        if (row.depth_breakdown_json) technicalMetaByKey.set(row.profile_key, row.depth_breakdown_json);
      }
    } catch {
      /* learned_dynamic_meta missing until migration 0018 */
    }
    learnedTechnicalRows = (tech.results || []).map((r) => {
      const raw = technicalMetaByKey.get(r.profile_key);
      const depths = raw ? (JSON.parse(raw) as Record<string, unknown>) : null;
      const { depth_pct, depth_breakdown } = depthFromBlendDepths(depths);
      return { name: r.name || r.profile_key, key: r.profile_key, depth_pct, depth_breakdown };
    });
  } catch {
    // learned_technical may not exist
  }
  const nonGca = (blends.results || []).filter((b) => b.domain !== "gradient" && b.domain !== "camera" && b.domain !== "audio");
  const blendsByDomain: Record<string, typeof nonGca> = {};
  for (const d of DEDICATED_BLEND_DOMAINS) blendsByDomain[d] = nonGca.filter((b) => b.domain === d);
  const otherBlends = nonGca
    .filter((b) => !DEDICATED_BLEND_DOMAINS.includes(b.domain))
    .map(toBlendRow);
  const lightingBlends = mergeTableIntoBlends(blendsByDomain.lighting.map(toBlendRow), learnedLightingRows);
  const compositionBlends = mergeTableIntoBlends(blendsByDomain.composition.map(toBlendRow), learnedCompositionRows);
  const graphicsBlends = mergeTableIntoBlends(blendsByDomain.graphics.map(toBlendRow), learnedGraphicsRows);
  const temporalBlends = mergeTableIntoBlends(blendsByDomain.temporal.map(toBlendRow), learnedTemporalRows);
  const technicalBlends = mergeTableIntoBlends(blendsByDomain.technical.map(toBlendRow), learnedTechnicalRows);
  const colorBlendsFromBlends = blendsByDomain.color.map(toBlendRow);
  const motionBlendsFromBlends = blendsByDomain.motion.map(toBlendRow);
  const motionFromLearned = (learnedMotion.results || []).map((r) => {
    let depth_breakdown: Record<string, number> = {};
    if (r.depth_breakdown_json) {
      try {
        const parsed = JSON.parse(r.depth_breakdown_json) as Record<string, unknown>;
        const { depth_breakdown: flat } = depthFromBlendDepths(parsed);
        depth_breakdown = flat;
      } catch { /* ignore */ }
    }
    if (!Object.keys(depth_breakdown).length) {
      const computed = computeMotionDepth((r.motion_level ?? parseFloat(String(r.profile_key).split("_")[0])) || 0);
      for (const [k, v] of Object.entries(computed)) depth_breakdown[k] = Math.round(v * 100);
    }
    const vals = Object.values(depth_breakdown);
    const depth_pct = vals.length ? Math.max(...vals) : 0;
    return { key: r.profile_key, name: r.name || r.profile_key, trend: r.motion_trend, count: r.count, depth_pct, depth_breakdown };
  });
  const motionFromBlends = motionBlendsFromBlends.map((b) => ({
    key: b.key,
    name: b.name,
    trend: "—" as const,
    count: 0,
    depth_pct: b.depth_pct,
    depth_breakdown: b.depth_breakdown,
  }));
  const motionKeysPresent = new Set([...motionFromLearned.map((m) => m.key), ...motionFromBlends.map((b) => b.key)]);
  const motionWithCanonicalRaw = [...motionFromLearned, ...motionFromBlends];
  for (const canonical of dynamicCanonical.motion) {
    if (!motionKeysPresent.has(canonical)) {
      motionKeysPresent.add(canonical);
      motionWithCanonicalRaw.push({ key: canonical, name: canonical, trend: "—", count: 0, depth_pct: 0, depth_breakdown: {} as Record<string, number> });
    }
  }
  // One row per motion key: keep highest count (learned beats placeholder; dedupes blend duplicates).
  const motionByKey = new Map<string, (typeof motionWithCanonicalRaw)[0]>();
  for (const m of motionWithCanonicalRaw) {
    const prev = motionByKey.get(m.key);
    const c = typeof m.count === "number" ? m.count : 0;
    const pc = prev && typeof prev.count === "number" ? prev.count : 0;
    if (!prev || c > pc) motionByKey.set(m.key, m);
  }
  const motionWithCanonical = [...motionByKey.values()];
  const staticPayload = {
    colors: ensureUniqueColorNames((staticColors.results || []).map((r) => {
        let depth_pct: number;
        let depth_breakdown: Record<string, number>;
        let opacity_pct: number | undefined;
        let theme_breakdown: Record<string, number> | undefined;
        if (r.depth_breakdown_json) {
          try {
            const stored = JSON.parse(r.depth_breakdown_json) as Record<string, unknown>;
            const raw: Record<string, number> = {};
            const oc = stored.origin_colors as Record<string, number> | undefined;
            if (oc && typeof oc === "object") {
              for (const [k, v] of Object.entries(oc)) {
                if (k === "opacity") {
                  raw[k] = normalizeOpacityToPercent(v);
                } else {
                  raw[k] = typeof v === "number" ? (v <= 1 ? Math.round(v * 100) : Math.round(v)) : 0;
                }
              }
            }
            for (const [k, v] of Object.entries(stored)) {
              if (k === "origin_colors") continue;
              if (typeof v === "number") {
                raw[k] = k === "opacity" ? normalizeOpacityToPercent(v) : (v <= 1 ? Math.round(v * 100) : Math.round(v));
              }
            }
            const split = splitDepthBreakdown(raw);
            depth_breakdown = split.depth_breakdown;
            opacity_pct = split.opacity_pct;
            theme_breakdown = split.theme_breakdown;
            depth_pct = Object.keys(depth_breakdown).length || Object.keys(theme_breakdown || {}).length ? 100 : 0;
          } catch {
            const comp = colorDepthVsPrimitives(r.r, r.g, r.b);
            depth_pct = comp.depth_pct;
            depth_breakdown = comp.depth_breakdown;
          }
        } else {
          const comp = colorDepthVsPrimitives(r.r, r.g, r.b);
          depth_pct = comp.depth_pct;
          depth_breakdown = comp.depth_breakdown;
        }
        const key = normalizeColorKey(r.color_key);
        const out: Record<string, unknown> = { key, r: r.r, g: r.g, b: r.b, name: r.name, count: r.count, depth_pct, depth_breakdown };
        if (opacity_pct != null) out.opacity_pct = opacity_pct;
        if (theme_breakdown && Object.keys(theme_breakdown).length > 0) out.theme_breakdown = theme_breakdown;
        return out as { key: string; r: number; g: number; b: number; name: string; count: number; depth_pct: number; depth_breakdown: Record<string, number>; opacity_pct?: number; theme_breakdown?: Record<string, number> };
      })),
      sound: (() => {
        const SOUND_PRIMITIVES = [...SOUND_PRIMARIES_FOR_COVERAGE];
        const stripSoundPrefix = (name: string | null): string => {
          if (!name || typeof name !== "string") return name ?? "";
          const n = name.trim();
          return n.toLowerCase().startsWith("sound_") ? n.slice(6).trim() || n : n;
        };
        const fromDb = (staticSound.results || []).map((r) => {
          const depth_breakdown = r.depth_breakdown_json ? (JSON.parse(r.depth_breakdown_json) as Record<string, unknown>) : undefined;
          const canonicalKey = sanitizePureSoundKey(r.sound_key);
          return {
            key: r.sound_key,
            canonical_key: canonicalKey !== r.sound_key ? canonicalKey : undefined,
            key_leak: pureSoundKeyHasLeak(r.sound_key),
            name: stripSoundPrefix(r.name),
            count: r.count,
            strength_pct: r.strength_pct ?? undefined,
            depth_breakdown,
          };
        });
        // Omit zero-count primitive rows — they duplicate static_primitives.sound_primaries in export/UI.
        return fromDb.filter((s) => !((SOUND_PRIMITIVES as string[]).includes(s.key) && (s.count ?? 0) === 0));
      })(),
  };
  const learnedColorRows = ensureUniqueColorNames((learnedColors.results || []).map((r) => {
        let depth_pct: number;
        let depth_breakdown: Record<string, number>;
        let opacity_pct: number | undefined;
        let theme_breakdown: Record<string, number> | undefined;
        if (r.depth_breakdown_json) {
          try {
            const stored = JSON.parse(r.depth_breakdown_json) as Record<string, number>;
            const raw: Record<string, number> = {};
            for (const [k, v] of Object.entries(stored)) {
              if (typeof v !== "number") continue;
              raw[k] = k === "opacity" ? normalizeOpacityToPercent(v) : (v <= 1 ? Math.round(v * 100) : Math.round(v));
            }
            const split = splitDepthBreakdown(raw);
            depth_breakdown = split.depth_breakdown;
            opacity_pct = split.opacity_pct;
            theme_breakdown = split.theme_breakdown;
            const vals = Object.values(depth_breakdown);
            depth_pct = vals.length ? Math.max(...vals) : (theme_breakdown && Object.keys(theme_breakdown).length ? 100 : 0);
          } catch {
            const comp = colorDepthVsPrimitives(r.r, r.g, r.b);
            depth_pct = comp.depth_pct;
            depth_breakdown = comp.depth_breakdown;
          }
        } else {
          const comp = colorDepthVsPrimitives(r.r, r.g, r.b);
          depth_pct = comp.depth_pct;
          depth_breakdown = comp.depth_breakdown;
        }
        const key = normalizeColorKey(r.color_key);
        const out: Record<string, unknown> = { key, r: r.r, g: r.g, b: r.b, name: r.name, count: r.count, depth_pct, depth_breakdown };
        if (opacity_pct != null) out.opacity_pct = opacity_pct;
        if (theme_breakdown && Object.keys(theme_breakdown).length > 0) out.theme_breakdown = theme_breakdown;
        return out as { key: string; r: number; g: number; b: number; name: string; count: number; depth_pct: number; depth_breakdown: Record<string, number>; opacity_pct?: number; theme_breakdown?: Record<string, number> };
      }));
  const colorKeysPresent = new Set(learnedColorRows.map((c) => c.key));
  const mergedLearnedColors = [...learnedColorRows];
  for (const b of colorBlendsFromBlends) {
    const rgbMatch = /^rgb\((\d+),\s*(\d+),\s*(\d+)\)$/.exec(b.key);
    if (!rgbMatch) continue;
    const key = `${rgbMatch[1]},${rgbMatch[2]},${rgbMatch[3]}`;
    if (colorKeysPresent.has(key)) continue;
    colorKeysPresent.add(key);
    mergedLearnedColors.push({
      key,
      r: parseInt(rgbMatch[1], 10),
      g: parseInt(rgbMatch[2], 10),
      b: parseInt(rgbMatch[3], 10),
      name: b.name,
      count: 0,
      depth_pct: b.depth_pct,
      depth_breakdown: b.depth_breakdown,
    });
  }
  const dynamicPayload = {
      colors: mergedLearnedColors,
      motion: motionWithCanonical,
      gradient: gradientBlends,
      camera: cameraBlends,
      sound: audioBlends,
      colors_from_blends: [],
      colors_merged_from_blends: colorBlendsFromBlends.length,
      lighting: lightingBlends,
      composition: compositionBlends,
      graphics: graphicsBlends,
      temporal: temporalBlends,
      technical: technicalBlends,
      blends: otherBlends,
      entities: learnedEntityRows.map((r) => ({
        key: r.profile_key,
        kind: r.kind,
        trajectory: r.trajectory || "none",
        bounce: !!r.bounce,
        color_hint: r.color_hint || null,
        label: r.label || null,
        name: r.name || r.label || r.kind,
        count: r.count,
      })),
  };
  const staticColorsPage = pageSlice(staticPayload.colors || []);
  const staticSoundPage = pageSlice(staticPayload.sound || []);
  const interpretationPage = pageSlice(interpretation || []);
  const linguisticPage = pageSlice(linguistic || []);
  const dynamicTotals: Record<string, number> = {};
  const dynamicPaged: Record<string, unknown> = { ...dynamicPayload };
  for (const key of Object.keys(dynamicPayload) as (keyof typeof dynamicPayload)[]) {
    const val = dynamicPayload[key];
    if (Array.isArray(val)) {
      const paged = pageSlice(val);
      dynamicTotals[key as string] = paged.total;
      dynamicPaged[key] = paged.items;
    }
  }
  const narrativePaged: Record<string, unknown> = {};
  const narrativeTotals: Record<string, number> = {};
  for (const [aspect, rows] of Object.entries(narrative || {})) {
    const list = Array.isArray(rows) ? rows : [];
    const paged = pageSlice(list);
    narrativeTotals[aspect] = paged.total;
    narrativePaged[aspect] = paged.items;
  }
  const includeStatic = section === "all" || section === "static";
  const includeDynamic = section === "all" || section === "dynamic";
  const includeNarrative = section === "all" || section === "narrative";
  const includeInterpretation = section === "all" || section === "interpretation";
  const includeLinguistic = section === "all" || section === "linguistic";
  const includeMeta = section === "all" || section === "meta";
  return json({
    limit: regLimit,
    offset: regOffset,
    section,
    truncated:
      staticColorsPage.truncated ||
      staticSoundPage.truncated ||
      interpretationPage.truncated ||
      linguisticPage.truncated ||
      Object.values(dynamicTotals).some((t) => t > regOffset + regLimit) ||
      Object.values(narrativeTotals).some((t) => t > regOffset + regLimit),
    totals: {
      static_colors: staticColorsPage.total,
      static_sound: staticSoundPage.total,
      interpretation: interpretationPage.total,
      linguistic: linguisticPage.total,
      dynamic: dynamicTotals,
      narrative: narrativeTotals,
    },
    ...(includeMeta
      ? { static_primitives: staticPrimitives, dynamic_canonical: dynamicCanonical }
      : {}),
    ...(includeStatic
      ? { static: { colors: staticColorsPage.items, sound: staticSoundPage.items } }
      : {}),
    ...(includeDynamic ? { dynamic: dynamicPaged } : {}),
    ...(includeNarrative ? { narrative: narrativePaged } : {}),
    ...(includeInterpretation ? { interpretation: interpretationPage.items } : {}),
    ...(includeLinguistic ? { linguistic: linguisticPage.items } : {}),
  });
}

  return null;
}
