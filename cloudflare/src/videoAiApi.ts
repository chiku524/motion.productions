/**
 * Video AI side project mounted at /video-ai — shares planner with ../video-ai/src/planner.
 */
import { planRecipe } from "../../video-ai/src/planner/index";

const corsHeaders: Record<string, string> = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Video-AI-Key",
};

function json<T>(data: T, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json", ...corsHeaders },
  });
}

function d1Err(e: unknown, status = 500) {
  const detail = e instanceof Error ? e.message : String(e);
  const safe = detail.slice(0, 500);
  return json({ error: "Database error", detail: safe }, status);
}

export type VideoAiEnv = {
  OPENAI_API_KEY?: string;
  OPENAI_MODEL?: string;
  VIDEO_AI_RENDER_URL?: string;
  VIDEO_AI_RENDER_SECRET?: string;
  DB: D1Database;
  VIDEOS: R2Bucket;
};

type JobRow = {
  id: string;
  status: string;
  recipe_key: string;
  output_key: string;
  error: string | null;
  created_at: string;
  updated_at: string;
};

/** True after video_ai_jobs exists in this isolate (avoids relying on wrangler migrate on large D1). */
let videoAiJobsTableReady = false;

/**
 * Ensure video_ai_jobs exists. Remote `wrangler d1 migrations apply` can fail (7429); same pattern as learned_dynamic_meta.
 */
async function ensureVideoAiJobsTable(db: D1Database): Promise<void> {
  if (videoAiJobsTableReady) return;
  try {
    await db.prepare("SELECT 1 FROM video_ai_jobs LIMIT 1").first();
    videoAiJobsTableReady = true;
    return;
  } catch {
    /* missing */
  }
  try {
    await db
      .prepare(
        `CREATE TABLE IF NOT EXISTS video_ai_jobs (
          id TEXT PRIMARY KEY,
          status TEXT NOT NULL,
          recipe_key TEXT NOT NULL,
          output_key TEXT NOT NULL,
          error TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )`,
      )
      .run();
  } catch {
    /* retry next request */
  }
  try {
    await db
      .prepare(
        "CREATE INDEX IF NOT EXISTS idx_video_ai_jobs_status ON video_ai_jobs(status)",
      )
      .run();
  } catch {
    /* non-fatal */
  }
  try {
    await db
      .prepare(
        "CREATE INDEX IF NOT EXISTS idx_video_ai_jobs_created ON video_ai_jobs(created_at)",
      )
      .run();
  } catch {
    /* non-fatal */
  }
  try {
    await db.prepare("SELECT 1 FROM video_ai_jobs LIMIT 1").first();
    videoAiJobsTableReady = true;
  } catch {
    /* leave false */
  }
}

function jobKeys(jobId: string) {
  const prefix = `video-ai/jobs/${jobId}`;
  return {
    recipeKey: `${prefix}/recipe.json`,
    outputKey: `${prefix}/output.mp4`,
  };
}

async function notifyRailwayEnqueue(
  env: VideoAiEnv,
  jobId: string,
  origin: string,
): Promise<{ ok: boolean; status: number; detail: string }> {
  const base = env.VIDEO_AI_RENDER_URL?.replace(/\/$/, "");
  if (!base) {
    return { ok: false, status: 0, detail: "VIDEO_AI_RENDER_URL not set" };
  }
  const { recipeKey, outputKey } = jobKeys(jobId);
  const completeUrl = `${origin.replace(/\/$/, "")}/video-ai/api/jobs/${jobId}/complete`;
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (env.VIDEO_AI_RENDER_SECRET) {
    headers["X-Video-AI-Key"] = env.VIDEO_AI_RENDER_SECRET;
  }
  try {
    const res = await fetch(`${base}/jobs`, {
      method: "POST",
      headers,
      body: JSON.stringify({ jobId, recipeKey, outputKey, completeUrl }),
    });
    const detail = (await res.text()).slice(0, 500);
    return { ok: res.ok, status: res.status, detail };
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e);
    return { ok: false, status: 0, detail: message };
  }
}

export async function handleVideoAiApi(
  request: Request,
  env: VideoAiEnv,
  path: string,
  ctx: ExecutionContext,
): Promise<Response | null> {
  if (!path.startsWith("/video-ai/api/")) return null;

  const sub = path.slice("/video-ai/api".length);
  const route = sub === "" ? "/" : sub;

  const touchesVideoAiJobsTable = route === "/jobs" || route.startsWith("/jobs/");
  if (touchesVideoAiJobsTable) {
    try {
      await ensureVideoAiJobsTable(env.DB);
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      return json({ error: `Database setup failed: ${message}` }, 500);
    }
    if (!videoAiJobsTableReady) {
      return json(
        {
          error:
            "video_ai_jobs table is not available yet. Retry shortly, or apply migration 0020_video_ai_jobs.sql when D1 allows.",
        },
        503,
      );
    }
  }

  if (route === "/health" && request.method === "GET") {
    return json({ ok: true, service: "video-ai", mount: "/video-ai" });
  }

  if (route === "/plan" && request.method === "POST") {
    let body: { prompt?: string; targetDurationSec?: number; maxDurationSec?: number };
    try {
      body = await request.json();
    } catch {
      return json({ error: "Invalid JSON" }, 400);
    }
    const prompt = typeof body.prompt === "string" ? body.prompt.trim() : "";
    if (!prompt) return json({ error: "Missing prompt" }, 400);
    try {
      const { recipe, source } = await planRecipe({
        prompt,
        targetDurationSec: body.targetDurationSec,
        maxDurationSec: body.maxDurationSec,
        openaiApiKey: env.OPENAI_API_KEY,
        openaiModel: env.OPENAI_MODEL,
      });
      return json({ recipe, source });
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      return json({ error: message }, 502);
    }
  }

  if (route === "/render" && request.method === "POST") {
    const base = env.VIDEO_AI_RENDER_URL?.replace(/\/$/, "");
    if (!base) {
      return json(
        {
          error:
            "VIDEO_AI_RENDER_URL is not configured. For MP4 output, run the Node render service (see video-ai/README.md) and set this variable on the Worker, or use local http://127.0.0.1:8788/render.",
        },
        501,
      );
    }

    let recipe: unknown;
    try {
      const body = await request.json();
      recipe =
        body && typeof body === "object" && "recipe" in body
          ? (body as { recipe: unknown }).recipe
          : body;
    } catch {
      return json({ error: "Invalid JSON" }, 400);
    }

    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (env.VIDEO_AI_RENDER_SECRET) {
      headers["X-Video-AI-Key"] = env.VIDEO_AI_RENDER_SECRET;
    }

    const url = `${base}/render`;
    const bodyJson = JSON.stringify({ recipe });
    let res = await fetch(url, { method: "POST", headers, body: bodyJson });
    if (res.status === 503) {
      await new Promise((r) => setTimeout(r, 2500));
      res = await fetch(url, { method: "POST", headers, body: bodyJson });
    }

    if (!res.ok) {
      const text = await res.text();
      return json({ error: `Render service ${res.status}`, detail: text.slice(0, 400) }, 502);
    }

    return new Response(res.body, {
      headers: {
        "Content-Type": "video/mp4",
        "Cache-Control": "no-store",
        ...corsHeaders,
      },
    });
  }

  if (route === "/jobs" && request.method === "POST") {
    const base = env.VIDEO_AI_RENDER_URL?.replace(/\/$/, "");
    if (!base) {
      return json(
        {
          error:
            "VIDEO_AI_RENDER_URL is not configured. Set it on the Worker and configure R2 credentials on Railway for async jobs (see video-ai/README.md).",
        },
        501,
      );
    }

    let recipe: unknown;
    try {
      const body = await request.json();
      recipe =
        body && typeof body === "object" && "recipe" in body
          ? (body as { recipe: unknown }).recipe
          : body;
    } catch {
      return json({ error: "Invalid JSON" }, 400);
    }
    if (recipe === undefined || recipe === null || typeof recipe !== "object") {
      return json({ error: "Missing recipe" }, 400);
    }

    const jobId = crypto.randomUUID();
    const { recipeKey, outputKey } = jobKeys(jobId);
    const recipeText = JSON.stringify(recipe);

    try {
      await env.VIDEOS.put(recipeKey, recipeText, {
        httpMetadata: { contentType: "application/json" },
      });
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      return json({ error: `R2 put failed: ${message}` }, 502);
    }

    try {
      await env.DB.prepare(
        `INSERT INTO video_ai_jobs (id, status, recipe_key, output_key, error, created_at, updated_at)
         VALUES (?, 'queued', ?, ?, NULL, datetime('now'), datetime('now'))`,
      )
        .bind(jobId, recipeKey, outputKey)
        .run();
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      ctx.waitUntil(env.VIDEOS.delete(recipeKey).catch(() => {}));
      return json({ error: `Job row failed: ${message}` }, 500);
    }

    const origin = new URL(request.url).origin;
    ctx.waitUntil(
      (async () => {
        const r = await notifyRailwayEnqueue(env, jobId, origin);
        if (!r.ok) {
          const errText = r.status ? `enqueue ${r.status}: ${r.detail}` : r.detail;
          try {
            await env.DB.prepare(
              `UPDATE video_ai_jobs SET status = 'failed', error = ?, updated_at = datetime('now') WHERE id = ?`,
            )
              .bind(errText.slice(0, 2000), jobId)
              .run();
          } catch {
            /* ignore */
          }
        } else {
          try {
            await env.DB.prepare(
              `UPDATE video_ai_jobs SET status = 'processing', updated_at = datetime('now') WHERE id = ?`,
            )
              .bind(jobId)
              .run();
          } catch {
            /* ignore */
          }
        }
      })(),
    );

    return json({
      jobId,
      status: "queued",
      pollUrl: `/video-ai/api/jobs/${jobId}`,
      downloadUrl: `/video-ai/api/jobs/${jobId}/download`,
    });
  }

  const jobStatusMatch = /^\/jobs\/([^/]+)$/.exec(route);
  if (jobStatusMatch && request.method === "GET") {
    const jobId = jobStatusMatch[1];
    let row: JobRow | null = null;
    try {
      row = await env.DB.prepare(
        `SELECT id, status, recipe_key, output_key, error, created_at, updated_at FROM video_ai_jobs WHERE id = ?`,
      )
        .bind(jobId)
        .first<JobRow>();
    } catch (e) {
      return d1Err(e);
    }
    if (!row) return json({ error: "Not found" }, 404);
    const payload: Record<string, unknown> = {
      jobId: row.id,
      status: row.status,
      createdAt: row.created_at,
      updatedAt: row.updated_at,
    };
    if (row.error) payload.error = row.error;
    if (row.status === "completed") {
      payload.downloadUrl = `/video-ai/api/jobs/${jobId}/download`;
    }
    return json(payload);
  }

  const jobDownloadMatch = /^\/jobs\/([^/]+)\/download$/.exec(route);
  if (jobDownloadMatch && request.method === "GET") {
    const jobId = jobDownloadMatch[1];
    let row: { status: string; output_key: string } | null = null;
    try {
      row = await env.DB.prepare(`SELECT status, output_key FROM video_ai_jobs WHERE id = ?`)
        .bind(jobId)
        .first<{ status: string; output_key: string }>();
    } catch (e) {
      return d1Err(e);
    }
    if (!row) return json({ error: "Not found" }, 404);
    if (row.status !== "completed") {
      return json({ error: "Not ready", status: row.status }, 409);
    }
    const obj = await env.VIDEOS.get(row.output_key);
    if (!obj) return json({ error: "Output missing in R2" }, 404);
    const headers = new Headers({
      "Content-Type": "video/mp4",
      "Cache-Control": "no-store",
      ...corsHeaders,
    });
    return new Response(obj.body, { headers });
  }

  const jobCompleteMatch = /^\/jobs\/([^/]+)\/complete$/.exec(route);
  if (jobCompleteMatch && request.method === "POST") {
    const secret = env.VIDEO_AI_RENDER_SECRET;
    if (secret) {
      const key = request.headers.get("X-Video-AI-Key");
      if (key !== secret) return json({ error: "Unauthorized" }, 401);
    }
    const jobId = jobCompleteMatch[1];
    let body: { ok?: boolean; error?: string };
    try {
      body = await request.json();
    } catch {
      return json({ error: "Invalid JSON" }, 400);
    }
    const ok = body.ok === true;
    const errMsg = ok
      ? null
      : typeof body.error === "string"
        ? body.error.slice(0, 4000)
        : "failed";

    let exists = false;
    try {
      const probe = await env.DB.prepare(`SELECT 1 AS n FROM video_ai_jobs WHERE id = ?`)
        .bind(jobId)
        .first<{ n: number }>();
      exists = probe !== null;
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      return json({ error: message }, 500);
    }
    if (!exists) return json({ error: "Not found" }, 404);

    const status = ok ? "completed" : "failed";
    try {
      await env.DB.prepare(
        `UPDATE video_ai_jobs SET status = ?, error = ?, updated_at = datetime('now') WHERE id = ?`,
      )
        .bind(status, ok ? null : errMsg, jobId)
        .run();
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      return json({ error: message }, 500);
    }
    return json({ ok: true });
  }

  return json({ error: "Not found" }, 404);
}
