/**
 * Knowledge discoveries, for-creation, colors, name reserve API routes.
 */
import type { Env } from "../env";
import { getDb, ensureLearnedColorsDepthColumn, upsertLearnedDynamicMeta, bumpRegistryCounts } from "../db";
import { json, err, uuid } from "../http";
import {
  resolveUniqueBlendName,
  titleCaseLabel,
  sanitizePureSoundKey,
  generateUniqueName,
} from "../naming";

export async function handleKnowledgeRoutes(
  request: Request,
  env: Env,
  path: string,
): Promise<Response | null> {
  const db = getDb(env);

// GET /api/knowledge/prompts — distinct prompts from jobs (for automation avoid set)
if (path === "/api/knowledge/prompts" && request.method === "GET") {
  const limit = Math.min(parseInt(new URL(request.url).searchParams.get("limit") || "500", 10), 1000);
  const rows = await db.prepare(
    "SELECT prompt FROM jobs WHERE prompt IS NOT NULL AND prompt != '' ORDER BY created_at DESC LIMIT ?"
  )
    .bind(limit * 2)
    .all<{ prompt: string }>();
  const seen = new Set<string>();
  const prompts: string[] = [];
  for (const r of rows.results || []) {
    if (!seen.has(r.prompt)) {
      seen.add(r.prompt);
      prompts.push(r.prompt);
      if (prompts.length >= limit) break;
    }
  }
  return json({ prompts });
}

// POST /api/knowledge/name/take — reserve a unique name for a discovery
if (path === "/api/knowledge/name/take" && request.method === "POST") {
  const name = await generateUniqueName(env);
  await db.prepare("INSERT OR IGNORE INTO name_reserve (name) VALUES (?)").bind(name).run();
  return json({ name }, 201);
}

// POST /api/knowledge/discoveries — batch record discoveries (D1)
// Supports: static_colors, static_sound (per-frame) + colors, blends, motion, etc. (dynamic/whole-video)
// Reduced to 50 items to stay under D1 CPU limit under 6-worker concurrency.
if (path === "/api/knowledge/discoveries" && request.method === "POST") {
  const DISCOVERIES_MAX_ITEMS = 25;
  let body: {
    static_colors?: Array<{ key: string; r: number; g: number; b: number; brightness?: number; luminance?: number; contrast?: number; saturation?: number; chroma?: number; hue?: number; color_variance?: number; opacity?: number; depth_breakdown?: Record<string, unknown>; source_prompt?: string; name?: string }>;
    static_sound?: Array<{ key: string; amplitude?: number; weight?: number; strength_pct?: number; tone?: string; timbre?: string; depth_breakdown?: Record<string, unknown>; source_prompt?: string; name?: string }>;
    colors?: Array<{
      key: string;
      r: number;
      g: number;
      b: number;
      source_prompt?: string;
      name?: string;
      depth_breakdown?: Record<string, unknown>;
    }>;
    blends?: Array<{ name: string; domain: string; inputs: Record<string, unknown>; output: Record<string, unknown>; primitive_depths?: Record<string, unknown>; source_prompt?: string }>;
    motion?: Array<{ key: string; motion_level: number; motion_std: number; motion_trend: string; motion_direction?: string; motion_rhythm?: string; depth_breakdown?: Record<string, unknown>; source_prompt?: string }>;
    lighting?: Array<{ key: string; brightness: number; contrast: number; saturation: number; depth_breakdown?: Record<string, unknown>; source_prompt?: string }>;
    composition?: Array<{ key: string; center_x: number; center_y: number; luminance_balance: number; source_prompt?: string }>;
    graphics?: Array<{ key: string; edge_density: number; spatial_variance: number; busyness: number; source_prompt?: string }>;
    temporal?: Array<{
      key: string;
      duration: number;
      motion_trend: string;
      source_prompt?: string;
      depth_breakdown?: Record<string, unknown>;
    }>;
    technical?: Array<{
      key: string;
      width: number;
      height: number;
      fps: number;
      source_prompt?: string;
      depth_breakdown?: Record<string, unknown>;
    }>;
    audio_semantic?: Array<{ key: string; role: string; mood?: string; tempo?: string; source_prompt?: string; name?: string }>;
    time?: Array<{ key: string; duration: number; fps: number; source_prompt?: string }>;
    gradient?: Array<{ key: string; gradient_type: string; strength?: number; depth_breakdown?: Record<string, unknown>; source_prompt?: string }>;
    camera?: Array<{ key: string; motion_type: string; speed?: string; depth_breakdown?: Record<string, unknown>; source_prompt?: string }>;
    transition?: Array<{ key: string; type: string; duration_seconds?: number; source_prompt?: string }>;
    depth?: Array<{ key: string; parallax_strength?: number; layer_count?: number; source_prompt?: string }>;
    entities?: Array<{
      key: string;
      kind: string;
      trajectory?: string;
      bounce?: number | boolean;
      color_hint?: string;
      label?: string;
      directionality?: string;
      entity_json?: Record<string, unknown>;
      source_prompt?: string;
      name?: string;
    }>;
    narrative?: Record<string, Array<{ key: string; value?: string; source_prompt?: string; name?: string }>>;
    job_id?: string;
  };
  try {
    body = (await request.json()) as typeof body;
  } catch {
    return err("Invalid JSON");
  }
  const results: Record<string, number> = { static_colors: 0, static_sound: 0, narrative: 0, colors: 0, blends: 0, motion: 0, lighting: 0, composition: 0, graphics: 0, temporal: 0, technical: 0, audio_semantic: 0, time: 0, gradient: 0, camera: 0, transition: 0, depth: 0, entities: 0 };
  let itemsProcessed = 0;
  let truncated = false;
  let novelStaticColors = 0;
  let novelStaticSound = 0;
  let novelLearnedColors = 0;

  try {
  // Static registry: per-frame color entries
  for (const c of body.static_colors || []) {
    if (itemsProcessed >= DISCOVERIES_MAX_ITEMS) { truncated = true; break; }
    const existing = await db.prepare("SELECT id, name, count FROM static_colors WHERE color_key = ?").bind(c.key).first();
    if (existing) {
      await db.prepare("UPDATE static_colors SET count = count + 1 WHERE color_key = ?").bind(c.key).run();
    } else {
      const name = (c.name && c.name.trim()) ? c.name : await generateUniqueName(env);
      if (!c.name || !c.name.trim()) {
        try { await db.prepare("INSERT OR IGNORE INTO name_reserve (name) VALUES (?)").bind(name).run(); } catch { /* ignore */ }
      }
      await db.prepare(
        "INSERT INTO static_colors (id, color_key, r, g, b, brightness, luminance, contrast, saturation, chroma, hue, color_variance, opacity, count, sources_json, name, depth_breakdown_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)"
      ).bind(uuid(), c.key, c.r, c.g, c.b, c.brightness ?? null, c.luminance ?? c.brightness ?? null, c.contrast ?? null, c.saturation ?? null, c.chroma ?? c.saturation ?? null, c.hue ?? null, c.color_variance ?? null, c.opacity ?? null, c.source_prompt ? JSON.stringify([c.source_prompt.slice(0, 80)]) : null, name, c.depth_breakdown ? JSON.stringify(c.depth_breakdown) : null).run();
      novelStaticColors++;
    }
    results.static_colors++;
    itemsProcessed++;
  }
  // Static registry: per-frame sound entries
  for (const s of body.static_sound || []) {
    if (itemsProcessed >= DISCOVERIES_MAX_ITEMS) { truncated = true; break; }
    const rawKey = s.key || "";
    const key = sanitizePureSoundKey(rawKey);
    const existing = await db.prepare("SELECT id, name, count FROM static_sound WHERE sound_key = ?").bind(key).first();
    if (existing) {
      await db.prepare("UPDATE static_sound SET count = count + 1 WHERE sound_key = ?").bind(key).run();
    } else {
      const name = (s.name && s.name.trim()) ? s.name : await generateUniqueName(env);
      if (!s.name || !s.name.trim()) {
        try { await db.prepare("INSERT OR IGNORE INTO name_reserve (name) VALUES (?)").bind(name).run(); } catch { /* ignore */ }
      }
      await db.prepare(
        "INSERT INTO static_sound (id, sound_key, amplitude, weight, tone, timbre, count, sources_json, name, depth_breakdown_json, strength_pct) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)"
      ).bind(uuid(), key, s.amplitude ?? null, s.weight ?? null, s.tone ?? null, s.timbre ?? null, s.source_prompt ? JSON.stringify([s.source_prompt.slice(0, 80)]) : null, name, s.depth_breakdown ? JSON.stringify(s.depth_breakdown) : null, s.strength_pct ?? s.amplitude ?? s.weight ?? null).run();
      novelStaticSound++;
    }
    results.static_sound++;
    itemsProcessed++;
  }
  // Narrative registry: themes, plots, settings, genre, mood, scene_type
  const narrativeAspects = ["genre", "mood", "plots", "settings", "themes", "style", "scene_type"];
  narrative_loop: for (const aspect of narrativeAspects) {
    for (const item of body.narrative?.[aspect] || []) {
      if (itemsProcessed >= DISCOVERIES_MAX_ITEMS) { truncated = true; break narrative_loop; }
      const key = (item.key || "").trim().toLowerCase();
      if (!key) continue;
      const existing = await db.prepare("SELECT id, name, count FROM narrative_entries WHERE aspect = ? AND entry_key = ?").bind(aspect, key).first();
      if (existing) {
        await db.prepare("UPDATE narrative_entries SET count = count + 1 WHERE aspect = ? AND entry_key = ?").bind(aspect, key).run();
      } else {
        const valueStr = (item.value ?? item.key ?? key).slice(0, 200);
        const name = (item.name && item.name.trim()) ? item.name.trim() : titleCaseLabel(valueStr || key);
        if (!(item.name && item.name.trim())) {
          try { await db.prepare("INSERT OR IGNORE INTO name_reserve (name) VALUES (?)").bind(name).run(); } catch { /* ignore */ }
        }
        await db.prepare(
          "INSERT INTO narrative_entries (id, aspect, entry_key, value, count, sources_json, name) VALUES (?, ?, ?, ?, 1, ?, ?)"
        ).bind(uuid(), aspect, key, valueStr, item.source_prompt ? JSON.stringify([item.source_prompt.slice(0, 80)]) : null, name).run();
      }
      results.narrative++;
      itemsProcessed++;
    }
  }
  if ((body.colors || []).length > 0) {
    const depthOk = await ensureLearnedColorsDepthColumn(db);
    if (!depthOk) {
      return json(
        { error: "learned_colors.depth_breakdown_json is not available yet (D1 ALTER pending). Retry later or add the column in the D1 dashboard." },
        503,
      );
    }
  }
  for (const c of body.colors || []) {
    if (itemsProcessed >= DISCOVERIES_MAX_ITEMS) { truncated = true; break; }
    const existing = await db.prepare("SELECT id, name, count FROM learned_colors WHERE color_key = ?").bind(c.key).first();
    const depthJson = c.depth_breakdown && typeof c.depth_breakdown === "object" ? JSON.stringify(c.depth_breakdown) : null;
    if (existing) {
      await db.prepare("UPDATE learned_colors SET count = count + 1 WHERE color_key = ?").bind(c.key).run();
      if (depthJson) {
        await db.prepare("UPDATE learned_colors SET depth_breakdown_json = ? WHERE color_key = ?").bind(depthJson, c.key).run();
      }
    } else {
      const name = (c.name && String(c.name).trim()) || await generateUniqueName(env);
      if (!c.name || !String(c.name).trim()) await db.prepare("INSERT OR IGNORE INTO name_reserve (name) VALUES (?)").bind(name).run();
      await db.prepare(
        "INSERT INTO learned_colors (id, color_key, r, g, b, count, sources_json, name, depth_breakdown_json) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)"
      ).bind(uuid(), c.key, c.r, c.g, c.b, c.source_prompt ? JSON.stringify([c.source_prompt.slice(0, 80)]) : null, name, depthJson).run();
      novelLearnedColors++;
    }
    results.colors++;
    itemsProcessed++;
  }
  for (const b of body.blends || []) {
    if (itemsProcessed >= DISCOVERIES_MAX_ITEMS) { truncated = true; break; }
    let name = (b.name && b.name.trim()) ? b.name.trim() : await generateUniqueName(env);
    if (b.name && b.name.trim()) {
      name = await resolveUniqueBlendName(env, name);
    } else {
      await db.prepare("INSERT OR IGNORE INTO name_reserve (name) VALUES (?)").bind(name).run();
    }
    await db.prepare(
      "INSERT INTO learned_blends (id, name, domain, inputs_json, output_json, primitive_depths_json, source_prompt) VALUES (?, ?, ?, ?, ?, ?, ?)"
    ).bind(uuid(), name, b.domain, JSON.stringify(b.inputs), JSON.stringify(b.output), b.primitive_depths ? JSON.stringify(b.primitive_depths) : null, (b.source_prompt || "").slice(0, 120)).run();
    results.blends++;
    itemsProcessed++;
  }
  for (const t of body.time || []) {
    if (itemsProcessed >= DISCOVERIES_MAX_ITEMS) { truncated = true; break; }
    const existing = await db.prepare("SELECT id FROM learned_time WHERE profile_key = ?").bind(t.key).first();
    if (existing) {
      await db.prepare("UPDATE learned_time SET count = count + 1 WHERE profile_key = ?").bind(t.key).run();
    } else {
      const name = await generateUniqueName(env);
      await db.prepare("INSERT OR IGNORE INTO name_reserve (name) VALUES (?)").bind(name).run();
      await db.prepare(
        "INSERT INTO learned_time (id, profile_key, duration, fps, count, sources_json, name) VALUES (?, ?, ?, ?, 1, ?, ?)"
      ).bind(uuid(), t.key, t.duration, t.fps, t.source_prompt ? JSON.stringify([t.source_prompt.slice(0, 80)]) : null, name).run();
    }
    results.time++;
    itemsProcessed++;
  }
  for (const m of body.motion || []) {
    if (itemsProcessed >= DISCOVERIES_MAX_ITEMS) { truncated = true; break; }
    const existing = await db.prepare("SELECT id FROM learned_motion WHERE profile_key = ?").bind(m.key).first();
    const motionDepthJson =
      m.depth_breakdown && typeof m.depth_breakdown === "object" ? JSON.stringify(m.depth_breakdown) : null;
    if (existing) {
      await db.prepare("UPDATE learned_motion SET count = count + 1 WHERE profile_key = ?").bind(m.key).run();
      if (motionDepthJson) {
        await db.prepare("UPDATE learned_motion SET depth_breakdown_json = ? WHERE profile_key = ?").bind(motionDepthJson, m.key).run();
      }
    } else {
      const name = await generateUniqueName(env);
      await db.prepare("INSERT OR IGNORE INTO name_reserve (name) VALUES (?)").bind(name).run();
      await db.prepare(
        "INSERT INTO learned_motion (id, profile_key, motion_level, motion_std, motion_trend, motion_direction, motion_rhythm, count, sources_json, name, depth_breakdown_json) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)"
      ).bind(uuid(), m.key, m.motion_level, m.motion_std, m.motion_trend, m.motion_direction ?? "neutral", m.motion_rhythm ?? "steady", m.source_prompt ? JSON.stringify([m.source_prompt.slice(0, 80)]) : null, name, motionDepthJson).run();
    }
    results.motion++;
    itemsProcessed++;
  }
  for (const l of body.lighting || []) {
    if (itemsProcessed >= DISCOVERIES_MAX_ITEMS) { truncated = true; break; }
    const existing = await db.prepare("SELECT id FROM learned_lighting WHERE profile_key = ?").bind(l.key).first();
    if (existing) {
      await db.prepare("UPDATE learned_lighting SET count = count + 1 WHERE profile_key = ?").bind(l.key).run();
    } else {
      const name = await generateUniqueName(env);
      await db.prepare("INSERT OR IGNORE INTO name_reserve (name) VALUES (?)").bind(name).run();
      await db.prepare(
        "INSERT INTO learned_lighting (id, profile_key, brightness, contrast, saturation, count, sources_json, name, depth_breakdown_json) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)"
      ).bind(uuid(), l.key, l.brightness, l.contrast, l.saturation, l.source_prompt ? JSON.stringify([l.source_prompt.slice(0, 80)]) : null, name, l.depth_breakdown ? JSON.stringify(l.depth_breakdown) : null).run();
    }
    results.lighting++;
    itemsProcessed++;
  }
  for (const c of body.composition || []) {
    if (itemsProcessed >= DISCOVERIES_MAX_ITEMS) { truncated = true; break; }
    const existing = await db.prepare("SELECT id FROM learned_composition WHERE profile_key = ?").bind(c.key).first();
    if (existing) {
      await db.prepare("UPDATE learned_composition SET count = count + 1 WHERE profile_key = ?").bind(c.key).run();
    } else {
      const name = await generateUniqueName(env);
      await db.prepare("INSERT OR IGNORE INTO name_reserve (name) VALUES (?)").bind(name).run();
      await db.prepare(
        "INSERT INTO learned_composition (id, profile_key, center_x, center_y, luminance_balance, count, sources_json, name) VALUES (?, ?, ?, ?, ?, 1, ?, ?)"
      ).bind(uuid(), c.key, c.center_x, c.center_y, c.luminance_balance, c.source_prompt ? JSON.stringify([c.source_prompt.slice(0, 80)]) : null, name).run();
    }
    results.composition++;
    itemsProcessed++;
  }
  for (const g of body.graphics || []) {
    if (itemsProcessed >= DISCOVERIES_MAX_ITEMS) { truncated = true; break; }
    const existing = await db.prepare("SELECT id FROM learned_graphics WHERE profile_key = ?").bind(g.key).first();
    if (existing) {
      await db.prepare("UPDATE learned_graphics SET count = count + 1 WHERE profile_key = ?").bind(g.key).run();
    } else {
      const name = await generateUniqueName(env);
      await db.prepare("INSERT OR IGNORE INTO name_reserve (name) VALUES (?)").bind(name).run();
      await db.prepare(
        "INSERT INTO learned_graphics (id, profile_key, edge_density, spatial_variance, busyness, count, sources_json, name) VALUES (?, ?, ?, ?, ?, 1, ?, ?)"
      ).bind(uuid(), g.key, g.edge_density, g.spatial_variance, g.busyness, g.source_prompt ? JSON.stringify([g.source_prompt.slice(0, 80)]) : null, name).run();
    }
    results.graphics++;
    itemsProcessed++;
  }
  for (const t of body.temporal || []) {
    if (itemsProcessed >= DISCOVERIES_MAX_ITEMS) { truncated = true; break; }
    const depthJson =
      t.depth_breakdown && typeof t.depth_breakdown === "object" ? JSON.stringify(t.depth_breakdown) : null;
    const existing = await db.prepare("SELECT id FROM learned_temporal WHERE profile_key = ?").bind(t.key).first();
    if (existing) {
      await db.prepare("UPDATE learned_temporal SET count = count + 1 WHERE profile_key = ?").bind(t.key).run();
    } else {
      const name = await generateUniqueName(env);
      await db.prepare("INSERT OR IGNORE INTO name_reserve (name) VALUES (?)").bind(name).run();
      await db.prepare(
        "INSERT INTO learned_temporal (id, profile_key, duration, motion_trend, count, sources_json, name) VALUES (?, ?, ?, ?, 1, ?, ?)"
      )
        .bind(uuid(), t.key, t.duration, t.motion_trend, t.source_prompt ? JSON.stringify([t.source_prompt.slice(0, 80)]) : null, name)
        .run();
    }
    await upsertLearnedDynamicMeta(db, "temporal", t.key, depthJson);
    results.temporal++;
    itemsProcessed++;
  }
  for (const t of body.technical || []) {
    if (itemsProcessed >= DISCOVERIES_MAX_ITEMS) { truncated = true; break; }
    const depthJson =
      t.depth_breakdown && typeof t.depth_breakdown === "object" ? JSON.stringify(t.depth_breakdown) : null;
    const existing = await db.prepare("SELECT id FROM learned_technical WHERE profile_key = ?").bind(t.key).first();
    if (existing) {
      await db.prepare("UPDATE learned_technical SET count = count + 1 WHERE profile_key = ?").bind(t.key).run();
    } else {
      const name = await generateUniqueName(env);
      await db.prepare("INSERT OR IGNORE INTO name_reserve (name) VALUES (?)").bind(name).run();
      await db.prepare(
        "INSERT INTO learned_technical (id, profile_key, width, height, fps, count, sources_json, name) VALUES (?, ?, ?, ?, ?, 1, ?, ?)"
      )
        .bind(uuid(), t.key, t.width, t.height, t.fps, t.source_prompt ? JSON.stringify([t.source_prompt.slice(0, 80)]) : null, name)
        .run();
    }
    await upsertLearnedDynamicMeta(db, "technical", t.key, depthJson);
    results.technical++;
    itemsProcessed++;
  }
  for (const a of body.audio_semantic || []) {
    if (itemsProcessed >= DISCOVERIES_MAX_ITEMS) { truncated = true; break; }
    const existing = await db.prepare("SELECT id FROM learned_audio_semantic WHERE profile_key = ?").bind(a.key).first();
    if (existing) {
      await db.prepare("UPDATE learned_audio_semantic SET count = count + 1 WHERE profile_key = ?").bind(a.key).run();
    } else {
      const name = (a.name && a.name.trim()) ? a.name : await generateUniqueName(env);
      if (!a.name || !a.name.trim()) await db.prepare("INSERT OR IGNORE INTO name_reserve (name) VALUES (?)").bind(name).run();
      await db.prepare(
        "INSERT INTO learned_audio_semantic (id, profile_key, role, count, sources_json, name) VALUES (?, ?, ?, 1, ?, ?)"
      ).bind(uuid(), a.key, a.role || "ambient", a.source_prompt ? JSON.stringify([a.source_prompt.slice(0, 80)]) : null, name).run();
    }
    results.audio_semantic++;
    itemsProcessed++;
  }
  for (const g of body.gradient || []) {
    if (itemsProcessed >= DISCOVERIES_MAX_ITEMS) { truncated = true; break; }
    const existing = await db.prepare("SELECT id FROM learned_gradient WHERE profile_key = ?").bind(g.key).first();
    if (existing) {
      await db.prepare("UPDATE learned_gradient SET count = count + 1 WHERE profile_key = ?").bind(g.key).run();
    } else {
      const name = await generateUniqueName(env);
      await db.prepare("INSERT OR IGNORE INTO name_reserve (name) VALUES (?)").bind(name).run();
      await db.prepare(
        "INSERT INTO learned_gradient (id, profile_key, gradient_type, strength, count, sources_json, name, depth_breakdown_json) VALUES (?, ?, ?, ?, 1, ?, ?, ?)"
      ).bind(uuid(), g.key, g.gradient_type ?? "angled", g.strength ?? null, g.source_prompt ? JSON.stringify([g.source_prompt.slice(0, 80)]) : null, name, g.depth_breakdown ? JSON.stringify(g.depth_breakdown) : null).run();
    }
    results.gradient++;
    itemsProcessed++;
  }
  for (const c of body.camera || []) {
    if (itemsProcessed >= DISCOVERIES_MAX_ITEMS) { truncated = true; break; }
    const existing = await db.prepare("SELECT id FROM learned_camera WHERE profile_key = ?").bind(c.key).first();
    if (existing) {
      await db.prepare("UPDATE learned_camera SET count = count + 1 WHERE profile_key = ?").bind(c.key).run();
    } else {
      const name = await generateUniqueName(env);
      await db.prepare("INSERT OR IGNORE INTO name_reserve (name) VALUES (?)").bind(name).run();
      await db.prepare(
        "INSERT INTO learned_camera (id, profile_key, motion_type, speed, count, sources_json, name, depth_breakdown_json) VALUES (?, ?, ?, ?, 1, ?, ?, ?)"
      ).bind(uuid(), c.key, c.motion_type ?? "static", c.speed ?? null, c.source_prompt ? JSON.stringify([c.source_prompt.slice(0, 80)]) : null, name, c.depth_breakdown ? JSON.stringify(c.depth_breakdown) : null).run();
    }
    results.camera++;
    itemsProcessed++;
  }
  for (const t of body.transition || []) {
    if (itemsProcessed >= DISCOVERIES_MAX_ITEMS) { truncated = true; break; }
    const existing = await db.prepare("SELECT id FROM learned_transition WHERE profile_key = ?").bind(t.key).first();
    if (existing) {
      await db.prepare("UPDATE learned_transition SET count = count + 1 WHERE profile_key = ?").bind(t.key).run();
    } else {
      const name = await generateUniqueName(env);
      await db.prepare("INSERT OR IGNORE INTO name_reserve (name) VALUES (?)").bind(name).run();
      await db.prepare(
        "INSERT INTO learned_transition (id, profile_key, type, duration_seconds, count, sources_json, name) VALUES (?, ?, ?, ?, 1, ?, ?)"
      ).bind(uuid(), t.key, t.type ?? "cut", t.duration_seconds ?? null, t.source_prompt ? JSON.stringify([t.source_prompt.slice(0, 80)]) : null, name).run();
    }
    results.transition++;
    itemsProcessed++;
  }
  for (const d of body.depth || []) {
    if (itemsProcessed >= DISCOVERIES_MAX_ITEMS) { truncated = true; break; }
    const existing = await db.prepare("SELECT id FROM learned_depth WHERE profile_key = ?").bind(d.key).first();
    if (existing) {
      await db.prepare("UPDATE learned_depth SET count = count + 1 WHERE profile_key = ?").bind(d.key).run();
    } else {
      const name = await generateUniqueName(env);
      await db.prepare("INSERT OR IGNORE INTO name_reserve (name) VALUES (?)").bind(name).run();
      await db.prepare(
        "INSERT INTO learned_depth (id, profile_key, parallax_strength, layer_count, count, sources_json, name) VALUES (?, ?, ?, ?, 1, ?, ?)"
      ).bind(uuid(), d.key, d.parallax_strength ?? null, d.layer_count ?? null, d.source_prompt ? JSON.stringify([d.source_prompt.slice(0, 80)]) : null, name).run();
    }
    results.depth++;
    itemsProcessed++;
  }
  for (const e of body.entities || []) {
    if (itemsProcessed >= DISCOVERIES_MAX_ITEMS) { truncated = true; break; }
    const existing = await db.prepare("SELECT id FROM learned_entities WHERE profile_key = ?").bind(e.key).first();
    const bounceVal = e.bounce === true || e.bounce === 1 ? 1 : 0;
    const entityJson =
      e.entity_json && typeof e.entity_json === "object" ? JSON.stringify(e.entity_json) : null;
    if (existing) {
      await db.prepare("UPDATE learned_entities SET count = count + 1 WHERE profile_key = ?").bind(e.key).run();
      if (entityJson) {
        await db.prepare("UPDATE learned_entities SET entity_json = ? WHERE profile_key = ?").bind(entityJson, e.key).run();
      }
    } else {
      const name = (e.name && e.name.trim()) ? e.name : await generateUniqueName(env);
      if (!e.name || !e.name.trim()) {
        try { await db.prepare("INSERT OR IGNORE INTO name_reserve (name) VALUES (?)").bind(name).run(); } catch { /* ignore */ }
      }
      await db.prepare(
        "INSERT INTO learned_entities (id, profile_key, kind, trajectory, bounce, color_hint, label, directionality, count, sources_json, name, entity_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)"
      ).bind(
        uuid(),
        e.key,
        e.kind || "circle",
        e.trajectory ?? "none",
        bounceVal,
        e.color_hint ?? null,
        e.label ?? null,
        e.directionality ?? "none",
        e.source_prompt ? JSON.stringify([e.source_prompt.slice(0, 80)]) : null,
        name,
        entityJson
      ).run();
    }
    results.entities++;
    itemsProcessed++;
  }
  const jobId = typeof (body as { job_id?: string }).job_id === "string" ? (body as { job_id: string }).job_id.trim() : null;
  // Record discovery run when job_id present (even if no discovery rows) so diagnostics show "attempted"
  if (jobId) {
    try {
      await db.prepare("INSERT INTO discovery_runs (id, job_id) VALUES (?, ?)")
        .bind(uuid(), jobId).run();
    } catch {
      // Ignore duplicate or missing table
    }
  }
  // Do not use KV delete (free tier limit). Stats cache expires via TTL; GET recomputes when stale.
  if (novelStaticColors || novelStaticSound || novelLearnedColors) {
    await bumpRegistryCounts(env, {
      static_colors: novelStaticColors,
      static_sound: novelStaticSound,
      learned_colors: novelLearnedColors,
    });
  }
  const resp: { status: string; results: Record<string, number>; truncated?: boolean } = { status: "recorded", results };
  if (truncated) resp.truncated = true;
  return json(resp, 201);
  } catch (e) {
    console.error("POST /api/knowledge/discoveries failed:", e);
    return json({ error: "Failed to record discoveries", details: String(e) }, 500);
  }
}

// GET /api/knowledge/colors — check if color key exists (for novelty check)
if (path === "/api/knowledge/colors" && request.method === "GET") {
  const key = new URL(request.url).searchParams.get("key");
  if (!key) return err("key required");
  const row = await db.prepare("SELECT color_key FROM learned_colors WHERE color_key = ?").bind(key).first();
  return json({ exists: !!row });
}

// GET /api/knowledge/for-creation — learned colors and motion for creation (closes the loop)
if (path === "/api/knowledge/for-creation" && request.method === "GET") {
  try {
  const limit = Math.min(parseInt(new URL(request.url).searchParams.get("limit") || "40", 10), 200);
  const interpLimitParam = new URL(request.url).searchParams.get("interpretation_limit") || "40";
  const interpLimit = Math.min(parseInt(interpLimitParam, 10), 120);
  const cacheKey = `knowledge:for-creation:${limit}:${interpLimit}`;
  if (env.MOTION_KV) {
    const cached = await env.MOTION_KV.get(cacheKey);
    if (cached) return new Response(cached, { headers: { "Content-Type": "application/json", "X-Cache": "HIT" } });
  }
  // Single batch reduces D1 round-trips and CPU overhead
  const batchResults = await db.batch([
    db.prepare("SELECT color_key, r, g, b, count, sources_json, name FROM learned_colors ORDER BY count DESC LIMIT ?").bind(limit),
    db.prepare("SELECT profile_key, motion_level, motion_std, motion_trend, count, sources_json, name FROM learned_motion ORDER BY count DESC LIMIT ?").bind(limit),
    db.prepare("SELECT domain, inputs_json, output_json, source_prompt, created_at FROM learned_blends WHERE domain = 'audio' ORDER BY created_at DESC LIMIT ?").bind(limit),
    db.prepare("SELECT output_json FROM learned_blends WHERE domain = 'gradient' ORDER BY created_at DESC LIMIT ?").bind(limit),
    db.prepare("SELECT gradient_type FROM learned_gradient ORDER BY count DESC LIMIT ?").bind(limit),
    db.prepare("SELECT output_json FROM learned_blends WHERE domain = 'camera' ORDER BY created_at DESC LIMIT ?").bind(limit),
    db.prepare("SELECT motion_type FROM learned_camera ORDER BY count DESC LIMIT ?").bind(limit),
    db.prepare("SELECT prompt, instruction_json FROM interpretations WHERE status = 'done' AND instruction_json IS NOT NULL ORDER BY updated_at DESC LIMIT ?").bind(interpLimit),
    db.prepare("SELECT color_key, r, g, b, count, created_at FROM static_colors ORDER BY count DESC LIMIT ?").bind(limit),
    db.prepare("SELECT sound_key, tone, timbre, amplitude, name, count, created_at FROM static_sound ORDER BY count DESC LIMIT ?").bind(limit),
  ]);
  type ColorRow = { color_key: string; r: number; g: number; b: number; count: number; sources_json: string | null; name: string };
  type MotionRow = { profile_key: string; motion_level: number; motion_std: number; motion_trend: string; count: number; sources_json: string | null; name: string | null };
  type AudioRow = { domain: string; inputs_json: string; output_json: string; source_prompt: string | null; created_at: string };
  type OutputRow = { output_json: string };
  type GradientRow = { gradient_type: string };
  type CameraRow = { motion_type: string };
  type InterpRow = { prompt: string; instruction_json: string };
  type StaticColorRow = { color_key: string; r: number; g: number; b: number; count: number; created_at: string | null };
  type StaticSoundRow = { sound_key: string; tone: string | null; timbre: string | null; amplitude: number | null; name: string | null; count: number; created_at: string | null };
  const colorRows = (batchResults[0].results || []) as ColorRow[];
  const colors: Record<string, { r: number; g: number; b: number; count: number; sources: string[]; name: string }> = {};
  for (const r of colorRows) {
    colors[r.color_key] = {
      r: r.r,
      g: r.g,
      b: r.b,
      count: r.count,
      sources: r.sources_json ? (JSON.parse(r.sources_json) as string[]) : [],
      name: r.name,
    };
  }
  const motionRows = (batchResults[1].results || []) as MotionRow[];
  const motion = motionRows.map((r) => ({
    key: r.profile_key,
    motion_level: r.motion_level,
    motion_std: r.motion_std,
    motion_trend: r.motion_trend,
    count: r.count,
    sources: r.sources_json ? (JSON.parse(r.sources_json) as string[]) : [],
    name: r.name,
  }));
  const audioRows = (batchResults[2].results || []) as AudioRow[];
  const learned_audio = audioRows.map((r) => ({
    tempo: (JSON.parse(r.output_json) as Record<string, unknown>).tempo ?? "medium",
    mood: (JSON.parse(r.output_json) as Record<string, unknown>).mood ?? "neutral",
    presence: (JSON.parse(r.output_json) as Record<string, unknown>).presence ?? "ambient",
    source_prompt: r.source_prompt ?? "",
    created_at: r.created_at,
  }));
  const gradientSeen = new Set<string>();
  const learned_gradient: string[] = [];
  for (const r of (batchResults[3].results || []) as OutputRow[]) {
    const out = JSON.parse(r.output_json) as Record<string, unknown>;
    const v = typeof out.gradient_type === "string" ? out.gradient_type.trim() : "";
    if (v && !gradientSeen.has(v)) {
      gradientSeen.add(v);
      learned_gradient.push(v);
    }
  }
  for (const r of (batchResults[4].results || []) as GradientRow[]) {
    const v = (r.gradient_type || "").trim();
    if (v && !gradientSeen.has(v)) {
      gradientSeen.add(v);
      learned_gradient.push(v);
    }
  }
  const cameraSeen = new Set<string>();
  const learned_camera: string[] = [];
  for (const r of (batchResults[5].results || []) as OutputRow[]) {
    const out = JSON.parse(r.output_json) as Record<string, unknown>;
    const v = typeof out.camera_motion === "string" ? out.camera_motion.trim() : "";
    if (v && !cameraSeen.has(v)) {
      cameraSeen.add(v);
      learned_camera.push(v);
    }
  }
  for (const r of (batchResults[6].results || []) as CameraRow[]) {
    const v = (r.motion_type || "").trim();
    if (v && !cameraSeen.has(v)) {
      cameraSeen.add(v);
      learned_camera.push(v);
    }
  }
  const origin_gradient = ["vertical", "horizontal", "radial", "angled"];
  const origin_camera = ["static", "pan", "tilt", "dolly", "crane", "zoom", "zoom_out", "handheld", "roll", "truck", "pedestal", "arc", "tracking", "birds_eye", "whip_pan", "rotate"];
  const origin_motion = ["slow", "wave", "flow", "fast", "pulse"];
  const interpRows = (batchResults[7].results || []) as InterpRow[];
  const interpretation_prompts = interpRows.map((r) => ({
    prompt: r.prompt,
    instruction: r.instruction_json ? (JSON.parse(r.instruction_json) as Record<string, unknown>) : {},
  }));
  const staticColorRows = (batchResults[8].results || []) as StaticColorRow[];
  const static_colors: Record<string, { r: number; g: number; b: number; count?: number; created_at?: string }> = {};
  for (const r of staticColorRows) {
    static_colors[r.color_key] = { r: r.r, g: r.g, b: r.b, count: r.count, created_at: r.created_at ?? undefined };
  }
  const staticSoundRows = (batchResults[9].results || []) as StaticSoundRow[];
  const static_sound = staticSoundRows.map((r) => ({
    key: r.sound_key,
    tone: r.tone ?? undefined,
    timbre: r.timbre ?? undefined,
    amplitude: r.amplitude ?? undefined,
    name: r.name ?? undefined,
    count: r.count,
    created_at: r.created_at ?? undefined,
  }));
  // Separate query so for-creation still works before migration 0021 is applied
  let learned_entities: Array<{
    key: string;
    kind: string;
    trajectory?: string;
    bounce: boolean;
    color_hint?: string | null;
    label?: string | null;
    directionality?: string | null;
    count: number;
    name?: string | null;
  }> = [];
  try {
    type EntityRow = {
      profile_key: string;
      kind: string;
      trajectory: string | null;
      bounce: number;
      color_hint: string | null;
      label: string | null;
      directionality: string | null;
      count: number;
      name: string | null;
    };
    const entityResult = await db
      .prepare(
        "SELECT profile_key, kind, trajectory, bounce, color_hint, label, directionality, count, name FROM learned_entities ORDER BY count DESC LIMIT ?"
      )
      .bind(limit)
      .all<EntityRow>();
    learned_entities = (entityResult.results || []).map((r) => ({
      key: r.profile_key,
      kind: r.kind,
      trajectory: r.trajectory ?? undefined,
      bounce: !!r.bounce,
      color_hint: r.color_hint,
      label: r.label,
      directionality: r.directionality,
      count: r.count,
      name: r.name,
    }));
  } catch {
    learned_entities = [];
  }
  const payload = {
    learned_colors: colors,
    learned_motion: motion,
    learned_audio,
    learned_gradient,
    learned_camera,
    learned_entities,
    origin_gradient,
    origin_camera,
    origin_motion,
    interpretation_prompts,
    static_colors,
    static_sound,
  };
  const body = JSON.stringify(payload);
  if (env.MOTION_KV) {
    try {
      await env.MOTION_KV.put(cacheKey, body, { expirationTtl: 180 });
    } catch { /* ignore KV write failure */ }
  }
  return new Response(body, { headers: { "Content-Type": "application/json" } });
  } catch (e) {
    console.error("GET /api/knowledge/for-creation failed:", e);
    return json({ error: "Failed to load for-creation", details: String(e) }, 500);
  }
}


  return null;
}
