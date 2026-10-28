/**
 * Knowledge discoveries, for-creation, colors, name reserve API routes.
 */
import type { Env } from "../env";
import { getDb } from "../db";
import { json, err, corsHeaders } from "../http";
import { generateUniqueName } from "../naming";
import { acquireDiscoveryLease, releaseDiscoveryLease, type LeaseResult } from "../discoveryLease";
import { writeDiscoveries, type DiscoveriesBody } from "../discoveryWriter";
import { getSnapshot } from "../snapshotCache";
import { isFreeTierLimitError, limitResponse } from "../limits";
import { classifyColorFamily, COLOR_FAMILY_META } from "../colorBrowse";

const FOR_CREATION_SOFT_TTL_SEC = 4 * 3600;

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
// Free-tier Core 4: keep per-request writes small (D1 CPU + 50 queries/request on Free).
if (path === "/api/knowledge/discoveries" && request.method === "POST") {
  let body: DiscoveriesBody;
  try {
    body = (await request.json()) as DiscoveriesBody;
  } catch {
    return err("Invalid JSON");
  }
  // The single-writer KV lease is OPT-IN (DISCOVERY_LEASE=1): it costs 2 KV writes per POST (1,000/day free).
  // Writes are now one batched upsert statement set, so concurrent workers no longer stampede D1.
  let lease: LeaseResult | null = null;
  if (env.DISCOVERY_LEASE === "1") {
    lease = await acquireDiscoveryLease(env);
    if (!lease.ok) {
      const retrySec = Math.ceil(lease.retry_after_ms / 1000);
      return new Response(
        JSON.stringify({ error: "Discovery writer busy", details: "Another worker holds the discoveries write lease", retry_after_ms: lease.retry_after_ms }),
        { status: 429, headers: { "Content-Type": "application/json", "Retry-After": String(Math.max(1, retrySec)), ...corsHeaders } },
      );
    }
  }
  try {
    const out = await writeDiscoveries(env, body);
    return json(out.body, out.status);
  } catch (e) {
    if (isFreeTierLimitError(e)) return limitResponse("POST", { details: String(e) });
    console.error("POST /api/knowledge/discoveries failed:", e);
    return json({ error: "Failed to record discoveries", details: String(e) }, 500);
  } finally {
    if (lease && lease.ok) await releaseDiscoveryLease(env, lease.holder);
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
  // Free-tier: bound static_colors ORDER BY count (large table → CPU 7429).
  const colorScan = Math.min(Math.max(limit * 3, 60), 120);
  // Snapshot: memory -> Cache API -> rarely-written KV. Soft TTL is long because the ORDER BY count queries scan the
  // whole static_colors table (~28k rows each); never invalidated per post. `fresh=1` is rate limited (5 min).
  const cacheKey = `knowledge:for-creation:v2:${limit}:${interpLimit}`;
  const wantFresh = new URL(request.url).searchParams.get("fresh") === "1";
  const snap = await getSnapshot<string>(
    env,
    cacheKey,
    { softTtlSec: FOR_CREATION_SOFT_TTL_SEC, hardTtlSec: 7 * 86400, kvPersistSec: 6 * 3600, bypass: wantFresh, bypassMinIntervalSec: 300 },
    async () => {
  // Single batch reduces D1 round-trips and CPU overhead
  const batchResults = await db.batch([
    db.prepare("SELECT color_key, r, g, b, count, sources_json, name FROM learned_colors ORDER BY count DESC LIMIT ?").bind(limit),
    db.prepare("SELECT profile_key, motion_level, motion_std, motion_trend, motion_direction, motion_rhythm, count, sources_json, name FROM learned_motion ORDER BY count DESC LIMIT ?").bind(limit),
    db.prepare("SELECT domain, inputs_json, output_json, source_prompt, created_at FROM learned_blends WHERE domain = 'audio' ORDER BY rowid DESC LIMIT ?").bind(limit),
    db.prepare("SELECT output_json FROM learned_blends WHERE domain = 'gradient' ORDER BY rowid DESC LIMIT ?").bind(limit),
    db.prepare("SELECT gradient_type FROM learned_gradient ORDER BY count DESC LIMIT ?").bind(limit),
    db.prepare("SELECT output_json FROM learned_blends WHERE domain = 'camera' ORDER BY rowid DESC LIMIT ?").bind(limit),
    db.prepare("SELECT motion_type FROM learned_camera ORDER BY count DESC LIMIT ?").bind(limit),
    db.prepare("SELECT prompt, instruction_json FROM interpretations WHERE status = 'done' AND instruction_json IS NOT NULL ORDER BY rowid DESC LIMIT ?").bind(interpLimit),
    db.prepare("SELECT color_key, r, g, b, name, count, created_at FROM static_colors ORDER BY count DESC LIMIT ?").bind(colorScan),
    db.prepare("SELECT color_key, r, g, b, name, count, created_at FROM static_colors ORDER BY count ASC, created_at DESC LIMIT ?").bind(limit),
    db.prepare("SELECT sound_key, tone, timbre, amplitude, name, count, created_at FROM static_sound WHERE sound_key NOT LIKE 's2.%' ORDER BY count DESC LIMIT ?").bind(Math.min(colorScan, 200)),
    db.prepare("SELECT aspect, entry_key, value, name, count FROM narrative_entries ORDER BY count DESC LIMIT ?").bind(Math.min(colorScan, 200)),
  ]);
  type ColorRow = { color_key: string; r: number; g: number; b: number; count: number; sources_json: string | null; name: string };
  type MotionRow = { profile_key: string; motion_level: number; motion_std: number; motion_trend: string; motion_direction: string | null; motion_rhythm: string | null; count: number; sources_json: string | null; name: string | null };
  type AudioRow = { domain: string; inputs_json: string; output_json: string; source_prompt: string | null; created_at: string };
  type OutputRow = { output_json: string };
  type GradientRow = { gradient_type: string };
  type CameraRow = { motion_type: string };
  type InterpRow = { prompt: string; instruction_json: string };
  type StaticColorRow = { color_key: string; r: number; g: number; b: number; name: string | null; count: number; created_at: string | null };
  type StaticSoundRow = { sound_key: string; tone: string | null; timbre: string | null; amplitude: number | null; name: string | null; count: number; created_at: string | null };
  type NarrativeRow = { aspect: string; entry_key: string; value: string | null; name: string | null; count: number };
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
    motion_direction: r.motion_direction ?? "none",
    motion_rhythm: r.motion_rhythm ?? "steady",
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
  // Stratify by hue family so for-creation matches explorer browse diversity (not only top-count colors).
  const byFamily = new Map<string, StaticColorRow[]>();
  for (const r of staticColorRows) {
    const fam = classifyColorFamily(r.r, r.g, r.b);
    const list = byFamily.get(fam) || [];
    list.push(r);
    byFamily.set(fam, list);
  }
  const stratified: StaticColorRow[] = [];
  const familyOrder = COLOR_FAMILY_META.map((m) => m.id);
  let guard = 0;
  while (stratified.length < limit && guard < colorScan + 12) {
    let addedRound = false;
    for (const fam of familyOrder) {
      const list = byFamily.get(fam);
      if (!list || !list.length) continue;
      stratified.push(list.shift()!);
      addedRound = true;
      if (stratified.length >= limit) break;
    }
    if (!addedRound) break;
    guard++;
  }
  // Fill remainder by original popularity if families exhausted unevenly
  if (stratified.length < limit) {
    const used = new Set(stratified.map((r) => r.color_key));
    for (const r of staticColorRows) {
      if (used.has(r.color_key)) continue;
      stratified.push(r);
      if (stratified.length >= limit) break;
    }
  }
  const static_colors: Record<string, { r: number; g: number; b: number; name?: string; count?: number; created_at?: string; family?: string }> = {};
  for (const r of stratified) {
    static_colors[r.color_key] = {
      r: r.r,
      g: r.g,
      b: r.b,
      name: r.name ?? undefined,
      count: r.count,
      created_at: r.created_at ?? undefined,
      family: classifyColorFamily(r.r, r.g, r.b),
    };
  }
  const underfilledRows = (batchResults[9].results || []) as StaticColorRow[];
  for (const r of underfilledRows) {
    if (static_colors[r.color_key]) continue;
    static_colors[r.color_key] = {
      r: r.r,
      g: r.g,
      b: r.b,
      name: r.name ?? undefined,
      count: r.count,
      created_at: r.created_at ?? undefined,
      family: classifyColorFamily(r.r, r.g, r.b),
    };
  }
  const color_by_name: Record<string, { key: string; r: number; g: number; b: number }> = {};
  for (const [key, data] of Object.entries(static_colors)) {
    const nm = (data.name || "").trim().toLowerCase();
    if (nm && !color_by_name[nm]) {
      color_by_name[nm] = { key, r: data.r, g: data.g, b: data.b };
    }
  }
  const staticSoundRows = (batchResults[10].results || []) as StaticSoundRow[];
  const static_sound = staticSoundRows.map((r) => ({
    key: r.sound_key,
    tone: r.tone ?? undefined,
    timbre: r.timbre ?? undefined,
    amplitude: r.amplitude ?? undefined,
    name: r.name ?? undefined,
    count: r.count,
    created_at: r.created_at ?? undefined,
  }));
  const narrativeRows = (batchResults[11].results || []) as NarrativeRow[];
  const narrative: Record<string, Array<{ key: string; value?: string; name?: string; count: number }>> = {};
  // Cap per aspect so one hot aspect cannot crowd out others (explorer/creation alignment).
  const perAspectCap = Math.max(4, Math.ceil(limit / 7));
  for (const r of narrativeRows) {
    const aspect = (r.aspect || "").trim() || "unknown";
    if (!narrative[aspect]) narrative[aspect] = [];
    if (narrative[aspect].length >= perAspectCap) continue;
    narrative[aspect].push({
      key: r.entry_key,
      value: r.value ?? undefined,
      name: r.name ?? undefined,
      count: r.count,
    });
  }
  let learned_audio_semantic: Array<{ key: string; role: string; name: string; count: number }> = [];
  try {
    type AudioSemanticRow = { profile_key: string; role: string | null; name: string | null; count: number };
    const asResult = await db
      .prepare("SELECT profile_key, role, name, count FROM learned_audio_semantic ORDER BY count DESC LIMIT ?")
      .bind(limit)
      .all<AudioSemanticRow>();
    learned_audio_semantic = (asResult.results || []).map((r) => ({
      key: r.profile_key,
      role: r.role || "ambient",
      name: r.name || r.profile_key,
      count: r.count,
    }));
  } catch {
    learned_audio_semantic = [];
  }
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
      entity_json: string | null;
    };
    const entityResult = await db
      .prepare(
        "SELECT profile_key, kind, trajectory, bounce, color_hint, label, directionality, count, name, entity_json FROM learned_entities ORDER BY count DESC LIMIT ?"
      )
      .bind(limit)
      .all<EntityRow>();
    learned_entities = (entityResult.results || []).map((r) => {
      let entity_json: Record<string, unknown> | undefined;
      if (r.entity_json) {
        try {
          entity_json = JSON.parse(r.entity_json) as Record<string, unknown>;
        } catch {
          entity_json = undefined;
        }
      }
      return {
        key: r.profile_key,
        kind: r.kind,
        trajectory: r.trajectory ?? undefined,
        bounce: !!r.bounce,
        color_hint: r.color_hint,
        label: r.label,
        directionality: r.directionality,
        count: r.count,
        name: r.name,
        entity_json,
        form: entity_json && typeof entity_json.form === "object" ? entity_json.form : undefined,
      };
    });
  } catch {
    learned_entities = [];
  }
  const payload = {
    learned_colors: colors,
    learned_motion: motion,
    learned_audio,
    learned_audio_semantic,
    learned_gradient,
    learned_camera,
    learned_entities,
    origin_gradient,
    origin_camera,
    origin_motion,
    interpretation_prompts,
    static_colors,
    color_by_name,
    static_sound,
    narrative,
  };
  return JSON.stringify(payload);
    },
  );
  return new Response(snap.value, {
    headers: { "Content-Type": "application/json", "X-Cache": snap.source === "built" ? "MISS" : "HIT", ...(snap.degraded ? { "X-Degraded": "free_tier_limit" } : {}) },
  });
  } catch (e) {
    if (isFreeTierLimitError(e)) {
      // No stale copy anywhere yet: answer 200 with an empty-but-shaped payload so loops keep running.
      return limitResponse("GET", { learned_colors: {}, learned_motion: [], learned_audio: [], learned_audio_semantic: [], learned_gradient: [], learned_camera: [], learned_entities: [], interpretation_prompts: [], static_colors: [], static_sound: [], narrative: {} });
    }
    console.error("GET /api/knowledge/for-creation failed:", e);
    return json({ error: "Failed to load for-creation", details: String(e) }, 500);
  }
}


  return null;
}
