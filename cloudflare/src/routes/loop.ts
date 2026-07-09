/**
 * Loop state/config/status/progress/diagnostics + metrics API routes.
 */
import type { Env } from "../env";
import { getDb } from "../db";
import { json, err, corsHeaders } from "../http";
import { COLOR_PRIMARIES_FOR_API } from "../colorPrimaries.generated";
import {
  STATIC_COLOR_ESTIMATED_CELLS,
  NARRATIVE_ORIGIN_SIZES,
  SOUND_ORIGIN_PRIMARIES,
} from "../registryConstants.generated";

export async function handleLoopRoutes(
  request: Request,
  env: Env,
  path: string,
): Promise<Response | null> {
  const db = getDb(env);

// GET /api/loop/state — load loop state (for worker continuity across restarts)
if (path === "/api/loop/state" && request.method === "GET") {
  const kv = env.MOTION_KV;
  if (!kv) return json({ error: "Loop state unavailable: KV not bound", details: "MOTION_KV undefined" }, 503);
  try {
    const raw = await kv.get("loop_state");
    const state = raw ? (JSON.parse(raw) as Record<string, unknown>) : {};
    return json({ state });
  } catch (e) {
    return json({ error: "Failed to load loop state", details: String(e) }, 500);
  }
}

// POST /api/loop/state — save loop state (good_prompts, recent_prompts, run_count)
if (path === "/api/loop/state" && request.method === "POST") {
  const kv = env.MOTION_KV;
  if (!kv) return json({ error: "Loop state unavailable: KV not bound", details: "MOTION_KV undefined" }, 503);
  let body: { state?: Record<string, unknown> };
  try {
    body = (await request.json()) as { state?: Record<string, unknown> };
  } catch {
    return err("Invalid JSON");
  }
  const raw = body.state && typeof body.state === "object" ? body.state : {};
  // Sanitize: only allow safe JSON; KV has 1 write/sec limit per key — client should space saves
  const state: Record<string, unknown> = {};
  state.run_count = typeof raw.run_count === "number" && Number.isFinite(raw.run_count) ? Math.floor(raw.run_count) : 0;
  const incomingGood = Array.isArray(raw.good_prompts)
    ? raw.good_prompts.map((p) => String(p ?? "").slice(0, 500)).filter(Boolean)
    : [];
  // Merge with existing KV good_prompts so gallery thumbs-up promotions survive worker state saves
  let existingGood: string[] = [];
  try {
    const prevRaw = await kv.get("loop_state");
    if (prevRaw) {
      const prev = JSON.parse(prevRaw) as { good_prompts?: unknown };
      if (Array.isArray(prev.good_prompts)) {
        existingGood = prev.good_prompts.map((p) => String(p ?? "").slice(0, 500)).filter(Boolean);
      }
    }
  } catch {
    /* ignore */
  }
  const mergedGood = [...existingGood];
  for (const p of incomingGood) {
    if (!mergedGood.includes(p)) mergedGood.push(p);
  }
  state.good_prompts = mergedGood.slice(-200);
  state.recent_prompts = Array.isArray(raw.recent_prompts)
    ? raw.recent_prompts.slice(-200).map((p) => String(p ?? "").slice(0, 500))
    : [];
  state.duration_base = typeof raw.duration_base === "number" && Number.isFinite(raw.duration_base) ? raw.duration_base : 6;
  state.exploit_count = typeof raw.exploit_count === "number" && Number.isFinite(raw.exploit_count) ? Math.floor(raw.exploit_count) : 0;
  state.explore_count = typeof raw.explore_count === "number" && Number.isFinite(raw.explore_count) ? Math.floor(raw.explore_count) : 0;
  if (typeof raw.last_run_at === "string") state.last_run_at = raw.last_run_at.slice(0, 50);
  if (typeof raw.last_prompt === "string") state.last_prompt = raw.last_prompt.slice(0, 100);
  if (typeof raw.last_job_id === "string") state.last_job_id = raw.last_job_id.slice(0, 80);
  try {
    const payload = JSON.stringify(state);
    if (payload.length > 25 * 1024 * 1024) return json({ error: "State too large for KV (max 25MB)" }, 413);
    await kv.put("loop_state", payload);
    return json({ ok: true });
  } catch (e) {
    const msg = String(e);
    const isRateLimit = msg.toLowerCase().includes("rate") || msg.toLowerCase().includes("limit");
    const status = isRateLimit ? 429 : 500;
    const headers: Record<string, string> = { "Content-Type": "application/json", ...corsHeaders };
    if (isRateLimit) headers["Retry-After"] = "2";
    return new Response(JSON.stringify({ error: "Failed to save loop state", details: msg }), {
      status,
      headers,
    });
  }
}

// GET /api/loop/config — user-controlled loop config (enabled, delay, exploit_ratio, duration_seconds)
if (path === "/api/loop/config" && request.method === "GET") {
  const kv = env.MOTION_KV;
  if (!kv) return json({ error: "Loop config unavailable: KV not bound", details: "MOTION_KV undefined" }, 500);
  try {
    const raw = await kv.get("loop_config");
    let config: { enabled?: boolean; delay_seconds?: number; exploit_ratio?: number; duration_seconds?: number } = { enabled: true, delay_seconds: 30, exploit_ratio: 0.7, duration_seconds: 5 };
    if (raw && raw.length > 0) {
      try {
        config = JSON.parse(raw) as typeof config;
      } catch {
        /* use defaults */
      }
    }
    const duration = typeof config.duration_seconds === "number" ? config.duration_seconds : 5;
    const ds = typeof config.delay_seconds === "number" ? config.delay_seconds : 30;
    return json({
      enabled: config.enabled !== false,
      delay_seconds: Math.max(3, ds),
      exploit_ratio: typeof config.exploit_ratio === "number" ? config.exploit_ratio : 0.7,
      duration_seconds: Math.max(1, Math.min(60, duration)),
    });
  } catch (e) {
    return json({ error: "Failed to load loop config", details: String(e) }, 500);
  }
}

// POST /api/loop/config — update loop config (controls background workers)
if (path === "/api/loop/config" && request.method === "POST") {
  let body: { enabled?: boolean; delay_seconds?: number; exploit_ratio?: number; duration_seconds?: number };
  try {
    body = (await request.json()) as typeof body;
  } catch {
    return err("Invalid JSON");
  }
  const kv = env.MOTION_KV;
  if (!kv) {
    return json({ error: "Loop config unavailable: KV namespace not bound. Check Worker bindings (MOTION_KV).", details: "MOTION_KV undefined" }, 500);
  }
  try {
    const raw = await kv.get("loop_config");
    let current: Record<string, unknown> = {};
    if (raw && raw.length > 0) {
      try {
        current = JSON.parse(raw) as Record<string, unknown>;
      } catch {
        current = {};
      }
    }
    if (typeof body.enabled === "boolean") current.enabled = body.enabled;
    if (typeof body.delay_seconds === "number") current.delay_seconds = Math.max(3, Math.min(600, body.delay_seconds));
    if (typeof body.exploit_ratio === "number") current.exploit_ratio = Math.max(0, Math.min(1, body.exploit_ratio));
    if (typeof body.duration_seconds === "number") current.duration_seconds = Math.max(1, Math.min(60, body.duration_seconds));
    await kv.put("loop_config", JSON.stringify(current));
    return json({ ok: true, config: current });
  } catch (e) {
    return json({ error: "Failed to save loop config", details: String(e) }, 500);
  }
}

// GET /api/loop/status — config + state + recent activity for webapp display
if (path === "/api/loop/status" && request.method === "GET") {
  const kv = env.MOTION_KV;
  if (!kv) return json({ error: "Loop status unavailable: KV not bound", details: "MOTION_KV undefined" }, 500);
  try {
    const configRaw = await kv.get("loop_config");
    let config: { enabled?: boolean; delay_seconds?: number; exploit_ratio?: number; duration_seconds?: number } = { enabled: true, delay_seconds: 30, exploit_ratio: 0.7, duration_seconds: 5 };
    if (configRaw && configRaw.length > 0) {
      try {
        config = JSON.parse(configRaw) as typeof config;
      } catch {
        /* use defaults */
      }
    }
    const duration = typeof config.duration_seconds === "number" ? config.duration_seconds : 5;
    const stateRaw = await kv.get("loop_state");
    let state: Record<string, unknown> = {};
    if (stateRaw && stateRaw.length > 0) {
      try {
        state = JSON.parse(stateRaw) as Record<string, unknown>;
      } catch {
        /* use empty */
      }
    }
    const rows = await db.prepare(
      "SELECT id, prompt, duration_seconds, updated_at, workflow_type FROM jobs WHERE status = 'completed' AND r2_key IS NOT NULL ORDER BY updated_at DESC LIMIT 10"
    )
      .all<{ id: string; prompt: string; duration_seconds: number | null; updated_at: string; workflow_type: string | null }>();
    const recent_runs = (rows.results || []).map((r) => ({
      id: r.id,
      prompt: (r.prompt || "").slice(0, 60) + ((r.prompt?.length ?? 0) > 60 ? "…" : ""),
      duration_seconds: r.duration_seconds,
      updated_at: r.updated_at,
      workflow_type: r.workflow_type ?? undefined,
      download_url: `/api/jobs/${r.id}/download`,
    }));
    return json({
      config: {
        enabled: config.enabled !== false,
        delay_seconds: typeof config.delay_seconds === "number" ? config.delay_seconds : 30,
        exploit_ratio: typeof config.exploit_ratio === "number" ? config.exploit_ratio : 0.7,
        duration_seconds: Math.max(1, Math.min(60, duration)),
      },
      run_count: typeof state.run_count === "number" ? state.run_count : 0,
      good_prompts_count: Array.isArray(state.good_prompts) ? state.good_prompts.length : 0,
      last_run_at: state.last_run_at ?? null,
      last_prompt: state.last_prompt ?? null,
      last_job_id: state.last_job_id ?? null,
      recent_runs,
    });
  } catch (e) {
    return json({ error: "Failed to load loop status", details: String(e) }, 500);
  }
}

// GET /api/loop/progress — learning precision (runs with growth in last N)
if (path === "/api/loop/progress" && request.method === "GET") {
  const last = Math.min(parseInt(new URL(request.url).searchParams.get("last") || "20", 10), 100);
  const progressCacheKey = `loop:progress:${last}`;
  if (env.MOTION_KV) {
    const cached = await env.MOTION_KV.get(progressCacheKey);
    if (cached) return new Response(cached, { headers: { "Content-Type": "application/json", "X-Cache": "HIT" } });
  }
  const completed = await db.prepare(
    "SELECT id FROM jobs WHERE status = 'completed' AND r2_key IS NOT NULL ORDER BY updated_at DESC LIMIT ?"
  ).bind(last).all<{ id: string }>();
  const ids = (completed.results || []).map((r) => r.id);
  let withLearning = 0;
  if (ids.length > 0) {
    const placeholders = ids.map(() => "?").join(",");
    const r = await db.prepare(
      `SELECT COUNT(DISTINCT job_id) as c FROM learning_runs WHERE job_id IN (${placeholders})`
    ).bind(...ids).first<{ c: number }>();
    withLearning = r?.c ?? 0;
  }
  const totalRuns = ids.length;
  const precision = totalRuns > 0 ? Math.round((withLearning / totalRuns) * 100) : 0;
  let withDiscovery = 0;
  if (ids.length > 0) {
    try {
      const placeholders = ids.map(() => "?").join(",");
      const dr = await db.prepare(
        `SELECT COUNT(DISTINCT job_id) as c FROM discovery_runs WHERE job_id IN (${placeholders})`
      ).bind(...ids).first<{ c: number }>();
      withDiscovery = dr?.c ?? 0;
    } catch {
      withDiscovery = 0;
    }
  }
  const discoveryRate = totalRuns > 0 ? Math.round((withDiscovery / totalRuns) * 100) : 0;

  // Exploit / explore counts from loop state (KV) for export and monitoring
  let exploit_count = 0;
  let explore_count = 0;
  try {
    if (env.MOTION_KV) {
      const stateRaw = await env.MOTION_KV.get("loop_state");
      if (stateRaw) {
        const loopState = JSON.parse(stateRaw) as Record<string, unknown>;
        if (typeof loopState.exploit_count === "number" && Number.isFinite(loopState.exploit_count))
          exploit_count = Math.floor(loopState.exploit_count);
        if (typeof loopState.explore_count === "number" && Number.isFinite(loopState.explore_count))
          explore_count = Math.floor(loopState.explore_count);
      }
    }
  } catch {
    /* optional */
  }

  // Repetition score: fraction of total count in top 20 entries (0–1). High = few entries dominate.
  let repetitionScore: number | null = null;
  try {
    const totalMotion = await db.prepare("SELECT COALESCE(SUM(count), 0) as s FROM learned_motion").first<{ s: number }>();
    const topMotion = await db.prepare(
      "SELECT SUM(c) as s FROM (SELECT count as c FROM learned_motion ORDER BY count DESC LIMIT 20)"
    ).first<{ s: number }>();
    const total = totalMotion?.s ?? 0;
    const top = topMotion?.s ?? 0;
    if (total > 0 && top > 0) {
      repetitionScore = Math.round((top / total) * 100) / 100;
    }
  } catch {
    /* learned_motion may not exist */
  }

  // Lightweight coverage snapshot for UI and export (avoids separate /api/registries/coverage call)
  let coverage_snapshot: {
    static_colors_coverage_pct?: number;
    narrative_min_coverage_pct?: number;
    static_sound_coverage_pct?: number;
    plots_coverage_pct?: number;
    style_coverage_pct?: number;
    narrative_plots_style_min_coverage_pct?: number;
    primitive_color_catalog_size?: number;
  } | null = null;
  try {
    const sc = await db.prepare("SELECT COUNT(*) as c FROM static_colors").first<{ c: number }>();
    const staticCount = sc?.c ?? 0;
    const staticCells = STATIC_COLOR_ESTIMATED_CELLS;
    const staticPct = staticCells > 0 ? Math.round((100 * staticCount) / staticCells * 100) / 100 : 0;
    const narrativeSizes = NARRATIVE_ORIGIN_SIZES;
    const aspects = Object.keys(narrativeSizes);
    let minNarrativePct = 100;
    for (const aspect of aspects) {
      const r = await db.prepare("SELECT COUNT(DISTINCT entry_key) as c FROM narrative_entries WHERE aspect = ?").bind(aspect).first<{ c: number }>();
      const count = r?.c ?? 0;
      const size = narrativeSizes[aspect] ?? 1;
      const pct = size > 0 ? (100 * count) / size : 100;
      if (pct < minNarrativePct) minNarrativePct = pct;
    }
    minNarrativePct = Math.round(minNarrativePct * 100) / 100;
    let staticSoundPct: number | undefined;
    try {
      // Match /api/registries/coverage: % of SOUND_ORIGIN_PRIMARIES touched in depth_breakdown.
      const rows = await db.prepare("SELECT depth_breakdown_json FROM static_sound LIMIT 500")
        .all<{ depth_breakdown_json: string | null }>();
      const present = new Set<string>();
      for (const row of rows.results || []) {
        if (!row.depth_breakdown_json) continue;
        try {
          const d = JSON.parse(row.depth_breakdown_json) as Record<string, unknown>;
          const oc = d.origin_noises as Record<string, unknown> | undefined;
          if (oc && typeof oc === "object") {
            for (const k of Object.keys(oc)) present.add(k.toLowerCase());
          }
          for (const k of Object.keys(d)) {
            if (k !== "origin_noises" && typeof d[k] === "number") present.add(k.toLowerCase());
          }
        } catch { /* ignore */ }
      }
      const hit = SOUND_ORIGIN_PRIMARIES.filter((p) => present.has(p)).length;
      staticSoundPct = SOUND_ORIGIN_PRIMARIES.length
        ? Math.round((100 * hit) / SOUND_ORIGIN_PRIMARIES.length * 100) / 100
        : 0;
    } catch {
      /* static_sound may not exist */
    }
    let plotsPct = 0;
    let stylePct = 0;
    try {
      const pr = await db.prepare("SELECT COUNT(DISTINCT entry_key) as c FROM narrative_entries WHERE aspect = 'plots'").first<{ c: number }>();
      const sr = await db.prepare("SELECT COUNT(DISTINCT entry_key) as c FROM narrative_entries WHERE aspect = 'style'").first<{ c: number }>();
      const plotsSize = narrativeSizes.plots || 4;
      const styleSize = narrativeSizes.style || 11;
      plotsPct = pr?.c != null ? Math.round((100 * pr.c) / plotsSize * 100) / 100 : 0;
      stylePct = sr?.c != null ? Math.round((100 * sr.c) / styleSize * 100) / 100 : 0;
    } catch {
      /* optional */
    }
    coverage_snapshot = {
      static_colors_coverage_pct: staticPct,
      narrative_min_coverage_pct: minNarrativePct,
      plots_coverage_pct: Math.min(100, plotsPct),
      style_coverage_pct: Math.min(100, stylePct),
      narrative_plots_style_min_coverage_pct: Math.min(100, plotsPct, stylePct),
      primitive_color_catalog_size: COLOR_PRIMARIES_FOR_API.length,
      ...(staticSoundPct !== undefined ? { static_sound_coverage_pct: staticSoundPct } : {}),
    };
  } catch {
    /* optional */
  }

  const progressPayload = {
    last_n: last,
    total_runs: totalRuns,
    runs_with_learning: withLearning,
    precision_pct: precision,
    target_pct: 95,
    runs_with_discovery: withDiscovery,
    discovery_rate_pct: discoveryRate,
    repetition_score: repetitionScore,
    coverage_snapshot: coverage_snapshot ?? undefined,
    exploit_count,
    explore_count,
  };
  const progressBody = JSON.stringify(progressPayload);
  if (env.MOTION_KV) {
    try {
      await env.MOTION_KV.put(progressCacheKey, progressBody, { expirationTtl: 120 });
    } catch { /* ignore KV write failure */ }
  }
  return new Response(progressBody, { headers: { "Content-Type": "application/json" } });
}

// GET /api/metrics — Prometheus-compatible metrics for dashboards
if (path === "/api/metrics" && request.method === "GET") {
  try {
    const last = 20;
    const completed = await db.prepare(
      "SELECT id FROM jobs WHERE status = 'completed' AND r2_key IS NOT NULL ORDER BY updated_at DESC LIMIT ?"
    ).bind(last).all<{ id: string }>();
    const ids = (completed.results || []).map((r) => r.id);
    let withLearning = 0;
    let withDiscovery = 0;
    if (ids.length > 0) {
      const ph = ids.map(() => "?").join(",");
      const lr = await db.prepare(`SELECT COUNT(DISTINCT job_id) as c FROM learning_runs WHERE job_id IN (${ph})`).bind(...ids).first<{ c: number }>();
      withLearning = lr?.c ?? 0;
      try {
        const dr = await db.prepare(`SELECT COUNT(DISTINCT job_id) as c FROM discovery_runs WHERE job_id IN (${ph})`).bind(...ids).first<{ c: number }>();
        withDiscovery = dr?.c ?? 0;
      } catch { /* discovery_runs may not exist */ }
    }
    const totalRuns = ids.length;
    const precision = totalRuns > 0 ? (withLearning / totalRuns) * 100 : 0;
    const discoveryRate = totalRuns > 0 ? (withDiscovery / totalRuns) * 100 : 0;
    const jobCount = await db.prepare("SELECT COUNT(*) as c FROM jobs WHERE status = 'completed'").first<{ c: number }>();
    const lines = [
      "# HELP motion_productions_total_runs Completed jobs in last N",
      "# TYPE motion_productions_total_runs gauge",
      `motion_productions_total_runs{last="${last}"} ${totalRuns}`,
      "# HELP motion_productions_precision_pct Runs with learning (%)",
      "# TYPE motion_productions_precision_pct gauge",
      `motion_productions_precision_pct ${precision}`,
      "# HELP motion_productions_discovery_rate_pct Runs with discovery (%)",
      "# TYPE motion_productions_discovery_rate_pct gauge",
      `motion_productions_discovery_rate_pct ${discoveryRate}`,
      "# HELP motion_productions_jobs_total Total completed jobs",
      "# TYPE motion_productions_jobs_total gauge",
      `motion_productions_jobs_total ${jobCount?.c ?? 0}`,
    ];
    return new Response(lines.join("\n") + "\n", {
      headers: { "Content-Type": "text/plain; charset=utf-8", ...corsHeaders },
    });
  } catch (e) {
    return json({ error: "Metrics failed", details: String(e) }, 500);
  }
}

// GET /api/loop/diagnostics — per-job has_learning / has_discovery for debugging precision gap
if (path === "/api/loop/diagnostics" && request.method === "GET") {
  const last = Math.min(parseInt(new URL(request.url).searchParams.get("last") || "20", 10), 50);
  const completed = await db.prepare(
    "SELECT id, prompt, created_at FROM jobs WHERE status = 'completed' AND r2_key IS NOT NULL ORDER BY updated_at DESC LIMIT ?"
  ).bind(last).all<{ id: string; prompt: string; created_at: string }>();
  const rows = completed.results || [];
  const ids = rows.map((r) => r.id);
  const learningSet = new Set<string>();
  const discoverySet = new Set<string>();
  if (ids.length > 0) {
    const placeholders = ids.map(() => "?").join(",");
    const lr = await db.prepare(`SELECT job_id FROM learning_runs WHERE job_id IN (${placeholders})`).bind(...ids).all<{ job_id: string }>();
    (lr.results || []).forEach((r) => { if (r.job_id) learningSet.add(r.job_id); });
    try {
      const dr = await db.prepare(`SELECT job_id FROM discovery_runs WHERE job_id IN (${placeholders})`).bind(...ids).all<{ job_id: string }>();
      (dr.results || []).forEach((r) => { if (r.job_id) discoverySet.add(r.job_id); });
    } catch { /* discovery_runs may not exist */ }
  }
  const jobs = rows.map((r) => ({
    job_id: r.id,
    prompt_preview: (r.prompt || "").slice(0, 50),
    has_learning: learningSet.has(r.id),
    has_discovery: discoverySet.has(r.id),
  }));
  const missing_learning = jobs.filter((j) => !j.has_learning).length;
  const missing_discovery = jobs.filter((j) => !j.has_discovery).length;
  return json({
    last_n: last,
    jobs,
    summary: {
      missing_learning,
      missing_discovery,
      hint:
      missing_learning > 0 || missing_discovery > 0
        ? "Missing learning: POST /api/learning may have failed or job completed via different path. Missing discovery: POST /api/knowledge/discoveries with job_id may have failed or path did not pass job_id."
        : null,
    },
  });
}

  return null;
}
