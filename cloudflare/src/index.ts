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
      try {
        const apiResponse = await handleApi(request, env, path);
        if (apiResponse) return apiResponse;
      } catch (e) {
        console.error("handleApi threw:", e);
        return new Response(
          JSON.stringify({ error: "Service temporarily unavailable", details: String(e) }),
          {
            status: 503,
            headers: {
              "Content-Type": "application/json",
              ...corsHeaders,
              "Retry-After": "3",
            },
          }
        );
      }
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

  // GET /api/jobs?status=pending|completed — list jobs (pending for worker; completed for library)
    if (path === "/api/jobs" && request.method === "GET") {
      const url = new URL(request.url);
      const status = url.searchParams.get("status");
      const limit = Math.min(parseInt(url.searchParams.get("limit") ?? "24", 10) || 24, 100);
      if (status === "pending") {
        const rows = await env.DB.prepare(
          "SELECT id, prompt, duration_seconds, created_at FROM jobs WHERE status = 'pending' ORDER BY created_at ASC"
        )
          .all<{ id: string; prompt: string; duration_seconds: number | null; created_at: string }>();
        return json({ jobs: rows.results || [] });
      }
      if (status === "completed") {
        const rows = await env.DB.prepare(
          "SELECT id, prompt, duration_seconds, created_at, updated_at, workflow_type FROM jobs WHERE status = 'completed' AND r2_key IS NOT NULL ORDER BY updated_at DESC LIMIT ?"
        )
          .bind(limit)
          .all<{ id: string; prompt: string; duration_seconds: number | null; created_at: string; updated_at: string; workflow_type: string | null }>();
        const jobs = (rows.results || []).map((r) => ({
          id: r.id,
          prompt: r.prompt,
          duration_seconds: r.duration_seconds,
          created_at: r.created_at,
          updated_at: r.updated_at,
          workflow_type: r.workflow_type ?? undefined,
          download_url: `/api/jobs/${r.id}/download`,
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
      await env.DB.prepare(
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
      const row = await env.DB.prepare(
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
      // Do not use KV delete (free tier limit). Stats cache expires via TTL; GET recomputes when stale.
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
      state.good_prompts = Array.isArray(raw.good_prompts)
        ? raw.good_prompts.slice(-200).map((p) => String(p ?? "").slice(0, 500))
        : [];
      state.recent_prompts = Array.isArray(raw.recent_prompts)
        ? raw.recent_prompts.slice(-200).map((p) => String(p ?? "").slice(0, 500))
        : [];
      state.duration_base = typeof raw.duration_base === "number" && Number.isFinite(raw.duration_base) ? raw.duration_base : 6;
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
        const headers = isRateLimit ? { "Retry-After": "2" } : {};
        return new Response(JSON.stringify({ error: "Failed to save loop state", details: msg }), {
          status,
          headers: { "Content-Type": "application/json", ...corsHeaders, ...headers },
        });
      }
    }

    // GET /api/loop/config — user-controlled loop config (enabled, delay, exploit_ratio, duration_seconds)
    if (path === "/api/loop/config" && request.method === "GET") {
      const kv = env.MOTION_KV;
      if (!kv) return json({ error: "Loop config unavailable: KV not bound", details: "MOTION_KV undefined" }, 500);
      try {
        const raw = await kv.get("loop_config");
        let config: { enabled?: boolean; delay_seconds?: number; exploit_ratio?: number; duration_seconds?: number } = { enabled: true, delay_seconds: 30, exploit_ratio: 0.7, duration_seconds: 1 };
        if (raw && raw.length > 0) {
          try {
            config = JSON.parse(raw) as typeof config;
          } catch {
            /* use defaults */
          }
        }
        const duration = typeof config.duration_seconds === "number" ? config.duration_seconds : 1;
        return json({
          enabled: config.enabled !== false,
          delay_seconds: typeof config.delay_seconds === "number" ? config.delay_seconds : 30,
          exploit_ratio: typeof config.exploit_ratio === "number" ? config.exploit_ratio : 0.7,
          duration_seconds: Math.max(1, Math.min(60, duration)),
        });
      } catch (e) {
        return json({ error: "Failed to load loop config", details: String(e) }, 500);
      }
    }

    // POST /api/loop/config — update loop config (controls Railway loop)
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
        if (typeof body.delay_seconds === "number") current.delay_seconds = Math.max(0, Math.min(600, body.delay_seconds));
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
        let config: { enabled?: boolean; delay_seconds?: number; exploit_ratio?: number; duration_seconds?: number } = { enabled: true, delay_seconds: 30, exploit_ratio: 0.7, duration_seconds: 1 };
        if (configRaw && configRaw.length > 0) {
          try {
            config = JSON.parse(configRaw) as typeof config;
          } catch {
            /* use defaults */
          }
        }
        const duration = typeof config.duration_seconds === "number" ? config.duration_seconds : 1;
        const stateRaw = await kv.get("loop_state");
        let state: Record<string, unknown> = {};
        if (stateRaw && stateRaw.length > 0) {
          try {
            state = JSON.parse(stateRaw) as Record<string, unknown>;
          } catch {
            /* use empty */
          }
        }
        const rows = await env.DB.prepare(
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

    // POST /api/interpret/queue — enqueue a prompt for interpretation (no create/render)
    if (path === "/api/interpret/queue" && request.method === "POST") {
      let body: { prompt: string; source?: string };
      try {
        body = (await request.json()) as typeof body;
      } catch {
        return err("Invalid JSON");
      }
      const prompt = typeof body.prompt === "string" ? body.prompt.trim() : "";
      if (!prompt) return err("prompt is required");
      const source = typeof body.source === "string" && /^(web|worker|loop)$/.test(body.source) ? body.source : "worker";
      const id = uuid();
      await env.DB.prepare(
        "INSERT INTO interpretations (id, prompt, source, status) VALUES (?, ?, ?, 'pending')"
      )
        .bind(id, prompt, source)
        .run();
      return json({ id, prompt: prompt.slice(0, 200), source, status: "pending" }, 201);
    }

    // GET /api/interpret/queue — fetch pending prompts for interpretation worker
    if (path === "/api/interpret/queue" && request.method === "GET") {
      const limit = Math.min(parseInt(new URL(request.url).searchParams.get("limit") || "20", 10), 50);
      const rows = await env.DB.prepare(
        "SELECT id, prompt, source, created_at FROM interpretations WHERE status = 'pending' ORDER BY created_at ASC LIMIT ?"
      )
        .bind(limit)
        .all<{ id: string; prompt: string; source: string; created_at: string }>();
      const items = (rows.results || []).map((r) => ({
        id: r.id,
        prompt: r.prompt,
        source: r.source,
        created_at: r.created_at,
      }));
      return json({ items });
    }

    // PATCH /api/interpret/:id — store interpretation result (called by interpretation worker)
    const interpretMatch = path.match(/^\/api\/interpret\/([a-f0-9-]+)$/);
    if (interpretMatch && request.method === "PATCH") {
      const id = interpretMatch[1];
      let body: { instruction: Record<string, unknown> };
      try {
        body = (await request.json()) as typeof body;
      } catch {
        return err("Invalid JSON");
      }
      const instruction = body.instruction && typeof body.instruction === "object" ? body.instruction : null;
      if (!instruction) return err("instruction is required");
      const row = await env.DB.prepare("SELECT id, status FROM interpretations WHERE id = ?").bind(id).first();
      if (!row) return err("Interpretation job not found", 404);
      if ((row as { status: string }).status !== "pending") return err("Already interpreted", 400);
      await env.DB.prepare(
        "UPDATE interpretations SET instruction_json = ?, status = 'done', updated_at = datetime('now') WHERE id = ?"
      )
        .bind(JSON.stringify(instruction), id)
        .run();
      return json({ id, status: "done" });
    }

    // GET /api/interpret/backfill-prompts — prompts from jobs not yet in interpretations (for interpretation worker)
    if (path === "/api/interpret/backfill-prompts" && request.method === "GET") {
      const limit = Math.min(parseInt(new URL(request.url).searchParams.get("limit") || "30", 10), 100);
      const rows = await env.DB.prepare(
        `SELECT DISTINCT j.prompt FROM jobs j
         LEFT JOIN interpretations i ON i.prompt = j.prompt AND i.status = 'done'
         WHERE j.prompt IS NOT NULL AND j.prompt != '' AND i.id IS NULL
         ORDER BY j.created_at DESC LIMIT ?`
      )
        .bind(limit)
        .all<{ prompt: string }>();
      const prompts = (rows.results || []).map((r) => r.prompt);
      return json({ prompts });
    }

    // POST /api/interpretations — store completed interpretation directly (e.g. backfill from jobs)
    if (path === "/api/interpretations" && request.method === "POST") {
      let body: { prompt: string; instruction: Record<string, unknown>; source?: string };
      try {
        body = (await request.json()) as typeof body;
      } catch {
        return err("Invalid JSON");
      }
      const prompt = typeof body.prompt === "string" ? body.prompt.trim() : "";
      if (!prompt) return err("prompt is required");
      const instruction = body.instruction && typeof body.instruction === "object" ? body.instruction : null;
      if (!instruction) return err("instruction is required");
      const source = typeof body.source === "string" && /^(web|worker|loop|backfill)$/.test(body.source) ? body.source : "worker";
      const id = uuid();
      await env.DB.prepare(
        "INSERT INTO interpretations (id, prompt, instruction_json, source, status) VALUES (?, ?, ?, ?, 'done')"
      )
        .bind(id, prompt, JSON.stringify(instruction), source)
        .run();
      return json({ id, prompt: prompt.slice(0, 200), status: "done" }, 201);
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

    // GET /api/learning/stats — aggregated stats (KV cache; fallback to D1-only on KV failure)
    if (path === "/api/learning/stats" && request.method === "GET") {
      const safeDefault = { total_runs: 0, by_palette: {}, by_keyword: {}, overall: {} };
      if (!env.DB) return json(safeDefault);
      try {
        if (env.MOTION_KV) {
          const cached = await env.MOTION_KV.get("learning:stats");
          if (cached) return json(JSON.parse(cached));
        }
        const rows = await env.DB.prepare(
          "SELECT prompt, spec_json, analysis_json FROM learning_runs ORDER BY created_at DESC LIMIT 500"
        )
          .all<{ prompt: string; spec_json: string; analysis_json: string }>();
        const report = aggregateLearningRuns(rows.results || []);
        if (env.MOTION_KV) {
          try {
            await env.MOTION_KV.put("learning:stats", JSON.stringify(report), { expirationTtl: 60 });
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

    // POST /api/knowledge/name/take — reserve a unique name for a discovery
    if (path === "/api/knowledge/name/take" && request.method === "POST") {
      const name = await generateUniqueName(env);
      await env.DB.prepare("INSERT INTO name_reserve (name) VALUES (?)").bind(name).run();
      return json({ name }, 201);
    }

    // POST /api/knowledge/discoveries — batch record discoveries (D1)
    // Supports: static_colors, static_sound (per-frame) + colors, blends, motion, etc. (dynamic/whole-video)
    if (path === "/api/knowledge/discoveries" && request.method === "POST") {
      let body: {
        static_colors?: Array<{ key: string; r: number; g: number; b: number; brightness?: number; luminance?: number; contrast?: number; saturation?: number; chroma?: number; hue?: number; color_variance?: number; opacity?: number; depth_breakdown?: Record<string, unknown>; source_prompt?: string; name?: string }>;
        static_sound?: Array<{ key: string; amplitude?: number; weight?: number; strength_pct?: number; tone?: string; timbre?: string; depth_breakdown?: Record<string, unknown>; source_prompt?: string; name?: string }>;
        colors?: Array<{ key: string; r: number; g: number; b: number; source_prompt?: string }>;
        blends?: Array<{ name: string; domain: string; inputs: Record<string, unknown>; output: Record<string, unknown>; primitive_depths?: Record<string, unknown>; source_prompt?: string }>;
        motion?: Array<{ key: string; motion_level: number; motion_std: number; motion_trend: string; motion_direction?: string; motion_rhythm?: string; source_prompt?: string }>;
        lighting?: Array<{ key: string; brightness: number; contrast: number; saturation: number; source_prompt?: string }>;
        composition?: Array<{ key: string; center_x: number; center_y: number; luminance_balance: number; source_prompt?: string }>;
        graphics?: Array<{ key: string; edge_density: number; spatial_variance: number; busyness: number; source_prompt?: string }>;
        temporal?: Array<{ key: string; duration: number; motion_trend: string; source_prompt?: string }>;
        technical?: Array<{ key: string; width: number; height: number; fps: number; source_prompt?: string }>;
        audio_semantic?: Array<{ key: string; role: string; mood?: string; tempo?: string; source_prompt?: string; name?: string }>;
        time?: Array<{ key: string; duration: number; fps: number; source_prompt?: string }>;
        gradient?: Array<{ key: string; gradient_type: string; strength?: number; source_prompt?: string }>;
        camera?: Array<{ key: string; motion_type: string; speed?: string; source_prompt?: string }>;
        narrative?: Record<string, Array<{ key: string; value?: string; source_prompt?: string; name?: string }>>;
        job_id?: string;
      };
      try {
        body = (await request.json()) as typeof body;
      } catch {
        return err("Invalid JSON");
      }
      const results: Record<string, number> = { static_colors: 0, static_sound: 0, narrative: 0, colors: 0, blends: 0, motion: 0, lighting: 0, composition: 0, graphics: 0, temporal: 0, technical: 0, audio_semantic: 0, time: 0, gradient: 0, camera: 0 };

      try {
      // Static registry: per-frame color entries
      for (const c of body.static_colors || []) {
        const existing = await env.DB.prepare("SELECT id, name, count FROM static_colors WHERE color_key = ?").bind(c.key).first();
        if (existing) {
          await env.DB.prepare("UPDATE static_colors SET count = count + 1 WHERE color_key = ?").bind(c.key).run();
        } else {
          const name = (c.name && c.name.trim()) ? c.name : await generateUniqueName(env);
          if (!c.name || !c.name.trim()) await env.DB.prepare("INSERT INTO name_reserve (name) VALUES (?)").bind(name).run();
          await env.DB.prepare(
            "INSERT INTO static_colors (id, color_key, r, g, b, brightness, luminance, contrast, saturation, chroma, hue, color_variance, opacity, count, sources_json, name, depth_breakdown_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)"
          ).bind(uuid(), c.key, c.r, c.g, c.b, c.brightness ?? null, c.luminance ?? c.brightness ?? null, c.contrast ?? null, c.saturation ?? null, c.chroma ?? c.saturation ?? null, c.hue ?? null, c.color_variance ?? null, c.opacity ?? null, c.source_prompt ? JSON.stringify([c.source_prompt.slice(0, 80)]) : null, name, c.depth_breakdown ? JSON.stringify(c.depth_breakdown) : null).run();
        }
        results.static_colors++;
      }
      // Static registry: per-frame sound entries
      for (const s of body.static_sound || []) {
        const existing = await env.DB.prepare("SELECT id, name, count FROM static_sound WHERE sound_key = ?").bind(s.key).first();
        if (existing) {
          await env.DB.prepare("UPDATE static_sound SET count = count + 1 WHERE sound_key = ?").bind(s.key).run();
        } else {
          const name = (s.name && s.name.trim()) ? s.name : await generateUniqueName(env);
          if (!s.name || !s.name.trim()) await env.DB.prepare("INSERT INTO name_reserve (name) VALUES (?)").bind(name).run();
          await env.DB.prepare(
            "INSERT INTO static_sound (id, sound_key, amplitude, weight, tone, timbre, count, sources_json, name, depth_breakdown_json, strength_pct) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)"
          ).bind(uuid(), s.key, s.amplitude ?? null, s.weight ?? null, s.tone ?? null, s.timbre ?? null, s.source_prompt ? JSON.stringify([s.source_prompt.slice(0, 80)]) : null, name, s.depth_breakdown ? JSON.stringify(s.depth_breakdown) : null, s.strength_pct ?? s.amplitude ?? s.weight ?? null).run();
        }
        results.static_sound++;
      }
      // Narrative registry: themes, plots, settings, genre, mood, scene_type
      const narrativeAspects = ["genre", "mood", "plots", "settings", "themes", "style", "scene_type"];
      for (const aspect of narrativeAspects) {
        for (const item of body.narrative?.[aspect] || []) {
          const key = (item.key || "").trim().toLowerCase();
          if (!key) continue;
          const existing = await env.DB.prepare("SELECT id, name, count FROM narrative_entries WHERE aspect = ? AND entry_key = ?").bind(aspect, key).first();
          if (existing) {
            await env.DB.prepare("UPDATE narrative_entries SET count = count + 1 WHERE aspect = ? AND entry_key = ?").bind(aspect, key).run();
          } else {
            const name = (item.name && item.name.trim()) ? item.name : await generateUniqueName(env);
            if (!item.name || !item.name.trim()) await env.DB.prepare("INSERT INTO name_reserve (name) VALUES (?)").bind(name).run();
            await env.DB.prepare(
              "INSERT INTO narrative_entries (id, aspect, entry_key, value, count, sources_json, name) VALUES (?, ?, ?, ?, 1, ?, ?)"
            ).bind(uuid(), aspect, key, (item.value ?? item.key ?? "").slice(0, 200), item.source_prompt ? JSON.stringify([item.source_prompt.slice(0, 80)]) : null, name).run();
          }
          results.narrative++;
        }
      }
      for (const c of body.colors || []) {
        const existing = await env.DB.prepare("SELECT id, name, count FROM learned_colors WHERE color_key = ?").bind(c.key).first();
        if (existing) {
          await env.DB.prepare("UPDATE learned_colors SET count = count + 1 WHERE color_key = ?").bind(c.key).run();
        } else {
          const name = await generateUniqueName(env);
          await env.DB.prepare("INSERT INTO name_reserve (name) VALUES (?)").bind(name).run();
          await env.DB.prepare(
            "INSERT INTO learned_colors (id, color_key, r, g, b, count, sources_json, name) VALUES (?, ?, ?, ?, ?, 1, ?, ?)"
          ).bind(uuid(), c.key, c.r, c.g, c.b, c.source_prompt ? JSON.stringify([c.source_prompt.slice(0, 80)]) : null, name).run();
        }
        results.colors++;
      }
      for (const b of body.blends || []) {
        let name = (b.name && b.name.trim()) ? b.name.trim() : await generateUniqueName(env);
        if (b.name && b.name.trim()) {
          name = await resolveUniqueBlendName(env, name);
        } else {
          await env.DB.prepare("INSERT INTO name_reserve (name) VALUES (?)").bind(name).run();
        }
        await env.DB.prepare(
          "INSERT INTO learned_blends (id, name, domain, inputs_json, output_json, primitive_depths_json, source_prompt) VALUES (?, ?, ?, ?, ?, ?, ?)"
        ).bind(uuid(), name, b.domain, JSON.stringify(b.inputs), JSON.stringify(b.output), b.primitive_depths ? JSON.stringify(b.primitive_depths) : null, (b.source_prompt || "").slice(0, 120)).run();
        results.blends++;
      }
      for (const t of body.time || []) {
        const existing = await env.DB.prepare("SELECT id FROM learned_time WHERE profile_key = ?").bind(t.key).first();
        if (existing) {
          await env.DB.prepare("UPDATE learned_time SET count = count + 1 WHERE profile_key = ?").bind(t.key).run();
        } else {
          const name = await generateUniqueName(env);
          await env.DB.prepare("INSERT INTO name_reserve (name) VALUES (?)").bind(name).run();
          await env.DB.prepare(
            "INSERT INTO learned_time (id, profile_key, duration, fps, count, sources_json, name) VALUES (?, ?, ?, ?, 1, ?, ?)"
          ).bind(uuid(), t.key, t.duration, t.fps, t.source_prompt ? JSON.stringify([t.source_prompt.slice(0, 80)]) : null, name).run();
        }
        results.time++;
      }
      for (const m of body.motion || []) {
        const existing = await env.DB.prepare("SELECT id FROM learned_motion WHERE profile_key = ?").bind(m.key).first();
        if (existing) {
          await env.DB.prepare("UPDATE learned_motion SET count = count + 1 WHERE profile_key = ?").bind(m.key).run();
        } else {
          const name = await generateUniqueName(env);
          await env.DB.prepare("INSERT INTO name_reserve (name) VALUES (?)").bind(name).run();
          await env.DB.prepare(
            "INSERT INTO learned_motion (id, profile_key, motion_level, motion_std, motion_trend, motion_direction, motion_rhythm, count, sources_json, name) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)"
          ).bind(uuid(), m.key, m.motion_level, m.motion_std, m.motion_trend, m.motion_direction ?? "neutral", m.motion_rhythm ?? "steady", m.source_prompt ? JSON.stringify([m.source_prompt.slice(0, 80)]) : null, name).run();
        }
        results.motion++;
      }
      for (const l of body.lighting || []) {
        const existing = await env.DB.prepare("SELECT id FROM learned_lighting WHERE profile_key = ?").bind(l.key).first();
        if (existing) {
          await env.DB.prepare("UPDATE learned_lighting SET count = count + 1 WHERE profile_key = ?").bind(l.key).run();
        } else {
          const name = await generateUniqueName(env);
          await env.DB.prepare("INSERT INTO name_reserve (name) VALUES (?)").bind(name).run();
          await env.DB.prepare(
            "INSERT INTO learned_lighting (id, profile_key, brightness, contrast, saturation, count, sources_json, name) VALUES (?, ?, ?, ?, ?, 1, ?, ?)"
          ).bind(uuid(), l.key, l.brightness, l.contrast, l.saturation, l.source_prompt ? JSON.stringify([l.source_prompt.slice(0, 80)]) : null, name).run();
        }
        results.lighting++;
      }
      for (const c of body.composition || []) {
        const existing = await env.DB.prepare("SELECT id FROM learned_composition WHERE profile_key = ?").bind(c.key).first();
        if (existing) {
          await env.DB.prepare("UPDATE learned_composition SET count = count + 1 WHERE profile_key = ?").bind(c.key).run();
        } else {
          const name = await generateUniqueName(env);
          await env.DB.prepare("INSERT INTO name_reserve (name) VALUES (?)").bind(name).run();
          await env.DB.prepare(
            "INSERT INTO learned_composition (id, profile_key, center_x, center_y, luminance_balance, count, sources_json, name) VALUES (?, ?, ?, ?, ?, 1, ?, ?)"
          ).bind(uuid(), c.key, c.center_x, c.center_y, c.luminance_balance, c.source_prompt ? JSON.stringify([c.source_prompt.slice(0, 80)]) : null, name).run();
        }
        results.composition++;
      }
      for (const g of body.graphics || []) {
        const existing = await env.DB.prepare("SELECT id FROM learned_graphics WHERE profile_key = ?").bind(g.key).first();
        if (existing) {
          await env.DB.prepare("UPDATE learned_graphics SET count = count + 1 WHERE profile_key = ?").bind(g.key).run();
        } else {
          const name = await generateUniqueName(env);
          await env.DB.prepare("INSERT INTO name_reserve (name) VALUES (?)").bind(name).run();
          await env.DB.prepare(
            "INSERT INTO learned_graphics (id, profile_key, edge_density, spatial_variance, busyness, count, sources_json, name) VALUES (?, ?, ?, ?, ?, 1, ?, ?)"
          ).bind(uuid(), g.key, g.edge_density, g.spatial_variance, g.busyness, g.source_prompt ? JSON.stringify([g.source_prompt.slice(0, 80)]) : null, name).run();
        }
        results.graphics++;
      }
      for (const t of body.temporal || []) {
        const existing = await env.DB.prepare("SELECT id FROM learned_temporal WHERE profile_key = ?").bind(t.key).first();
        if (existing) {
          await env.DB.prepare("UPDATE learned_temporal SET count = count + 1 WHERE profile_key = ?").bind(t.key).run();
        } else {
          const name = await generateUniqueName(env);
          await env.DB.prepare("INSERT INTO name_reserve (name) VALUES (?)").bind(name).run();
          await env.DB.prepare(
            "INSERT INTO learned_temporal (id, profile_key, duration, motion_trend, count, sources_json, name) VALUES (?, ?, ?, ?, 1, ?, ?)"
          ).bind(uuid(), t.key, t.duration, t.motion_trend, t.source_prompt ? JSON.stringify([t.source_prompt.slice(0, 80)]) : null, name).run();
        }
        results.temporal++;
      }
      for (const t of body.technical || []) {
        const existing = await env.DB.prepare("SELECT id FROM learned_technical WHERE profile_key = ?").bind(t.key).first();
        if (existing) {
          await env.DB.prepare("UPDATE learned_technical SET count = count + 1 WHERE profile_key = ?").bind(t.key).run();
        } else {
          const name = await generateUniqueName(env);
          await env.DB.prepare("INSERT INTO name_reserve (name) VALUES (?)").bind(name).run();
          await env.DB.prepare(
            "INSERT INTO learned_technical (id, profile_key, width, height, fps, count, sources_json, name) VALUES (?, ?, ?, ?, ?, 1, ?, ?)"
          ).bind(uuid(), t.key, t.width, t.height, t.fps, t.source_prompt ? JSON.stringify([t.source_prompt.slice(0, 80)]) : null, name).run();
        }
        results.technical++;
      }
      for (const a of body.audio_semantic || []) {
        const existing = await env.DB.prepare("SELECT id FROM learned_audio_semantic WHERE profile_key = ?").bind(a.key).first();
        if (existing) {
          await env.DB.prepare("UPDATE learned_audio_semantic SET count = count + 1 WHERE profile_key = ?").bind(a.key).run();
        } else {
          const name = (a.name && a.name.trim()) ? a.name : await generateUniqueName(env);
          if (!a.name || !a.name.trim()) await env.DB.prepare("INSERT INTO name_reserve (name) VALUES (?)").bind(name).run();
          await env.DB.prepare(
            "INSERT INTO learned_audio_semantic (id, profile_key, role, count, sources_json, name) VALUES (?, ?, ?, 1, ?, ?)"
          ).bind(uuid(), a.key, a.role || "ambient", a.source_prompt ? JSON.stringify([a.source_prompt.slice(0, 80)]) : null, name).run();
        }
        results.audio_semantic++;
      }
      for (const g of body.gradient || []) {
        const existing = await env.DB.prepare("SELECT id FROM learned_gradient WHERE profile_key = ?").bind(g.key).first();
        if (existing) {
          await env.DB.prepare("UPDATE learned_gradient SET count = count + 1 WHERE profile_key = ?").bind(g.key).run();
        } else {
          const name = await generateUniqueName(env);
          await env.DB.prepare("INSERT INTO name_reserve (name) VALUES (?)").bind(name).run();
          await env.DB.prepare(
            "INSERT INTO learned_gradient (id, profile_key, gradient_type, strength, count, sources_json, name) VALUES (?, ?, ?, ?, 1, ?, ?)"
          ).bind(uuid(), g.key, g.gradient_type ?? "angled", g.strength ?? null, g.source_prompt ? JSON.stringify([g.source_prompt.slice(0, 80)]) : null, name).run();
        }
        results.gradient++;
      }
      for (const c of body.camera || []) {
        const existing = await env.DB.prepare("SELECT id FROM learned_camera WHERE profile_key = ?").bind(c.key).first();
        if (existing) {
          await env.DB.prepare("UPDATE learned_camera SET count = count + 1 WHERE profile_key = ?").bind(c.key).run();
        } else {
          const name = await generateUniqueName(env);
          await env.DB.prepare("INSERT INTO name_reserve (name) VALUES (?)").bind(name).run();
          await env.DB.prepare(
            "INSERT INTO learned_camera (id, profile_key, motion_type, speed, count, sources_json, name) VALUES (?, ?, ?, ?, 1, ?, ?)"
          ).bind(uuid(), c.key, c.motion_type ?? "static", c.speed ?? null, c.source_prompt ? JSON.stringify([c.source_prompt.slice(0, 80)]) : null, name).run();
        }
        results.camera++;
      }
      const totalResults = Object.values(results).reduce((a, b) => a + b, 0);
      const jobId = typeof (body as { job_id?: string }).job_id === "string" ? (body as { job_id: string }).job_id.trim() : null;
      if (jobId && totalResults > 0) {
        try {
          await env.DB.prepare("INSERT INTO discovery_runs (id, job_id) VALUES (?, ?)")
            .bind(uuid(), jobId).run();
        } catch {
          // Ignore duplicate or missing table
        }
      }
      // Do not use KV delete (free tier limit). Stats cache expires via TTL; GET recomputes when stale.
      return json({ status: "recorded", results }, 201);
      } catch (e) {
        console.error("POST /api/knowledge/discoveries failed:", e);
        return json({ error: "Failed to record discoveries", details: String(e) }, 500);
      }
    }

    // GET /api/knowledge/colors — check if color key exists (for novelty check)
    if (path === "/api/knowledge/colors" && request.method === "GET") {
      const key = new URL(request.url).searchParams.get("key");
      if (!key) return err("key required");
      const row = await env.DB.prepare("SELECT color_key FROM learned_colors WHERE color_key = ?").bind(key).first();
      return json({ exists: !!row });
    }

    // GET /api/knowledge/for-creation — learned colors and motion for creation (closes the loop)
    if (path === "/api/knowledge/for-creation" && request.method === "GET") {
      try {
      const limit = Math.min(parseInt(new URL(request.url).searchParams.get("limit") || "500", 10), 2000);
      const colorRows = await env.DB.prepare(
        "SELECT color_key, r, g, b, count, sources_json, name FROM learned_colors ORDER BY count DESC LIMIT ?"
      )
        .bind(limit)
        .all<{ color_key: string; r: number; g: number; b: number; count: number; sources_json: string | null; name: string }>();
      const colors: Record<string, { r: number; g: number; b: number; count: number; sources: string[]; name: string }> = {};
      for (const r of colorRows.results || []) {
        colors[r.color_key] = {
          r: r.r,
          g: r.g,
          b: r.b,
          count: r.count,
          sources: r.sources_json ? (JSON.parse(r.sources_json) as string[]) : [],
          name: r.name,
        };
      }
      const motionRows = await env.DB.prepare(
        "SELECT profile_key, motion_level, motion_std, motion_trend, count, sources_json, name FROM learned_motion ORDER BY count DESC LIMIT ?"
      )
        .bind(limit)
        .all<{ profile_key: string; motion_level: number; motion_std: number; motion_trend: string; count: number; sources_json: string | null; name: string | null }>();
      const motion = (motionRows.results || []).map((r) => ({
        key: r.profile_key,
        motion_level: r.motion_level,
        motion_std: r.motion_std,
        motion_trend: r.motion_trend,
        count: r.count,
        sources: r.sources_json ? (JSON.parse(r.sources_json) as string[]) : [],
        name: r.name,
      }));
      const audioRows = await env.DB.prepare(
        "SELECT domain, inputs_json, output_json, source_prompt, created_at FROM learned_blends WHERE domain = 'audio' ORDER BY created_at DESC LIMIT ?"
      )
        .bind(limit)
        .all<{ domain: string; inputs_json: string; output_json: string; source_prompt: string | null; created_at: string }>();
      const learned_audio = (audioRows.results || []).map((r) => ({
        tempo: (JSON.parse(r.output_json) as Record<string, unknown>).tempo ?? "medium",
        mood: (JSON.parse(r.output_json) as Record<string, unknown>).mood ?? "neutral",
        presence: (JSON.parse(r.output_json) as Record<string, unknown>).presence ?? "ambient",
        source_prompt: r.source_prompt ?? "",
      }));
      // Gradient and camera from learned_blends (growth from spec) — creation picks from STATIC/registry
      const gradientSeen = new Set<string>();
      const learned_gradient: string[] = [];
      const gradientBlendRows = await env.DB.prepare(
        "SELECT output_json FROM learned_blends WHERE domain = 'gradient' ORDER BY created_at DESC LIMIT ?"
      )
        .bind(limit)
        .all<{ output_json: string }>();
      for (const r of gradientBlendRows.results || []) {
        const out = JSON.parse(r.output_json) as Record<string, unknown>;
        const v = typeof out.gradient_type === "string" ? out.gradient_type.trim() : "";
        if (v && !gradientSeen.has(v)) {
          gradientSeen.add(v);
          learned_gradient.push(v);
        }
      }
      const gradientTableRows = await env.DB.prepare(
        "SELECT gradient_type FROM learned_gradient ORDER BY count DESC LIMIT ?"
      )
        .bind(limit)
        .all<{ gradient_type: string }>();
      for (const r of gradientTableRows.results || []) {
        const v = (r.gradient_type || "").trim();
        if (v && !gradientSeen.has(v)) {
          gradientSeen.add(v);
          learned_gradient.push(v);
        }
      }
      const cameraSeen = new Set<string>();
      const learned_camera: string[] = [];
      const cameraBlendRows = await env.DB.prepare(
        "SELECT output_json FROM learned_blends WHERE domain = 'camera' ORDER BY created_at DESC LIMIT ?"
      )
        .bind(limit)
        .all<{ output_json: string }>();
      for (const r of cameraBlendRows.results || []) {
        const out = JSON.parse(r.output_json) as Record<string, unknown>;
        const v = typeof out.camera_motion === "string" ? out.camera_motion.trim() : "";
        if (v && !cameraSeen.has(v)) {
          cameraSeen.add(v);
          learned_camera.push(v);
        }
      }
      const cameraTableRows = await env.DB.prepare(
        "SELECT motion_type FROM learned_camera ORDER BY count DESC LIMIT ?"
      )
        .bind(limit)
        .all<{ motion_type: string }>();
      for (const r of cameraTableRows.results || []) {
        const v = (r.motion_type || "").trim();
        if (v && !cameraSeen.has(v)) {
          cameraSeen.add(v);
          learned_camera.push(v);
        }
      }
      // Canonical non-pure (multi-frame) options — gradient/camera/motion are non-pure; creation uses these when registry empty
      const origin_gradient = ["vertical", "horizontal", "radial", "angled"];
      const origin_camera = ["static", "pan", "tilt", "dolly", "crane", "zoom", "zoom_out", "handheld", "roll", "truck", "pedestal", "arc", "tracking", "birds_eye", "whip_pan", "rotate"];
      const origin_motion = ["slow", "wave", "flow", "fast", "pulse"];
      // Interpretation registry: user prompts + resolved instructions (for creation / pick_prompt)
      const interpLimit = Math.min(parseInt(new URL(request.url).searchParams.get("interpretation_limit") || "100", 10), 500);
      const interpRows = await env.DB.prepare(
        "SELECT prompt, instruction_json FROM interpretations WHERE status = 'done' AND instruction_json IS NOT NULL ORDER BY updated_at DESC LIMIT ?"
      )
        .bind(interpLimit)
        .all<{ prompt: string; instruction_json: string }>();
      const interpretation_prompts = (interpRows.results || []).map((r) => ({
        prompt: r.prompt,
        instruction: r.instruction_json ? (JSON.parse(r.instruction_json) as Record<string, unknown>) : {},
      }));
      return json({
        learned_colors: colors,
        learned_motion: motion,
        learned_audio,
        learned_gradient,
        learned_camera,
        origin_gradient,
        origin_camera,
        origin_motion,
        interpretation_prompts,
      });
      } catch (e) {
        console.error("GET /api/knowledge/for-creation failed:", e);
        return json({ error: "Failed to load for-creation", details: String(e) }, 500);
      }
    }

    // GET /api/registries — pure (STATIC) vs non-pure (DYNAMIC + NARRATIVE); depth % vs primitives always
    // Pure = single frame/pixel (static). Non-pure = multi-frame blends (gradient, motion, camera → dynamic).
    if (path === "/api/registries" && request.method === "GET") {
      const regLimit = Math.min(parseInt(new URL(request.url).searchParams.get("limit") || "200", 10), 500);
      // Pure primitives — must match static_registry.py and REGISTRY_FOUNDATION (full origin set for UI)
      const staticPrimitives = {
        color_primaries: [
          { name: "black", r: 0, g: 0, b: 0 },
          { name: "white", r: 255, g: 255, b: 255 },
          { name: "red", r: 255, g: 0, b: 0 },
          { name: "green", r: 0, g: 255, b: 0 },
          { name: "blue", r: 0, g: 0, b: 255 },
          { name: "yellow", r: 255, g: 255, b: 0 },
          { name: "cyan", r: 0, g: 255, b: 255 },
          { name: "magenta", r: 255, g: 0, b: 255 },
          { name: "orange", r: 255, g: 165, b: 0 },
          { name: "purple", r: 128, g: 0, b: 128 },
          { name: "pink", r: 255, g: 192, b: 203 },
          { name: "brown", r: 165, g: 42, b: 42 },
          { name: "navy", r: 0, g: 0, b: 128 },
          { name: "gray", r: 128, g: 128, b: 128 },
          { name: "olive", r: 128, g: 128, b: 0 },
          { name: "teal", r: 0, g: 128, b: 128 },
        ],
        sound_primaries: ["silence", "rumble", "tone", "hiss"],
      };
      // Blended canonical — must match origins.py (gradient_type, camera motion_type, motion speed+rhythm, audio tempo/mood/presence)
      const dynamicCanonical = {
        gradient_type: ["vertical", "horizontal", "radial", "angled"],
        camera_motion: ["static", "pan", "tilt", "dolly", "crane", "zoom", "zoom_out", "handheld", "roll", "truck", "pedestal", "arc", "tracking", "birds_eye", "whip_pan", "rotate"],
        motion: ["static", "slow", "medium", "fast", "steady", "pulsing", "wave", "random"],
        sound: ["tempo: slow", "tempo: medium", "tempo: fast", "mood: neutral", "mood: calm", "mood: tense", "mood: uplifting", "mood: dark", "presence: silence", "presence: ambient", "presence: music", "presence: sfx", "presence: full"],
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
      const staticColors = await env.DB.prepare(
        "SELECT color_key, r, g, b, name, count, depth_breakdown_json FROM static_colors ORDER BY count DESC LIMIT ?"
      ).bind(regLimit).all<{ color_key: string; r: number; g: number; b: number; name: string; count: number; depth_breakdown_json: string | null }>();
      const staticSound = await env.DB.prepare(
        "SELECT sound_key, name, count, depth_breakdown_json, strength_pct FROM static_sound ORDER BY count DESC LIMIT ?"
      ).bind(regLimit).all<{ sound_key: string; name: string; count: number; depth_breakdown_json: string | null; strength_pct: number | null }>();
      const learnedColors = await env.DB.prepare(
        "SELECT color_key, r, g, b, name, count FROM learned_colors ORDER BY count DESC LIMIT ?"
      ).bind(regLimit).all<{ color_key: string; r: number; g: number; b: number; name: string; count: number }>();
      const learnedMotion = await env.DB.prepare(
        "SELECT profile_key, motion_trend, name, count FROM learned_motion ORDER BY count DESC LIMIT ?"
      ).bind(regLimit).all<{ profile_key: string; motion_trend: string; name: string | null; count: number }>();
      const blends = await env.DB.prepare(
        "SELECT name, domain, output_json, primitive_depths_json FROM learned_blends ORDER BY created_at DESC LIMIT ?"
      ).bind(regLimit).all<{ name: string; domain: string; output_json: string; primitive_depths_json: string | null }>();
      const narrativeAspects = ["genre", "mood", "themes", "plots", "settings", "style", "scene_type"];
      const narrative: Record<string, Array<{ entry_key: string; value: string; name: string; count: number }>> = {};
      for (const aspect of narrativeAspects) {
        const rows = await env.DB.prepare(
          "SELECT entry_key, value, name, count FROM narrative_entries WHERE aspect = ? ORDER BY count DESC LIMIT ?"
        ).bind(aspect, regLimit).all<{ entry_key: string; value: string | null; name: string; count: number }>();
        narrative[aspect] = (rows.results || []).map((r) => ({
          entry_key: r.entry_key,
          value: r.value || r.entry_key,
          name: r.name,
          count: r.count,
        }));
      }
      const interpretationRows = await env.DB.prepare(
        "SELECT id, prompt, instruction_json, updated_at FROM interpretations WHERE status = 'done' AND instruction_json IS NOT NULL ORDER BY updated_at DESC LIMIT ?"
      ).bind(Math.min(regLimit, 100)).all<{ id: string; prompt: string; instruction_json: string; updated_at: string }>();
      const interpretation = (interpretationRows.results || []).map((r) => ({
        id: r.id,
        prompt: r.prompt,
        instruction: r.instruction_json ? (JSON.parse(r.instruction_json) as Record<string, unknown>) : null,
        updated_at: r.updated_at,
      }));
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
      const gradientBlends = (blends.results || []).filter((b) => b.domain === "gradient").map((b) => {
        const out = JSON.parse(b.output_json) as Record<string, unknown>;
        const depths = b.primitive_depths_json ? (JSON.parse(b.primitive_depths_json) as Record<string, unknown>) : null;
        const { depth_pct, depth_breakdown } = depthFromBlendDepths(depths);
        return { name: b.name, key: String(out.gradient_type ?? b.domain), depth_pct, depth_breakdown };
      });
      const cameraBlends = (blends.results || []).filter((b) => b.domain === "camera").map((b) => {
        const out = JSON.parse(b.output_json) as Record<string, unknown>;
        const depths = b.primitive_depths_json ? (JSON.parse(b.primitive_depths_json) as Record<string, unknown>) : null;
        const { depth_pct, depth_breakdown } = depthFromBlendDepths(depths);
        return { name: b.name, key: String(out.camera_motion ?? b.domain), depth_pct, depth_breakdown };
      });
      const audioBlends = (blends.results || []).filter((b) => b.domain === "audio").map((b) => {
        const out = JSON.parse(b.output_json) as Record<string, unknown>;
        const depths = b.primitive_depths_json ? (JSON.parse(b.primitive_depths_json) as Record<string, unknown>) : null;
        const { depth_pct, depth_breakdown } = depthFromBlendDepths(depths);
        const key = [out.tempo, out.mood, out.presence].filter(Boolean).join(" / ") || b.output_json.slice(0, 60);
        return { name: b.name, key, tempo: out.tempo, mood: out.mood, presence: out.presence, depth_pct, depth_breakdown };
      });
      const otherBlends = (blends.results || []).filter((b) => b.domain !== "gradient" && b.domain !== "camera" && b.domain !== "audio").map((b) => {
        const depths = b.primitive_depths_json ? (JSON.parse(b.primitive_depths_json) as Record<string, unknown>) : null;
        const { depth_pct, depth_breakdown } = depthFromBlendDepths(depths);
        return { name: b.name, domain: b.domain, key: b.output_json.slice(0, 80), depth_pct, depth_breakdown };
      });
      return json({
        static_primitives: staticPrimitives,
        dynamic_canonical: dynamicCanonical,
        static: {
          colors: (staticColors.results || []).map((r) => {
            let depth_pct: number;
            let depth_breakdown: Record<string, number>;
            if (r.depth_breakdown_json) {
              try {
                const stored = JSON.parse(r.depth_breakdown_json) as Record<string, unknown>;
                depth_breakdown = {};
                for (const [k, v] of Object.entries(stored)) {
                  if (typeof v === "number") depth_breakdown[k] = v;
                }
                depth_pct = Object.keys(depth_breakdown).length ? 100 : 0;
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
            return { key: r.color_key, r: r.r, g: r.g, b: r.b, name: r.name, count: r.count, depth_pct, depth_breakdown };
          }),
          sound: (staticSound.results || []).map((r) => {
            const depth_breakdown = r.depth_breakdown_json ? (JSON.parse(r.depth_breakdown_json) as Record<string, unknown>) : undefined;
            return { key: r.sound_key, name: r.name, count: r.count, strength_pct: r.strength_pct ?? undefined, depth_breakdown };
          }),
        },
        dynamic: {
          colors: (learnedColors.results || []).map((r) => {
            const { depth_pct, depth_breakdown } = colorDepthVsPrimitives(r.r, r.g, r.b);
            return { key: r.color_key, name: r.name, count: r.count, depth_pct, depth_breakdown };
          }),
          motion: (learnedMotion.results || []).map((r) => ({ key: r.profile_key, name: r.name || r.profile_key, trend: r.motion_trend, count: r.count })),
          gradient: gradientBlends,
          camera: cameraBlends,
          sound: audioBlends,
          blends: otherBlends,
        },
        narrative,
        interpretation,
      });
    }

    // GET /api/loop/progress — learning precision (runs with growth in last N)
    if (path === "/api/loop/progress" && request.method === "GET") {
      const last = Math.min(parseInt(new URL(request.url).searchParams.get("last") || "20", 10), 100);
      const completed = await env.DB.prepare(
        "SELECT id FROM jobs WHERE status = 'completed' AND r2_key IS NOT NULL ORDER BY updated_at DESC LIMIT ?"
      ).bind(last).all<{ id: string }>();
      const ids = (completed.results || []).map((r) => r.id);
      let withLearning = 0;
      if (ids.length > 0) {
        const placeholders = ids.map(() => "?").join(",");
        const r = await env.DB.prepare(
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
          const dr = await env.DB.prepare(
            `SELECT COUNT(DISTINCT job_id) as c FROM discovery_runs WHERE job_id IN (${placeholders})`
          ).bind(...ids).first<{ c: number }>();
          withDiscovery = dr?.c ?? 0;
        } catch {
          withDiscovery = 0;
        }
      }
      const discoveryRate = totalRuns > 0 ? Math.round((withDiscovery / totalRuns) * 100) : 0;
      return json({
        last_n: last,
        total_runs: totalRuns,
        runs_with_learning: withLearning,
        precision_pct: precision,
        target_pct: 95,
        runs_with_discovery: withDiscovery,
        discovery_rate_pct: discoveryRate,
      });
    }

    // GET /api/loop/diagnostics — per-job has_learning / has_discovery for debugging precision gap
    if (path === "/api/loop/diagnostics" && request.method === "GET") {
      const last = Math.min(parseInt(new URL(request.url).searchParams.get("last") || "20", 10), 50);
      const completed = await env.DB.prepare(
        "SELECT id, prompt, created_at FROM jobs WHERE status = 'completed' AND r2_key IS NOT NULL ORDER BY updated_at DESC LIMIT ?"
      ).bind(last).all<{ id: string; prompt: string; created_at: string }>();
      const rows = completed.results || [];
      const ids = rows.map((r) => r.id);
      const learningSet = new Set<string>();
      const discoverySet = new Set<string>();
      if (ids.length > 0) {
        const placeholders = ids.map(() => "?").join(",");
        const lr = await env.DB.prepare(`SELECT job_id FROM learning_runs WHERE job_id IN (${placeholders})`).bind(...ids).all<{ job_id: string }>();
        (lr.results || []).forEach((r) => { if (r.job_id) learningSet.add(r.job_id); });
        try {
          const dr = await env.DB.prepare(`SELECT job_id FROM discovery_runs WHERE job_id IN (${placeholders})`).bind(...ids).all<{ job_id: string }>();
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
          hint: missing_learning > 0 ? "Jobs without learning_run: POST /api/learning may have failed or job completed via different path" : null,
        },
      });
    }

  return err("Not found", 404);
}

async function resolveUniqueBlendName(env: Env, base: string): Promise<string> {
  let candidate = base;
  for (let i = 0; i < 100; i++) {
    const inReserve = await env.DB.prepare("SELECT name FROM name_reserve WHERE name = ?").bind(candidate).first();
    const inBlends = await env.DB.prepare("SELECT name FROM learned_blends WHERE name = ?").bind(candidate).first();
    if (!inReserve && !inBlends) return candidate;
    candidate = i === 0 ? base + "2" : base + (i + 2);
  }
  return base + (Math.floor(Math.random() * 9000) + 1000);
}

async function generateUniqueName(env: Env): Promise<string> {
  const CONSONANTS = "blckdrflgrklmnprstvzwxq";
  const VOWELS = "aeiou";
  const invent = (seed: number): string => {
    let r = seed % 100000;
    const parts: string[] = [];
    for (let i = 0; i < 3; i++) {
      parts.push(CONSONANTS[r % CONSONANTS.length]);
      r = Math.floor(r / CONSONANTS.length);
      parts.push(VOWELS[r % VOWELS.length]);
      r = Math.floor(r / VOWELS.length);
    }
    return parts.join("");
  };
  for (let attempt = 0; attempt < 20; attempt++) {
    const seed = Math.floor(Math.random() * 1000000) + attempt * 7919;
    const c1 = invent(seed);
    const c2 = invent(seed + 1237);
    const raw = c1 + c2;
    if (raw.length >= 5) {
      const name = raw[0].toUpperCase() + raw.slice(1).toLowerCase();
      const inReserve = await env.DB.prepare("SELECT name FROM name_reserve WHERE name = ?").bind(name).first();
      const inBlends = await env.DB.prepare("SELECT name FROM learned_blends WHERE name = ?").bind(name).first();
      if (!inReserve && !inBlends) return name;
    }
  }
  const n = (Math.floor(Math.random() * 100000) + 1) % 100000;
  return "Novel" + n.toString().padStart(5, "0");
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
