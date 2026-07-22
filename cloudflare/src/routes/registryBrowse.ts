/**
 * GET /api/registries/browse — public facet + paginated explorer for all registries.
 */
import type { Env } from "../env";
import { getDb, getPrimaryDb, ensureStaticColorsFamilyColumns } from "../db";
import { json, err } from "../http";
import {
  COLOR_FAMILY_META,
  COLOR_SHADE_META,
  FAMILY_SAMPLE_RGB,
  classifyStaticColorRow,
  colorMatchesPrimitives,
  type ClassifiedColor,
  type ColorFamilyId,
  type ColorShadeId,
} from "../colorBrowse";
import {
  BROWSE_COLORS_CACHE_KEY,
  BROWSE_COLOR_FACETS_KEY,
  BROWSE_SOUND_CACHE_KEY,
} from "../browseCache";
import { SOUND_ORIGIN_PRIMARIES } from "../naming";

// Free-tier D1: keep ORDER BY count scans small; serve from KV when warm.
const SCAN_CAP = 800;
const CACHE_TTL_SEC = 300;

type Facet = { id: string; label: string; count: number; sample_rgb?: [number, number, number] };

function parseLimitOffset(url: URL): { limit: number; offset: number } {
  const limit = Math.min(Math.max(parseInt(url.searchParams.get("limit") || "48", 10) || 48, 1), 100);
  const offset = Math.max(parseInt(url.searchParams.get("offset") || "0", 10) || 0, 0);
  return { limit, offset };
}

function parsePrimitives(url: URL): string[] {
  const multi = url.searchParams.getAll("primitive").map((p) => p.trim().toLowerCase()).filter(Boolean);
  if (multi.length) return [...new Set(multi)];
  const csv = (url.searchParams.get("primitives") || "").trim();
  if (!csv) return [];
  return [...new Set(csv.split(",").map((p) => p.trim().toLowerCase()).filter(Boolean))];
}

function pageItems<T>(items: T[], offset: number, limit: number) {
  const total = items.length;
  const slice = items.slice(offset, offset + limit);
  return { items: slice, total, truncated: offset + slice.length < total };
}

async function loadClassifiedColors(env: Env): Promise<ClassifiedColor[]> {
  const kv = env.MOTION_KV;
  if (kv) {
    try {
      const cached = await kv.get(BROWSE_COLORS_CACHE_KEY, "json");
      if (Array.isArray(cached) && cached.length) return cached as ClassifiedColor[];
    } catch {
      /* ignore */
    }
  }
  const db = getPrimaryDb(env);
  const familyOk = await ensureStaticColorsFamilyColumns(db);
  type Row = {
    color_key: string;
    r: number;
    g: number;
    b: number;
    name: string | null;
    count: number;
    depth_breakdown_json: string | null;
    family?: string | null;
    shade?: string | null;
  };
  let rows: { results?: Row[] };
  if (familyOk) {
    rows = await db
      .prepare(
        "SELECT color_key, r, g, b, name, count, depth_breakdown_json, family, shade FROM static_colors ORDER BY count DESC LIMIT ?",
      )
      .bind(SCAN_CAP)
      .all<Row>();
  } else {
    rows = await db
      .prepare(
        "SELECT color_key, r, g, b, name, count, depth_breakdown_json FROM static_colors ORDER BY count DESC LIMIT ?",
      )
      .bind(SCAN_CAP)
      .all<Row>();
  }
  const classified: ClassifiedColor[] = [];
  const backfill: Array<{ key: string; family: string; shade: string }> = [];
  for (const r of rows.results || []) {
    const base = classifyStaticColorRow(r);
    if (r.family && r.shade) {
      base.family = r.family as ColorFamilyId;
      base.shade = r.shade as ColorShadeId;
    } else if (familyOk) {
      backfill.push({ key: r.color_key, family: base.family, shade: base.shade });
    }
    classified.push(base);
  }
  // Opportunistic backfill (bounded) so SQL filters work for older rows
  for (const b of backfill.slice(0, 80)) {
    try {
      await db
        .prepare("UPDATE static_colors SET family = ?, shade = ? WHERE color_key = ? AND (family IS NULL OR shade IS NULL)")
        .bind(b.family, b.shade, b.key)
        .run();
    } catch {
      break;
    }
  }
  if (kv) {
    try {
      await kv.put(BROWSE_COLORS_CACHE_KEY, JSON.stringify(classified), { expirationTtl: CACHE_TTL_SEC });
      const facets = buildColorFacets(classified, null);
      await kv.put(
        BROWSE_COLOR_FACETS_KEY,
        JSON.stringify({
          updated_at: new Date().toISOString(),
          scanned: classified.length,
          families: facets.families,
          shades: facets.shades,
          primitives: facets.primitives.slice(0, 40),
        }),
        { expirationTtl: CACHE_TTL_SEC },
      );
    } catch {
      /* ignore */
    }
  }
  return classified;
}

function buildColorFacets(
  pool: ClassifiedColor[],
  family: string | null,
): { families: Facet[]; shades: Facet[]; primitives: Facet[] } {
  const familyCounts = new Map<string, { count: number; sample?: [number, number, number] }>();
  for (const meta of COLOR_FAMILY_META) {
    familyCounts.set(meta.id, { count: 0, sample: FAMILY_SAMPLE_RGB[meta.id] });
  }
  for (const c of pool) {
    const entry = familyCounts.get(c.family) || { count: 0 };
    entry.count += 1;
    if (!entry.sample) entry.sample = [c.r, c.g, c.b];
    familyCounts.set(c.family, entry);
  }
  const families: Facet[] = COLOR_FAMILY_META.map((m) => {
    const e = familyCounts.get(m.id)!;
    return { id: m.id, label: m.label, count: e.count, sample_rgb: e.sample };
  }).filter((f) => f.count > 0);

  const shadePool = family ? pool.filter((c) => c.family === family) : pool;
  const shadeCounts = new Map<string, number>();
  for (const m of COLOR_SHADE_META) shadeCounts.set(m.id, 0);
  for (const c of shadePool) {
    shadeCounts.set(c.shade, (shadeCounts.get(c.shade) || 0) + 1);
  }
  const shades: Facet[] = COLOR_SHADE_META.map((m) => ({
    id: m.id,
    label: m.label,
    count: shadeCounts.get(m.id) || 0,
  })).filter((s) => s.count > 0);

  const primCounts = new Map<string, number>();
  for (const c of shadePool) {
    for (const p of c.primitives) {
      primCounts.set(p, (primCounts.get(p) || 0) + 1);
    }
  }
  const primitives: Facet[] = [...primCounts.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([id, count]) => ({ id, label: id.charAt(0).toUpperCase() + id.slice(1), count }));

  return { families, shades, primitives };
}

async function browseStaticColors(request: Request, env: Env): Promise<Response> {
  const url = new URL(request.url);
  const { limit, offset } = parseLimitOffset(url);
  const family = (url.searchParams.get("family") || "").trim().toLowerCase() || null;
  const shade = (url.searchParams.get("shade") || "").trim().toLowerCase() || null;
  const q = (url.searchParams.get("q") || "").trim().toLowerCase();
  const requiredPrims = parsePrimitives(url);

  const all = await loadClassifiedColors(env);
  let filtered = all;
  if (family) filtered = filtered.filter((c) => c.family === family);
  if (shade) filtered = filtered.filter((c) => c.shade === shade);
  if (requiredPrims.length) filtered = filtered.filter((c) => colorMatchesPrimitives(c, requiredPrims));
  if (q) {
    filtered = filtered.filter(
      (c) =>
        c.name.toLowerCase().includes(q) ||
        c.key.toLowerCase().includes(q) ||
        `${c.r},${c.g},${c.b}`.includes(q),
    );
  }

  const facets = buildColorFacets(all, family);
  const page = pageItems(filtered, offset, limit);
  return json({
    kind: "static_colors",
    facets,
    filters: { family, shade, primitives: requiredPrims, q: q || null },
    items: page.items.map((c) => ({
      key: c.key,
      name: c.name,
      r: c.r,
      g: c.g,
      b: c.b,
      count: c.count,
      family: c.family,
      shade: c.shade,
      depth_breakdown: c.depth_breakdown,
    })),
    total: page.total,
    offset,
    limit,
    truncated: page.truncated,
    scanned: all.length,
  });
}

type SoundRow = {
  key: string;
  name: string;
  count: number;
  strength_pct: number | null;
  depth_breakdown: Record<string, number>;
  origin: string;
  tone?: string;
  timbre?: string;
};

function parseSoundOrigins(depthJson: string | null): { depth_breakdown: Record<string, number>; origin: string } {
  const depth_breakdown: Record<string, number> = {};
  let origin = "other";
  if (!depthJson) return { depth_breakdown, origin };
  try {
    const d = JSON.parse(depthJson) as Record<string, unknown>;
    const oc = d.origin_noises as Record<string, number> | undefined;
    if (oc && typeof oc === "object") {
      let best = "";
      let bestV = -1;
      for (const [k, v] of Object.entries(oc)) {
        const n = typeof v === "number" ? (v <= 1 ? v * 100 : v) : 0;
        depth_breakdown[k] = Math.round(n);
        if (n > bestV) {
          bestV = n;
          best = k;
        }
      }
      if (best) origin = best;
    }
  } catch {
    /* ignore */
  }
  return { depth_breakdown, origin };
}

async function loadSoundRows(env: Env): Promise<SoundRow[]> {
  const kv = env.MOTION_KV;
  if (kv) {
    try {
      const cached = await kv.get(BROWSE_SOUND_CACHE_KEY, "json");
      if (Array.isArray(cached) && cached.length) return cached as SoundRow[];
    } catch {
      /* ignore */
    }
  }
  const db = getPrimaryDb(env);
  const rows = await db
    .prepare(
      "SELECT sound_key, name, count, depth_breakdown_json, strength_pct, tone, timbre FROM static_sound ORDER BY count DESC LIMIT ?",
    )
    .bind(SCAN_CAP)
    .all<{
      sound_key: string;
      name: string | null;
      count: number;
      depth_breakdown_json: string | null;
      strength_pct: number | null;
      tone: string | null;
      timbre: string | null;
    }>();
  const all: SoundRow[] = (rows.results || []).map((r) => {
    const { depth_breakdown, origin } = parseSoundOrigins(r.depth_breakdown_json);
    return {
      key: r.sound_key,
      name: (r.name || r.sound_key || "").trim(),
      count: r.count || 1,
      strength_pct: r.strength_pct,
      depth_breakdown,
      origin,
      tone: r.tone || undefined,
      timbre: r.timbre || undefined,
    };
  });
  if (kv) {
    try {
      await kv.put(BROWSE_SOUND_CACHE_KEY, JSON.stringify(all), { expirationTtl: CACHE_TTL_SEC });
    } catch {
      /* ignore */
    }
  }
  return all;
}

async function browseStaticSound(request: Request, env: Env): Promise<Response> {
  const url = new URL(request.url);
  const { limit, offset } = parseLimitOffset(url);
  const family = (url.searchParams.get("family") || "").trim().toLowerCase() || null;
  const q = (url.searchParams.get("q") || "").trim().toLowerCase();
  const all = await loadSoundRows(env);

  const originSet = new Set<string>([...SOUND_ORIGIN_PRIMARIES, "other"]);
  const counts = new Map<string, number>();
  for (const o of originSet) counts.set(o, 0);
  for (const s of all) {
    const id = originSet.has(s.origin) ? s.origin : "other";
    counts.set(id, (counts.get(id) || 0) + 1);
  }
  const families: Facet[] = [...counts.entries()]
    .filter(([, c]) => c > 0)
    .sort((a, b) => b[1] - a[1])
    .map(([id, count]) => ({
      id,
      label: id.charAt(0).toUpperCase() + id.slice(1),
      count,
    }));

  let filtered = all;
  if (family) filtered = filtered.filter((s) => (originSet.has(s.origin) ? s.origin : "other") === family);
  if (q) {
    filtered = filtered.filter(
      (s) =>
        s.name.toLowerCase().includes(q) ||
        s.key.toLowerCase().includes(q) ||
        (s.tone || "").toLowerCase().includes(q) ||
        (s.timbre || "").toLowerCase().includes(q),
    );
  }
  const page = pageItems(filtered, offset, limit);
  return json({
    kind: "static_sound",
    facets: { families, shades: [], primitives: [] },
    filters: { family, q: q || null },
    items: page.items,
    total: page.total,
    offset,
    limit,
    truncated: page.truncated,
    scanned: all.length,
  });
}

const DYNAMIC_KINDS: Record<string, { table: string; keyCol: string; extra?: string[] }> = {
  learned_motion: { table: "learned_motion", keyCol: "profile_key", extra: ["motion_level", "motion_trend"] },
  learned_lighting: { table: "learned_lighting", keyCol: "profile_key", extra: ["brightness", "contrast", "saturation"] },
  learned_composition: { table: "learned_composition", keyCol: "profile_key" },
  learned_graphics: { table: "learned_graphics", keyCol: "profile_key" },
  learned_temporal: { table: "learned_temporal", keyCol: "profile_key", extra: ["duration", "motion_trend"] },
  learned_technical: { table: "learned_technical", keyCol: "profile_key", extra: ["width", "height", "fps"] },
  learned_audio_semantic: { table: "learned_audio_semantic", keyCol: "profile_key", extra: ["role"] },
  learned_time: { table: "learned_time", keyCol: "profile_key", extra: ["duration", "fps"] },
  learned_gradient: { table: "learned_gradient", keyCol: "profile_key", extra: ["gradient_type", "strength"] },
  learned_camera: { table: "learned_camera", keyCol: "profile_key", extra: ["motion_type", "speed"] },
  learned_transition: { table: "learned_transition", keyCol: "profile_key", extra: ["type", "duration_seconds"] },
  learned_depth: { table: "learned_depth", keyCol: "profile_key", extra: ["parallax_strength", "layer_count"] },
  learned_entities: { table: "learned_entities", keyCol: "profile_key", extra: ["kind", "trajectory", "label"] },
  learned_colors: { table: "learned_colors", keyCol: "color_key", extra: ["r", "g", "b"] },
};

const DYNAMIC_ASPECTS = Object.keys(DYNAMIC_KINDS);

async function loadDynamicAspectFacets(env: Env): Promise<Facet[]> {
  const db = getDb(env);
  const families: Facet[] = [];
  for (const id of DYNAMIC_ASPECTS) {
    const m = DYNAMIC_KINDS[id];
    try {
      const c = await db.prepare(`SELECT COUNT(*) AS n FROM ${m.table}`).first<{ n: number }>();
      const n = Number(c?.n || 0);
      if (n > 0) {
        families.push({
          id,
          label: id.replace(/^learned_/, "").replace(/_/g, " "),
          count: n,
        });
      }
    } catch {
      /* missing table */
    }
  }
  return families;
}

async function browseDynamic(request: Request, env: Env, kind: string): Promise<Response> {
  const url = new URL(request.url);
  const { limit, offset } = parseLimitOffset(url);
  const q = (url.searchParams.get("q") || "").trim().toLowerCase();
  // kind=dynamic with no aspect → facet rails only
  const aspectRaw = (url.searchParams.get("aspect") || "").trim().toLowerCase();
  const aspect = aspectRaw || (kind !== "dynamic" ? kind : "");
  if (!aspect) {
    const families = await loadDynamicAspectFacets(env);
    return json({
      kind: "dynamic",
      facets: { families, shades: [], primitives: [] },
      filters: { aspect: null, q: q || null },
      items: [],
      total: families.reduce((s, f) => s + f.count, 0),
      offset: 0,
      limit,
      truncated: false,
      scanned: 0,
    });
  }

  const meta = DYNAMIC_KINDS[aspect];
  if (!meta) return err(`Unknown dynamic aspect: ${aspect}`, 400);

  const db = getDb(env);
  const extras = meta.extra?.length ? `, ${meta.extra.join(", ")}` : "";
  const sql = `SELECT ${meta.keyCol} AS entry_key, name, count${extras} FROM ${meta.table} ORDER BY count DESC LIMIT ?`;
  let rows: { results?: Record<string, unknown>[] };
  try {
    rows = await db.prepare(sql).bind(SCAN_CAP).all();
  } catch {
    return json({
      kind: aspect,
      facets: { families: await loadDynamicAspectFacets(env), shades: [], primitives: [] },
      items: [],
      total: 0,
      offset,
      limit,
      truncated: false,
    });
  }

  type DynItem = { key: string; name: string; count: number; [k: string]: unknown };
  let all: DynItem[] = (rows.results || []).map((r) => {
    const key = String(r.entry_key ?? "");
    const item: DynItem = {
      key,
      name: String(r.name || key),
      count: Number(r.count || 1),
    };
    for (const col of meta.extra || []) {
      if (r[col] !== undefined) item[col] = r[col];
    }
    return item;
  });
  if (q) {
    all = all.filter(
      (i) => i.name.toLowerCase().includes(q) || i.key.toLowerCase().includes(q),
    );
  }

  const page = pageItems(all, offset, limit);
  return json({
    kind: aspect,
    facets: {
      families: [
        {
          id: aspect,
          label: aspect.replace(/^learned_/, "").replace(/_/g, " "),
          count: all.length,
        },
      ],
      shades: [],
      primitives: [],
    },
    filters: { aspect, q: q || null },
    items: page.items,
    total: page.total,
    offset,
    limit,
    truncated: page.truncated,
    scanned: all.length,
  });
}

async function browseNarrative(request: Request, env: Env): Promise<Response> {
  const url = new URL(request.url);
  const { limit, offset } = parseLimitOffset(url);
  const family = (url.searchParams.get("family") || url.searchParams.get("aspect") || "").trim().toLowerCase() || null;
  const q = (url.searchParams.get("q") || "").trim().toLowerCase();
  const db = getDb(env);
  const rows = await db
    .prepare(
      "SELECT aspect, entry_key, value, name, count FROM narrative_entries ORDER BY count DESC LIMIT ?",
    )
    .bind(SCAN_CAP)
    .all<{ aspect: string; entry_key: string; value: string; name: string | null; count: number }>();

  const all = (rows.results || []).map((r) => ({
    key: r.entry_key,
    name: (r.name || r.value || r.entry_key || "").trim(),
    value: r.value,
    aspect: r.aspect,
    count: r.count || 1,
  }));

  const aspectCounts = new Map<string, number>();
  for (const r of all) aspectCounts.set(r.aspect, (aspectCounts.get(r.aspect) || 0) + 1);
  const families: Facet[] = [...aspectCounts.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([id, count]) => ({ id, label: id.replace(/_/g, " "), count }));

  let filtered = all;
  if (family) filtered = filtered.filter((r) => r.aspect === family);
  if (q) {
    filtered = filtered.filter(
      (r) =>
        r.name.toLowerCase().includes(q) ||
        r.key.toLowerCase().includes(q) ||
        (r.value || "").toLowerCase().includes(q),
    );
  }
  const page = pageItems(filtered, offset, limit);
  return json({
    kind: "narrative",
    facets: { families, shades: [], primitives: [] },
    filters: { family, q: q || null },
    items: page.items,
    total: page.total,
    offset,
    limit,
    truncated: page.truncated,
    scanned: all.length,
  });
}

async function browseInterpretation(request: Request, env: Env): Promise<Response> {
  const url = new URL(request.url);
  const { limit, offset } = parseLimitOffset(url);
  const q = (url.searchParams.get("q") || "").trim().toLowerCase();
  const db = getDb(env);
  const rows = await db
    .prepare(
      "SELECT id, prompt, instruction_json, updated_at FROM interpretations WHERE status = 'done' AND instruction_json IS NOT NULL ORDER BY updated_at DESC LIMIT ?",
    )
    .bind(SCAN_CAP)
    .all<{ id: string; prompt: string; instruction_json: string | null; updated_at: string }>();

  let all = (rows.results || []).map((r) => {
    let instruction: unknown = null;
    if (r.instruction_json) {
      try {
        instruction = JSON.parse(r.instruction_json);
      } catch {
        instruction = r.instruction_json;
      }
    }
    return {
      id: r.id,
      key: r.id,
      name: (r.prompt || "").slice(0, 120),
      prompt: r.prompt,
      instruction,
      updated_at: r.updated_at,
      count: 1,
    };
  });
  if (q) {
    all = all.filter(
      (r) =>
        (r.prompt || "").toLowerCase().includes(q) ||
        JSON.stringify(r.instruction || {}).toLowerCase().includes(q),
    );
  }
  const page = pageItems(all, offset, limit);
  return json({
    kind: "interpretation",
    facets: { families: [], shades: [], primitives: [] },
    filters: { q: q || null },
    items: page.items,
    total: page.total,
    offset,
    limit,
    truncated: page.truncated,
    scanned: all.length,
  });
}

async function browseLinguistic(request: Request, env: Env): Promise<Response> {
  const url = new URL(request.url);
  const { limit, offset } = parseLimitOffset(url);
  const family = (url.searchParams.get("family") || "").trim().toLowerCase() || null;
  const q = (url.searchParams.get("q") || "").trim().toLowerCase();
  const db = getDb(env);
  let rows: {
    results?: Array<{
      span: string;
      canonical: string;
      domain: string;
      variant_type: string | null;
      count: number;
    }>;
  };
  try {
    rows = await db
      .prepare(
        "SELECT span, canonical, domain, variant_type, count FROM linguistic_registry ORDER BY count DESC LIMIT ?",
      )
      .bind(SCAN_CAP)
      .all();
  } catch {
    return json({
      kind: "linguistic",
      facets: { families: [] },
      items: [],
      total: 0,
      offset,
      limit,
      truncated: false,
    });
  }

  const all = (rows.results || []).map((r) => ({
    key: r.span,
    name: r.span,
    canonical: r.canonical,
    domain: r.domain,
    variant_type: r.variant_type,
    count: r.count || 1,
  }));
  const domainCounts = new Map<string, number>();
  for (const r of all) domainCounts.set(r.domain, (domainCounts.get(r.domain) || 0) + 1);
  const families: Facet[] = [...domainCounts.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([id, count]) => ({ id, label: id, count }));

  let filtered = all;
  if (family) filtered = filtered.filter((r) => r.domain === family);
  if (q) {
    filtered = filtered.filter(
      (r) =>
        r.key.toLowerCase().includes(q) ||
        r.name.toLowerCase().includes(q) ||
        (r.canonical || "").toLowerCase().includes(q) ||
        (r.domain || "").toLowerCase().includes(q),
    );
  }
  const page = pageItems(filtered, offset, limit);
  return json({
    kind: "linguistic",
    facets: { families, shades: [], primitives: [] },
    filters: { family, q: q || null },
    items: page.items,
    total: page.total,
    offset,
    limit,
    truncated: page.truncated,
    scanned: all.length,
  });
}

const VALID_KINDS = new Set([
  "static_colors",
  "static_sound",
  "narrative",
  "interpretation",
  "linguistic",
  "learned_motion",
  "learned_lighting",
  "learned_composition",
  "learned_graphics",
  "learned_temporal",
  "learned_technical",
  "learned_audio_semantic",
  "learned_time",
  "learned_gradient",
  "learned_camera",
  "learned_transition",
  "learned_depth",
  "learned_entities",
  "learned_colors",
  "dynamic",
]);

async function browseMission(env: Env): Promise<Response> {
  const colors = await loadClassifiedColors(env);
  const sounds = await loadSoundRows(env);
  const colorFacets = buildColorFacets(colors, null);
  const familiesFilled = colorFacets.families.filter((f) => f.count > 0).length;
  const familiesTotal = COLOR_FAMILY_META.length;
  const originSet = new Set<string>([...SOUND_ORIGIN_PRIMARIES]);
  const soundOriginsPresent = new Set<string>();
  for (const s of sounds) {
    if (originSet.has(s.origin)) soundOriginsPresent.add(s.origin);
  }
  const db = getDb(env);
  let narrativeAspects = 0;
  let narrativeTotal = 7;
  try {
    const rows = await db
      .prepare("SELECT DISTINCT aspect FROM narrative_entries")
      .all<{ aspect: string }>();
    narrativeAspects = (rows.results || []).length;
  } catch {
    narrativeAspects = 0;
  }
  const colorFill = familiesTotal ? familiesFilled / familiesTotal : 0;
  const soundFill = SOUND_ORIGIN_PRIMARIES.length
    ? soundOriginsPresent.size / SOUND_ORIGIN_PRIMARIES.length
    : 0;
  const narrativeFill = narrativeTotal ? Math.min(1, narrativeAspects / narrativeTotal) : 0;
  // Findability: can a human drill Blue→shade→swatch? Weighted toward color families + shade depth.
  const shadesWithColors = colorFacets.shades.filter((s) => s.count > 0).length;
  const shadeFill = COLOR_SHADE_META.length ? shadesWithColors / COLOR_SHADE_META.length : 0;
  const findability = Math.round(
    100 * (0.45 * colorFill + 0.2 * shadeFill + 0.2 * soundFill + 0.15 * narrativeFill),
  );
  return json({
    findability_pct: findability,
    colors: {
      total: colors.length,
      families_filled: familiesFilled,
      families_total: familiesTotal,
      families: colorFacets.families,
      shades_filled: shadesWithColors,
      shades_total: COLOR_SHADE_META.length,
    },
    sound: {
      total: sounds.length,
      origins_filled: soundOriginsPresent.size,
      origins_total: SOUND_ORIGIN_PRIMARIES.length,
      origins_present: [...soundOriginsPresent].sort(),
    },
    narrative: {
      aspects_filled: narrativeAspects,
      aspects_total: narrativeTotal,
    },
    hint:
      findability >= 80
        ? "Explorer findability looks strong — humans can drill most color families and sound origins."
        : "Grow frame (colors/sounds) and window (narrative) loops until family/origin brackets fill out.",
  });
}

export async function handleRegistryBrowse(
  request: Request,
  env: Env,
  path: string,
): Promise<Response | null> {
  if (path === "/api/registries/mission" && request.method === "GET") {
    try {
      return await browseMission(env);
    } catch (e) {
      console.error("GET /api/registries/mission failed:", e);
      return json({ error: "Mission metrics failed", details: String(e) }, 500);
    }
  }
  if (path !== "/api/registries/browse" || request.method !== "GET") return null;

  const url = new URL(request.url);
  const kind = (url.searchParams.get("kind") || "static_colors").trim().toLowerCase();
  if (!VALID_KINDS.has(kind) && !DYNAMIC_KINDS[kind]) {
    return err(`Unknown kind. Use one of: static_colors, static_sound, narrative, interpretation, linguistic, dynamic, or learned_*`, 400);
  }

  try {
    if (kind === "static_colors") return await browseStaticColors(request, env);
    if (kind === "static_sound") return await browseStaticSound(request, env);
    if (kind === "narrative") return await browseNarrative(request, env);
    if (kind === "interpretation") return await browseInterpretation(request, env);
    if (kind === "linguistic") return await browseLinguistic(request, env);
    return await browseDynamic(request, env, kind);
  } catch (e) {
    console.error("GET /api/registries/browse failed:", e);
    return json({ error: "Browse failed", details: String(e) }, 500);
  }
}

// Re-export types used only to keep family ids available for tests / future
export type { ColorFamilyId, ColorShadeId };
