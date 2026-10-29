/**
 * Jobs, learning, events, feedback API routes.
 */
import type { Env } from "../env";
import { getDb } from "../db";
import { json, err, uuid, corsHeaders } from "../http";
import { aggregateLearningRuns, logEvent } from "../naming";
import { getSnapshot, invalidateSnapshot } from "../snapshotCache";
import { PENDING_CACHE_KEY, listPendingWebJobs } from "../jobsClaim";
import { hitRateLimit } from "../rateLimit";
import { slimAnalysis, slimSpec } from "../learningSlim";
import { maybeRunRetention } from "../retention";
import { rowsWrittenOf } from "../d1Meta";
import { checkDeclaredSize, recordPut, reserveUpload } from "../r2Budget";

/** jobs.r2_key sentinels: no R2 object exists (loops delete renders after discovery; retention may expire others). */
export const R2_KEY_SKIPPED = "skipped:no-upload";
export const hasR2Object = (k: string | null | undefined): k is string => !!k && !k.startsWith("skipped:") && !k.startsWith("expired:");

/** GET /api/jobs: per-client cap and snapshot TTLs (free-tier D1 read budget, see docs/D1_FREE_TIER.md). */
const JOBS_LIST_RATE_PER_MIN = 120;
const JOBS_COMPLETED_SOFT_TTL_SEC = 120;

export async function handleJobsRoutes(
  request: Request,
  env: Env,
  path: string,
): Promise<Response | null> {
  const db = getDb(env);

  // GET /api/jobs?status=pending|completed — list jobs (pending for webjobs; loop-owned explorer/exploiter/main stay off this queue)
if (path === "/api/jobs" && request.method === "GET") {
  const url = new URL(request.url);
  const status = url.searchParams.get("status");
  const limit = Math.min(parseInt(url.searchParams.get("limit") ?? "24", 10) || 24, 100);
  if (status !== "pending" && status !== "completed") return err("status=pending or status=completed required", 400);
  // Unauthenticated + hit by every gallery page / worker poll: cap per client (Cache API counter, no D1/KV write).
  const rl = await hitRateLimit(request, "jobs-list", JOBS_LIST_RATE_PER_MIN, 60);
  if (!rl.allowed) {
    const r = json({ error: "rate limited" }, 429);
    r.headers.set("Retry-After", String(rl.retryAfterSec));
    return r;
  }
  if (status === "pending") {
    // Bounded cursor scan + negative cache (jobsClaim.ts): an empty queue costs 0 D1 reads for 60 s, a backlog of
    // loop-owned pending rows is walked once, and a D1 quota error serves the last answer (X-Degraded) instead of a 5xx.
    const listing = await listPendingWebJobs(env, limit);
    const { source, stale, ...body } = listing;
    const r = json(body);
    r.headers.set("X-Cache", source === "built" ? "MISS" : stale ? "STALE" : "HIT");
    if (listing.degraded) r.headers.set("X-Degraded", "d1-quota");
    // Retry-After is only a hint on 200s; clients also read poll_after_sec from the body.
    if (listing.poll_after_sec > 0) r.headers.set("Retry-After", String(listing.poll_after_sec));
    r.headers.set("Cache-Control", `public, max-age=${listing.poll_after_sec > 0 ? Math.min(listing.poll_after_sec, 60) : 5}`);
    return r;
  }
  const maxDur = url.searchParams.get("max_duration");
  const minDur = url.searchParams.get("min_duration");
  const ratingFilter = url.searchParams.get("rating"); // "2" = liked only
  const maxD = maxDur != null ? parseFloat(maxDur) : null;
  const minD = minDur != null ? parseFloat(minDur) : null;
  const likedOnly = ratingFilter === "2" || ratingFilter === "up";
  const okMin = minD != null && !Number.isNaN(minD) ? minD : null;
  const okMax = maxD != null && !Number.isNaN(maxD) ? maxD : null;
  // Normalised key: arbitrary query strings (cache-busters like &_=123) must not fan out into distinct D1 reads.
  const cacheKey = `jobs:list:v1:completed:${limit}:${okMin ?? ""}:${okMax ?? ""}:${likedOnly ? "liked" : "all"}`;
  const snap = await getSnapshot<{ jobs: unknown[] }>(
    env,
    cacheKey,
    { softTtlSec: JOBS_COMPLETED_SOFT_TTL_SEC, hardTtlSec: 86400 },
    async () => {
      let sql = likedOnly
        ? `SELECT j.id, j.prompt, j.duration_seconds, j.created_at, j.updated_at, j.workflow_type
           FROM jobs j
           INNER JOIN feedback f ON f.job_id = j.id AND f.rating = 2
           WHERE j.status = 'completed' AND j.r2_key IS NOT NULL`
        : "SELECT id, prompt, duration_seconds, created_at, updated_at, workflow_type FROM jobs WHERE status = 'completed' AND r2_key IS NOT NULL";
      const binds: (string | number)[] = [];
      const durCol = likedOnly ? "j.duration_seconds" : "duration_seconds";
      const orderCol = likedOnly ? "j.rowid" : "rowid";
      if (okMin != null) {
        sql += ` AND ${durCol} IS NOT NULL AND ${durCol} >= ?`;
        binds.push(okMin);
      }
      if (okMax != null) {
        sql += ` AND ${durCol} IS NOT NULL AND ${durCol} <= ?`;
        binds.push(okMax);
      }
      sql += ` ORDER BY ${orderCol} DESC LIMIT ?`;
      binds.push(limit);
      const rows = await db.prepare(sql)
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
      return { jobs };
    },
  );
  const resp = json(snap.value);
  resp.headers.set("X-Cache", snap.source === "built" ? "MISS" : snap.stale ? "STALE" : "HIT");
  if (snap.degraded) resp.headers.set("X-Degraded", "d1-quota");
  resp.headers.set("Cache-Control", "public, max-age=15");
  return resp;
}

// POST /api/jobs — create job (optional workflow_type: explorer | exploiter | main | web | cartoon)
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
  const workflow_type = typeof body.workflow_type === "string" && /^(explorer|exploiter|main|web|cartoon)$/.test(body.workflow_type) ? body.workflow_type : null;
  const created = await db.prepare(
    "INSERT INTO jobs (id, prompt, duration_seconds, status, workflow_type) VALUES (?, ?, ?, 'pending', ?)"
  )
    .bind(id, prompt, duration_seconds ?? null, workflow_type)
    .run();
  // A new web job must not wait out the 60 s negative cache (this isolate / colo; others age out within the TTL).
  if (workflow_type === null || workflow_type === "web") await invalidateSnapshot(PENDING_CACHE_KEY);
  return json({ id, prompt, duration_seconds, workflow_type: workflow_type ?? undefined, status: "pending", rows_written: rowsWrittenOf(created) }, 201);
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
  // No R2 head/get here (Class B op per poll): the key in D1 is the source of truth; /download 404s if retention removed it.
  if (row.status === "completed" && hasR2Object(row.r2_key)) {
    out.download_url = `/api/jobs/${id}/download`;
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

  // Reject oversized uploads before reading the body, then enforce the storage budget.
  const declared = Number(request.headers.get("Content-Length") ?? "");
  if (Number.isFinite(declared) && declared > 0) {
    const pre = checkDeclaredSize(env, declared);
    if (!pre.ok) return json({ error: pre.error, ...pre.details }, pre.status);
  }
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
  const reserve = await reserveUpload(env, body.byteLength);
  if (!reserve.ok) return json({ error: reserve.error, ...reserve.details }, reserve.status);
  const r2_key = `jobs/${id}/video.mp4`;
  await env.VIDEOS.put(r2_key, body, { httpMetadata: { contentType } });
  try {
    await recordPut(env, body.byteLength);
  } catch (e) {
    console.error("r2 usage counter update failed (sweep will re-measure):", e);
  }
  // Atomic claim: only one finisher wins; a concurrent worker gets changes = 0.
  const won = await db.prepare(
    "UPDATE jobs SET status = 'completed', r2_key = ?, updated_at = datetime('now') WHERE id = ? AND status = 'pending'"
  )
    .bind(r2_key, id)
    .run();
  if (won.meta?.changes === 0) return err("Job already has video", 400);
  return json({ id, status: "completed", download_url: `/api/jobs/${id}/download`, rows_written: rowsWrittenOf(won) });
}

// POST /api/jobs/:id/complete — mark a job completed WITHOUT storing a video (loops delete renders after discovery;
// avoids R2 storage + Class A ops). Sets r2_key to a sentinel so status/progress queries still count the run.
const completeMatch = path.match(/^\/api\/jobs\/([a-f0-9-]+)\/complete$/);
if (completeMatch && request.method === "POST") {
  const id = completeMatch[1];
  const row = await db.prepare("SELECT id, status FROM jobs WHERE id = ?").bind(id).first();
  if (!row) return err("Job not found", 404);
  if ((row as { status: string }).status !== "pending") return err("Job already completed", 400);
  const won = await db.prepare(
    "UPDATE jobs SET status = 'completed', r2_key = ?, updated_at = datetime('now') WHERE id = ? AND status = 'pending'"
  )
    .bind(R2_KEY_SKIPPED, id)
    .run();
  if (won.meta?.changes === 0) return err("Job already completed", 400);
  return json({ id, status: "completed", stored: false, rows_written: rowsWrittenOf(won) });
}

// GET /api/jobs/:id/download — stream video from R2
const downloadMatch = path.match(/^\/api\/jobs\/([a-f0-9-]+)\/download$/);
if (downloadMatch && request.method === "GET") {
  const id = downloadMatch[1];
  const row = await db.prepare("SELECT r2_key FROM jobs WHERE id = ? AND status = 'completed'")
    .bind(id)
    .first<{ r2_key: string | null }>();
  if (!row?.r2_key) return err("Not found", 404);
  if (!hasR2Object(row.r2_key)) return err("Video not stored", 404);
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
  let body: { job_id?: string; prompt: string; spec: Record<string, unknown>; analysis: Record<string, unknown>; store_full?: boolean };
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
  // Loop clips only need the few fields aggregateLearningRuns reads; the full documents were ~22% of the D1 file.
  const full = body.store_full === true;
  const logged = await db.prepare(
    "INSERT INTO learning_runs (id, job_id, prompt, spec_json, analysis_json) VALUES (?, ?, ?, ?, ?)"
  )
    .bind(id, jobId, prompt, JSON.stringify(full ? spec : slimSpec(spec)), JSON.stringify(full ? analysis : slimAnalysis(analysis)))
    .run();
  const ret = await maybeRunRetention(env);
  // Do not use KV delete (free tier limit). Stats cache expires via TTL; GET recomputes when stale.
  return json({ id, job_id: jobId, status: "logged", rows_written: rowsWrittenOf(logged) + ret.totalRowsWritten }, 201);
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
  const evt = await db.prepare(
    "INSERT INTO events (id, event_type, job_id, payload_json) VALUES (?, ?, ?, ?)"
  )
    .bind(id, eventType, jobId, payload ? JSON.stringify(payload) : null)
    .run();
  return json({ id, status: "logged", rows_written: rowsWrittenOf(evt) }, 201);
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

  return json({ id: fid, rating, status: "saved" }, 201);
}

// GET /api/learning/stats — aggregated stats (KV cache; fallback to D1-only on KV failure)
if (path === "/api/learning/stats" && request.method === "GET") {
  const safeDefault = { total_runs: 0, by_palette: {}, by_keyword: {}, overall: {} };
  if (!db) return json(safeDefault);
  try {
    const statsSnap = await getSnapshot<ReturnType<typeof aggregateLearningRuns>>(
      env,
      "learning:stats",
      { softTtlSec: 1800, hardTtlSec: 86400 },
      async () => {
    const rows = await db.prepare(
      "SELECT prompt, spec_json, analysis_json FROM learning_runs ORDER BY created_at DESC LIMIT 500"
    )
      .all<{ prompt: string; spec_json: string; analysis_json: string }>();
    return aggregateLearningRuns(rows.results || []);
      },
    );
    return json(statsSnap.value);
  } catch (e) {
    console.error("GET /api/learning/stats failed:", e);
    return json(safeDefault);
  }
}


  return null;
}
