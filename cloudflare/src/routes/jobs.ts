/**
 * Jobs, learning, events, feedback API routes.
 */
import type { Env } from "../env";
import { getDb } from "../db";
import { json, err, uuid, corsHeaders } from "../http";
import { aggregateLearningRuns, logEvent } from "../naming";

export async function handleJobsRoutes(
  request: Request,
  env: Env,
  path: string,
): Promise<Response | null> {
  const db = getDb(env);

  // GET /api/jobs?status=pending|completed — list jobs (pending for worker; completed for library)
if (path === "/api/jobs" && request.method === "GET") {
  const url = new URL(request.url);
  const status = url.searchParams.get("status");
  const limit = Math.min(parseInt(url.searchParams.get("limit") ?? "24", 10) || 24, 100);
  if (status === "pending") {
    const rows = await db.prepare(
      "SELECT id, prompt, duration_seconds, created_at FROM jobs WHERE status = 'pending' ORDER BY created_at ASC LIMIT ?"
    )
      .bind(limit)
      .all<{ id: string; prompt: string; duration_seconds: number | null; created_at: string }>();
    return json({ jobs: rows.results || [] });
  }
  if (status === "completed") {
    const maxDur = url.searchParams.get("max_duration");
    const minDur = url.searchParams.get("min_duration");
    const ratingFilter = url.searchParams.get("rating"); // "2" = liked only
    const maxD = maxDur != null ? parseFloat(maxDur) : null;
    const minD = minDur != null ? parseFloat(minDur) : null;
    const likedOnly = ratingFilter === "2" || ratingFilter === "up";
    let sql = likedOnly
      ? `SELECT j.id, j.prompt, j.duration_seconds, j.created_at, j.updated_at, j.workflow_type
         FROM jobs j
         INNER JOIN feedback f ON f.job_id = j.id AND f.rating = 2
         WHERE j.status = 'completed' AND j.r2_key IS NOT NULL`
      : "SELECT id, prompt, duration_seconds, created_at, updated_at, workflow_type FROM jobs WHERE status = 'completed' AND r2_key IS NOT NULL";
    const binds: (string | number)[] = [];
    const durCol = likedOnly ? "j.duration_seconds" : "duration_seconds";
    const orderCol = likedOnly ? "j.updated_at" : "updated_at";
    if (minD != null && !Number.isNaN(minD)) {
      sql += ` AND ${durCol} IS NOT NULL AND ${durCol} >= ?`;
      binds.push(minD);
    }
    if (maxD != null && !Number.isNaN(maxD)) {
      sql += ` AND ${durCol} IS NOT NULL AND ${durCol} <= ?`;
      binds.push(maxD);
    }
    sql += ` ORDER BY ${orderCol} DESC LIMIT ?`;
    binds.push(limit);
    const stmt = db.prepare(sql);
    const rows = await stmt
      .bind(...binds)
      .all<{ id: string; prompt: string; duration_seconds: number | null; created_at: string; updated_at: string; workflow_type: string | null }>();
    const jobs = (rows.results || []).map((r) => ({
      id: r.id,
      prompt: r.prompt,
      duration_seconds: r.duration_seconds,
      created_at: r.created_at,
      updated_at: r.updated_at,
      workflow_type: r.workflow_type ?? undefined,
      download_url: `/api/jobs/${r.id}/download`,
      liked: likedOnly ? true : undefined,
    }));
    return json({ jobs });
  }
  return err("status=pending or status=completed required", 400);
}

// POST /api/jobs — create job (optional workflow_type: explorer | exploiter | main | web)
if (path === "/api/jobs" && request.method === "POST") {
  let body: { prompt: string; duration_seconds?: number; workflow_type?: string };
  try {
    body = (await request.json()) as { prompt: string; duration_seconds?: number; workflow_type?: string };
  } catch {
    return err("Invalid JSON");
  }
  const prompt = typeof body.prompt === "string" ? body.prompt.trim() : "";
  if (!prompt) return err("prompt is required");
  const id = uuid();
  const duration_seconds = typeof body.duration_seconds === "number" ? body.duration_seconds : null;
  const workflow_type = typeof body.workflow_type === "string" && /^(explorer|exploiter|main|web)$/.test(body.workflow_type) ? body.workflow_type : null;
  await db.prepare(
    "INSERT INTO jobs (id, prompt, duration_seconds, status, workflow_type) VALUES (?, ?, ?, 'pending', ?)"
  )
    .bind(id, prompt, duration_seconds ?? null, workflow_type)
    .run();
  return json({ id, prompt, duration_seconds, workflow_type: workflow_type ?? undefined, status: "pending" }, 201);
}

// GET /api/jobs/:id — get job (and download URL if completed)
const jobMatch = path.match(/^\/api\/jobs\/([a-f0-9-]+)$/);
if (jobMatch && request.method === "GET") {
  const id = jobMatch[1];
  const row = await db.prepare(
    "SELECT id, prompt, duration_seconds, status, r2_key, created_at, updated_at, workflow_type FROM jobs WHERE id = ?"
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
      workflow_type: string | null;
    }>();
  if (!row) return err("Job not found", 404);
  const out: Record<string, unknown> = {
    id: row.id,
    prompt: row.prompt,
    duration_seconds: row.duration_seconds,
    status: row.status,
    created_at: row.created_at,
    updated_at: row.updated_at,
    workflow_type: row.workflow_type ?? undefined,
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
  const row = await db.prepare("SELECT id, status FROM jobs WHERE id = ?").bind(id).first();
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
  await db.prepare(
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
  const row = await db.prepare("SELECT r2_key FROM jobs WHERE id = ? AND status = 'completed'")
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
  await db.prepare(
    "INSERT INTO learning_runs (id, job_id, prompt, spec_json, analysis_json) VALUES (?, ?, ?, ?, ?)"
  )
    .bind(id, jobId, prompt, JSON.stringify(spec), JSON.stringify(analysis))
    .run();
  // Do not use KV delete (free tier limit). Stats cache expires via TTL; GET recomputes when stale.
  return json({ id, job_id: jobId, status: "logged" }, 201);
}

// GET /api/learning/runs — list learning runs (for aggregation/reports)
if (path === "/api/learning/runs" && request.method === "GET") {
  const limit = Math.min(parseInt(new URL(request.url).searchParams.get("limit") || "100", 10), 500);
  const rows = await db.prepare(
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
  await db.prepare(
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
  const rows = await db.prepare(q).bind(...params)
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

// GET /api/feedback — list feedback (for learning pipeline)
if (path === "/api/feedback" && request.method === "GET") {
  const limit = Math.min(parseInt(new URL(request.url).searchParams.get("limit") || "500", 10), 1000);
  const rows = await db.prepare(
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
  const row = await db.prepare("SELECT id FROM jobs WHERE id = ? AND status = 'completed'").bind(id).first();
  if (!row) return err("Job not found or not completed", 404);
  const fid = uuid();
  await db.prepare(
    "INSERT INTO feedback (id, job_id, rating) VALUES (?, ?, ?) ON CONFLICT(job_id) DO UPDATE SET rating = excluded.rating"
  )
    .bind(fid, id, rating)
    .run();
  await logEvent(env, "feedback", id, { rating });

  // Thumbs-up: promote prompt into loop good_prompts so exploit favors human-liked mini-scenes
  // Thumbs-down: remove from good_prompts and track as bad so the loop avoids replaying it
  if (env.MOTION_KV) {
    try {
      const job = await db.prepare("SELECT prompt FROM jobs WHERE id = ?").bind(id).first<{ prompt: string }>();
      const prompt = (job?.prompt || "").trim().slice(0, 500);
      if (prompt) {
        const raw = await env.MOTION_KV.get("loop_state");
        const state = raw ? (JSON.parse(raw) as Record<string, unknown>) : {};
        let good = Array.isArray(state.good_prompts)
          ? (state.good_prompts as unknown[]).map((p) => String(p ?? "").slice(0, 500))
          : [];
        let bad = Array.isArray(state.bad_prompts)
          ? (state.bad_prompts as unknown[]).map((p) => String(p ?? "").slice(0, 500))
          : [];
        if (rating === 2) {
          good = good.filter((p) => p !== prompt);
          good.push(prompt);
          bad = bad.filter((p) => p !== prompt);
        } else if (rating === 1) {
          good = good.filter((p) => p !== prompt);
          if (!bad.includes(prompt)) bad.push(prompt);
        }
        state.good_prompts = good.slice(-200);
        state.bad_prompts = bad.slice(-100);
        await env.MOTION_KV.put("loop_state", JSON.stringify(state));
      }
    } catch (e) {
      console.error("feedback→good/bad_prompts failed:", e);
    }
  }

  return json({ id: fid, rating, status: "saved" }, 201);
}

// GET /api/learning/stats — aggregated stats (KV cache; fallback to D1-only on KV failure)
if (path === "/api/learning/stats" && request.method === "GET") {
  const safeDefault = { total_runs: 0, by_palette: {}, by_keyword: {}, overall: {} };
  if (!db) return json(safeDefault);
  try {
    if (env.MOTION_KV) {
      const cached = await env.MOTION_KV.get("learning:stats");
      if (cached) return json(JSON.parse(cached));
    }
    const rows = await db.prepare(
      "SELECT prompt, spec_json, analysis_json FROM learning_runs ORDER BY created_at DESC LIMIT 500"
    )
      .all<{ prompt: string; spec_json: string; analysis_json: string }>();
    const report = aggregateLearningRuns(rows.results || []);
    if (env.MOTION_KV) {
      try {
        await env.MOTION_KV.put("learning:stats", JSON.stringify(report), { expirationTtl: 120 });
      } catch {
        /* ignore KV write failure */
      }
    }
    return json(report);
  } catch (e) {
    console.error("GET /api/learning/stats failed:", e);
    return json(safeDefault);
  }
}


  return null;
}
