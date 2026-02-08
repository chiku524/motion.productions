/**
 * Motion Productions — Cloudflare Worker API
 * Uses: D1 (jobs), R2 (video files), KV (optional cache/config)
 */

export interface Env {
  DB: D1Database;
  VIDEOS: R2Bucket;
  MOTION_KV: KVNamespace;
  ASSETS: Fetcher;
}

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization",
};

function json<T>(data: T, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json", ...corsHeaders },
  });
}

function err(message: string, status = 400) {
  return json({ error: message }, status);
}

function uuid() {
  return crypto.randomUUID();
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    if (request.method === "OPTIONS") return new Response(null, { headers: corsHeaders });

    const url = new URL(request.url);
    const path = url.pathname;

    // Health (API)
    if (path === "/health") {
      return json({ ok: true, service: "motion-productions" });
    }

    // API routes
    if (path.startsWith("/api/")) {
      const apiResponse = await handleApi(request, env, path);
      if (apiResponse) return apiResponse;
    }

    // Static assets (app UI)
    return env.ASSETS.fetch(request);
  },
};

async function handleApi(request: Request, env: Env, path: string): Promise<Response | null> {
  const corsHeaders = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
  };
  const json = <T>(data: T, status = 200) =>
    new Response(JSON.stringify(data), {
      status,
      headers: { "Content-Type": "application/json", ...corsHeaders },
    });
  const err = (message: string, status = 400) =>
    json({ error: message }, status);

  // GET /api/jobs?status=pending — list pending jobs (for generator service)
    if (path === "/api/jobs" && request.method === "GET") {
      const status = new URL(request.url).searchParams.get("status");
      if (status === "pending") {
        const rows = await env.DB.prepare(
          "SELECT id, prompt, duration_seconds, created_at FROM jobs WHERE status = 'pending' ORDER BY created_at ASC"
        )
          .all<{ id: string; prompt: string; duration_seconds: number | null; created_at: string }>();
        return json({ jobs: rows.results || [] });
      }
      return err("status=pending required", 400);
    }

    // POST /api/jobs — create job
    if (path === "/api/jobs" && request.method === "POST") {
      let body: { prompt: string; duration_seconds?: number };
      try {
        body = (await request.json()) as { prompt: string; duration_seconds?: number };
      } catch {
        return err("Invalid JSON");
      }
      const prompt = typeof body.prompt === "string" ? body.prompt.trim() : "";
      if (!prompt) return err("prompt is required");
      const id = uuid();
      const duration_seconds = typeof body.duration_seconds === "number" ? body.duration_seconds : null;
      await env.DB.prepare(
        "INSERT INTO jobs (id, prompt, duration_seconds, status) VALUES (?, ?, ?, 'pending')"
      )
        .bind(id, prompt, duration_seconds ?? null)
        .run();
      return json({ id, prompt, duration_seconds, status: "pending" }, 201);
    }

    // GET /api/jobs/:id — get job (and download URL if completed)
    const jobMatch = path.match(/^\/api\/jobs\/([a-f0-9-]+)$/);
    if (jobMatch && request.method === "GET") {
      const id = jobMatch[1];
      const row = await env.DB.prepare(
        "SELECT id, prompt, duration_seconds, status, r2_key, created_at, updated_at FROM jobs WHERE id = ?"
      )
        .bind(id)
        .first<{
          id: string;
          prompt: string;
          duration_seconds: number | null;
          status: string;
          r2_key: string | null;
          created_at: string;
          updated_at: string;
        }>();
      if (!row) return err("Job not found", 404);
      const out: Record<string, unknown> = {
        id: row.id,
        prompt: row.prompt,
        duration_seconds: row.duration_seconds,
        status: row.status,
        created_at: row.created_at,
        updated_at: row.updated_at,
      };
      if (row.status === "completed" && row.r2_key) {
        const obj = await env.VIDEOS.get(row.r2_key);
        if (obj) {
          out.download_url = `/api/jobs/${id}/download`;
        }
      }
      return json(out);
    }

    // POST /api/jobs/:id/upload — upload video (raw body or multipart)
    const uploadMatch = path.match(/^\/api\/jobs\/([a-f0-9-]+)\/upload$/);
    if (uploadMatch && request.method === "POST") {
      const id = uploadMatch[1];
      const row = await env.DB.prepare("SELECT id, status FROM jobs WHERE id = ?").bind(id).first();
      if (!row) return err("Job not found", 404);
      if ((row as { status: string }).status !== "pending") return err("Job already has video", 400);

      let body: ArrayBuffer;
      let contentType = "video/mp4";
      const ct = request.headers.get("Content-Type") ?? "";
      if (ct.includes("multipart/form-data")) {
        const formData = await request.formData();
        const file = formData.get("file") as File | null;
        if (!file) return err("Missing file in form");
        body = await file.arrayBuffer();
        contentType = file.type || contentType;
      } else {
        body = await request.arrayBuffer();
      }
      if (body.byteLength === 0) return err("Empty body");
      const r2_key = `jobs/${id}/video.mp4`;
      await env.VIDEOS.put(r2_key, body, { httpMetadata: { contentType } });
      await env.DB.prepare(
        "UPDATE jobs SET status = 'completed', r2_key = ?, updated_at = datetime('now') WHERE id = ?"
      )
        .bind(r2_key, id)
        .run();
      return json({ id, status: "completed", download_url: `/api/jobs/${id}/download` });
    }

    // GET /api/jobs/:id/download — stream video from R2
    const downloadMatch = path.match(/^\/api\/jobs\/([a-f0-9-]+)\/download$/);
    if (downloadMatch && request.method === "GET") {
      const id = downloadMatch[1];
      const row = await env.DB.prepare("SELECT r2_key FROM jobs WHERE id = ? AND status = 'completed'")
        .bind(id)
        .first<{ r2_key: string | null }>();
      if (!row?.r2_key) return err("Not found", 404);
      const obj = await env.VIDEOS.get(row.r2_key);
      if (!obj) return err("Video not found", 404);
      return new Response(obj.body, {
        headers: {
          "Content-Type": obj.httpMetadata?.contentType ?? "video/mp4",
          "Content-Length": String(obj.size),
          ...corsHeaders,
        },
      });
    }

    // POST /api/learning — log a run for learning (D1)
    if (path === "/api/learning" && request.method === "POST") {
      let body: { job_id?: string; prompt: string; spec: Record<string, unknown>; analysis: Record<string, unknown> };
      try {
        body = (await request.json()) as typeof body;
      } catch {
        return err("Invalid JSON");
      }
      const prompt = typeof body.prompt === "string" ? body.prompt.trim() : "";
      if (!prompt) return err("prompt is required");
      const spec = body.spec && typeof body.spec === "object" ? body.spec : {};
      const analysis = body.analysis && typeof body.analysis === "object" ? body.analysis : {};
      const jobId = typeof body.job_id === "string" ? body.job_id : null;
      const id = uuid();
      await env.DB.prepare(
        "INSERT INTO learning_runs (id, job_id, prompt, spec_json, analysis_json) VALUES (?, ?, ?, ?, ?)"
      )
        .bind(id, jobId, prompt, JSON.stringify(spec), JSON.stringify(analysis))
        .run();
      await env.MOTION_KV.delete("learning:stats");
      return json({ id, job_id: jobId, status: "logged" }, 201);
    }

    // GET /api/learning/runs — list learning runs (for aggregation/reports)
    if (path === "/api/learning/runs" && request.method === "GET") {
      const limit = Math.min(parseInt(new URL(request.url).searchParams.get("limit") || "100", 10), 500);
      const rows = await env.DB.prepare(
        "SELECT id, job_id, prompt, spec_json, analysis_json, created_at FROM learning_runs ORDER BY created_at DESC LIMIT ?"
      )
        .bind(limit)
        .all<{ id: string; job_id: string | null; prompt: string; spec_json: string; analysis_json: string; created_at: string }>();
      const runs = (rows.results || []).map((r) => ({
        id: r.id,
        job_id: r.job_id,
        prompt: r.prompt,
        spec: JSON.parse(r.spec_json),
        analysis: JSON.parse(r.analysis_json),
        created_at: r.created_at,
      }));
      return json({ runs });
    }

    // POST /api/events — log user interaction for learning
    if (path === "/api/events" && request.method === "POST") {
      let body: { event_type: string; job_id?: string; payload?: Record<string, unknown> };
      try {
        body = (await request.json()) as typeof body;
      } catch {
        return err("Invalid JSON");
      }
      const eventType = typeof body.event_type === "string" ? body.event_type.trim() : "";
      if (!eventType) return err("event_type is required");
      const allowed = ["prompt_submitted", "job_completed", "video_played", "video_abandoned", "download_clicked", "error", "feedback"];
      if (!allowed.includes(eventType)) return err(`event_type must be one of: ${allowed.join(", ")}`);
      const jobId = typeof body.job_id === "string" ? body.job_id : null;
      const payload = body.payload && typeof body.payload === "object" ? body.payload : null;
      const id = uuid();
      await env.DB.prepare(
        "INSERT INTO events (id, event_type, job_id, payload_json) VALUES (?, ?, ?, ?)"
      )
        .bind(id, eventType, jobId, payload ? JSON.stringify(payload) : null)
        .run();
      return json({ id, status: "logged" }, 201);
    }

    // GET /api/events — list events (for learning pipeline)
    if (path === "/api/events" && request.method === "GET") {
      const limit = Math.min(parseInt(new URL(request.url).searchParams.get("limit") || "500", 10), 1000);
      const typeFilter = new URL(request.url).searchParams.get("type");
      let q = "SELECT id, event_type, job_id, payload_json, created_at FROM events ORDER BY created_at DESC LIMIT ?";
      const params: (string | number)[] = [limit];
      if (typeFilter) {
        q = "SELECT id, event_type, job_id, payload_json, created_at FROM events WHERE event_type = ? ORDER BY created_at DESC LIMIT ?";
        params.unshift(typeFilter);
      }
      const rows = await env.DB.prepare(q).bind(...params)
        .all<{ id: string; event_type: string; job_id: string | null; payload_json: string | null; created_at: string }>();
      const events = (rows.results || []).map((r) => ({
        id: r.id,
        event_type: r.event_type,
        job_id: r.job_id,
        payload: r.payload_json ? JSON.parse(r.payload_json) : null,
        created_at: r.created_at,
      }));
      return json({ events });
    }

    // GET /api/knowledge/prompts — distinct prompts from jobs (for automation avoid set)
    if (path === "/api/knowledge/prompts" && request.method === "GET") {
      const limit = Math.min(parseInt(new URL(request.url).searchParams.get("limit") || "500", 10), 1000);
      const rows = await env.DB.prepare(
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

    // GET /api/feedback — list feedback (for learning pipeline)
    if (path === "/api/feedback" && request.method === "GET") {
      const limit = Math.min(parseInt(new URL(request.url).searchParams.get("limit") || "500", 10), 1000);
      const rows = await env.DB.prepare(
        "SELECT f.id, f.job_id, f.rating, f.created_at, j.prompt FROM feedback f JOIN jobs j ON j.id = f.job_id ORDER BY f.created_at DESC LIMIT ?"
      )
        .bind(limit)
        .all<{ id: string; job_id: string; rating: number; created_at: string; prompt: string }>();
      return json({ feedback: rows.results || [] });
    }

    // POST /api/jobs/:id/feedback — rate completed video (1=down, 2=up)
    const feedbackMatch = path.match(/^\/api\/jobs\/([a-f0-9-]+)\/feedback$/);
    if (feedbackMatch && request.method === "POST") {
      const id = feedbackMatch[1];
      let body: { rating: number };
      try {
        body = (await request.json()) as { rating: number };
      } catch {
        return err("Invalid JSON");
      }
      const rating = body.rating === 1 || body.rating === 2 ? body.rating : 0;
      if (rating === 0) return err("rating must be 1 (thumbs down) or 2 (thumbs up)");
      const row = await env.DB.prepare("SELECT id FROM jobs WHERE id = ? AND status = 'completed'").bind(id).first();
      if (!row) return err("Job not found or not completed", 404);
      const fid = uuid();
      await env.DB.prepare(
        "INSERT INTO feedback (id, job_id, rating) VALUES (?, ?, ?) ON CONFLICT(job_id) DO UPDATE SET rating = excluded.rating"
      )
        .bind(fid, id, rating)
        .run();
      await logEvent(env, "feedback", id, { rating });
      return json({ id: fid, rating, status: "saved" }, 201);
    }

    // GET /api/learning/stats — aggregated stats (KV cache, D1 fallback)
    if (path === "/api/learning/stats" && request.method === "GET") {
      const cached = await env.MOTION_KV.get("learning:stats");
      if (cached) return json(JSON.parse(cached));

      const rows = await env.DB.prepare(
        "SELECT prompt, spec_json, analysis_json FROM learning_runs ORDER BY created_at DESC LIMIT 500"
      )
        .all<{ prompt: string; spec_json: string; analysis_json: string }>();
      const report = aggregateLearningRuns(rows.results || []);
      await env.MOTION_KV.put("learning:stats", JSON.stringify(report), { expirationTtl: 300 });
      return json(report);
    }

  return err("Not found", 404);
}

async function logEvent(env: Env, eventType: string, jobId: string | null, payload: Record<string, unknown> | null): Promise<void> {
  const id = crypto.randomUUID();
  await env.DB.prepare("INSERT INTO events (id, event_type, job_id, payload_json) VALUES (?, ?, ?, ?)")
    .bind(id, eventType, jobId, payload ? JSON.stringify(payload) : null)
    .run();
}

function aggregateLearningRuns(
  rows: { prompt: string; spec_json: string; analysis_json: string }[]
): Record<string, unknown> {
  if (rows.length === 0) return { total_runs: 0, by_palette: {}, by_keyword: {}, overall: {} };
  const byPalette: Record<string, { count: number; motion: number[]; brightness: number[] }> = {};
  const byKeyword: Record<string, { count: number; motion: number[]; brightness: number[] }> = {};
  const allMotion: number[] = [];
  const allBrightness: number[] = [];
  const allContrast: number[] = [];

  const words = (s: string) => new Set((s || "").toLowerCase().match(/[a-z]+/g) || []);

  for (const r of rows) {
    const spec = JSON.parse(r.spec_json) as Record<string, unknown>;
    const analysis = JSON.parse(r.analysis_json) as Record<string, unknown>;
    const palette = (spec.palette_name as string) || "default";
    byPalette[palette] = byPalette[palette] || { count: 0, motion: [], brightness: [] };
    byPalette[palette].count++;
    byPalette[palette].motion.push((analysis.motion_level as number) ?? 0);
    byPalette[palette].brightness.push((analysis.mean_brightness as number) ?? 0);

    for (const w of words(r.prompt)) {
      byKeyword[w] = byKeyword[w] || { count: 0, motion: [], brightness: [] };
      byKeyword[w].count++;
      byKeyword[w].motion.push((analysis.motion_level as number) ?? 0);
      byKeyword[w].brightness.push((analysis.mean_brightness as number) ?? 0);
    }
    allMotion.push((analysis.motion_level as number) ?? 0);
    allBrightness.push((analysis.mean_brightness as number) ?? 0);
    allContrast.push((analysis.mean_contrast as number) ?? 0);
  }

  const summarize = (v: { count: number; motion: number[]; brightness: number[] }) => ({
    count: v.count,
    mean_motion_level: v.motion.reduce((a, b) => a + b, 0) / v.motion.length || 0,
    mean_brightness: v.brightness.reduce((a, b) => a + b, 0) / v.brightness.length || 0,
  });

  const reportByPalette: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(byPalette)) reportByPalette[k] = summarize(v);
  const reportByKeyword: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(byKeyword)) reportByKeyword[k] = summarize(v);

  const n = rows.length;
  return {
    total_runs: n,
    by_palette: reportByPalette,
    by_keyword: reportByKeyword,
    overall: {
      mean_motion_level: allMotion.reduce((a, b) => a + b, 0) / n,
      mean_brightness: allBrightness.reduce((a, b) => a + b, 0) / n,
      mean_contrast: allContrast.reduce((a, b) => a + b, 0) / n,
    },
  };
}
