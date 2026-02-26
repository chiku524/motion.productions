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
    if (path === "/health" || path === "/api/health") {
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
      // Prioritize user-submitted (web) over worker-enqueued
      const rows = await env.DB.prepare(
        "SELECT id, prompt, source, created_at FROM interpretations WHERE status = 'pending' ORDER BY CASE WHEN source = 'web' THEN 0 ELSE 1 END, created_at ASC LIMIT ?"
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
        .bind(limit * 2)
        .all<{ prompt: string }>();
      const raw = (rows.results || []).map((r) => r.prompt);
      const prompts = raw.filter((p) => !isGibberishPrompt(p, true)).slice(0, limit);
      return json({ prompts });
    }

    // POST /api/interpretations/batch — store multiple completed interpretations (batch backfill)
    if (path === "/api/interpretations/batch" && request.method === "POST") {
      let body: { items: Array<{ prompt: string; instruction: Record<string, unknown>; source?: string }> };
      try {
        body = (await request.json()) as typeof body;
      } catch {
        return err("Invalid JSON");
      }
      const items = Array.isArray(body.items) ? body.items : [];
      if (items.length === 0) return json({ inserted: 0 });
      const maxBatch = 50;
      const toInsert = items.slice(0, maxBatch);
      let inserted = 0;
      for (const it of toInsert) {
        const prompt = typeof it.prompt === "string" ? it.prompt.trim() : "";
        if (!prompt) continue;
        if (isGibberishPrompt(prompt, true)) continue;
        const instruction = it.instruction && typeof it.instruction === "object" ? it.instruction : null;
        if (!instruction) continue;
        const source = typeof it.source === "string" && /^(web|worker|loop|backfill)$/.test(it.source) ? it.source : "backfill";
        const id = uuid();
        try {
          await env.DB.prepare(
            "INSERT INTO interpretations (id, prompt, instruction_json, source, status) VALUES (?, ?, ?, ?, 'done')"
          )
            .bind(id, prompt, JSON.stringify(instruction), source)
            .run();
          inserted++;
        } catch {
          // Skip duplicate or constraint error
        }
      }
      return json({ inserted }, inserted > 0 ? 201 : 200);
    }

    // GET /api/linguistic-registry — fetch all mappings for interpretation (span -> canonical by domain)
    if (path === "/api/linguistic-registry" && request.method === "GET") {
      try {
        const domain = new URL(request.url).searchParams.get("domain");
        const q = domain
          ? "SELECT span, canonical, domain, variant_type, count FROM linguistic_registry WHERE domain = ?"
          : "SELECT span, canonical, domain, variant_type, count FROM linguistic_registry";
        const stmt = domain ? env.DB.prepare(q).bind(domain) : env.DB.prepare(q);
        const rows = await stmt.all<{ span: string; canonical: string; domain: string; variant_type: string; count: number }>();
        const mappings = (rows.results || []).map((r) => ({
          span: r.span,
          canonical: r.canonical,
          domain: r.domain,
          variant_type: r.variant_type,
          count: r.count,
        }));
        return json({ mappings });
      } catch {
        return json({ mappings: [] });
      }
    }

    // POST /api/linguistic-registry/batch — add mappings from extraction (upsert: increment count if exists)
    if (path === "/api/linguistic-registry/batch" && request.method === "POST") {
      let body: { items: Array<{ span: string; canonical: string; domain: string; variant_type?: string }> };
      try {
        body = (await request.json()) as typeof body;
      } catch {
        return err("Invalid JSON");
      }
      const items = Array.isArray(body.items) ? body.items : [];
      if (items.length === 0) return json({ inserted: 0, updated: 0 });
      let inserted = 0;
      let updated = 0;
      for (const it of items.slice(0, 100)) {
        const span = typeof it.span === "string" ? it.span.trim().toLowerCase() : "";
        const canonical = typeof it.canonical === "string" ? it.canonical.trim() : "";
        const domain = typeof it.domain === "string" ? it.domain.trim() : "";
        const variantType = typeof it.variant_type === "string" ? it.variant_type : "synonym";
        if (!span || !canonical || !domain) continue;
        try {
          const existing = await env.DB.prepare("SELECT id, count FROM linguistic_registry WHERE span = ? AND domain = ?")
            .bind(span, domain)
            .first<{ id: string; count: number }>();
          if (existing) {
            await env.DB.prepare("UPDATE linguistic_registry SET count = count + 1, updated_at = datetime('now') WHERE span = ? AND domain = ?")
              .bind(span, domain)
              .run();
            updated++;
          } else {
            await env.DB.prepare(
              "INSERT INTO linguistic_registry (id, span, canonical, domain, variant_type, count) VALUES (?, ?, ?, ?, ?, 1)"
            )
              .bind(uuid(), span, canonical, domain, variantType)
              .run();
            inserted++;
          }
        } catch {
          // Skip on duplicate or missing table
        }
      }
      return json({ inserted, updated }, inserted > 0 || updated > 0 ? 201 : 200);
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
      const source = typeof body.source === "string" && /^(web|worker|loop|backfill|generate)$/.test(body.source) ? body.source : "worker";
      // Gibberish check: skip for source "loop" so every video run is recorded (interpretation registry grows from main workers)
      if (source !== "loop" && isGibberishPrompt(prompt, true)) return err("prompt appears to be gibberish; interpretation registry requires meaningful prompts");
      const instruction = body.instruction && typeof body.instruction === "object" ? body.instruction : null;
      if (!instruction) return err("instruction is required");
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
    // D1 Free plan: 50 queries/request. ~3 queries/item. Max 14 items per request to stay under limit.
    if (path === "/api/knowledge/discoveries" && request.method === "POST") {
      const DISCOVERIES_MAX_ITEMS = 14;
      let body: {
        static_colors?: Array<{ key: string; r: number; g: number; b: number; brightness?: number; luminance?: number; contrast?: number; saturation?: number; chroma?: number; hue?: number; color_variance?: number; opacity?: number; depth_breakdown?: Record<string, unknown>; source_prompt?: string; name?: string }>;
        static_sound?: Array<{ key: string; amplitude?: number; weight?: number; strength_pct?: number; tone?: string; timbre?: string; depth_breakdown?: Record<string, unknown>; source_prompt?: string; name?: string }>;
        colors?: Array<{ key: string; r: number; g: number; b: number; source_prompt?: string }>;
        blends?: Array<{ name: string; domain: string; inputs: Record<string, unknown>; output: Record<string, unknown>; primitive_depths?: Record<string, unknown>; source_prompt?: string }>;
        motion?: Array<{ key: string; motion_level: number; motion_std: number; motion_trend: string; motion_direction?: string; motion_rhythm?: string; depth_breakdown?: Record<string, unknown>; source_prompt?: string }>;
        lighting?: Array<{ key: string; brightness: number; contrast: number; saturation: number; depth_breakdown?: Record<string, unknown>; source_prompt?: string }>;
        composition?: Array<{ key: string; center_x: number; center_y: number; luminance_balance: number; source_prompt?: string }>;
        graphics?: Array<{ key: string; edge_density: number; spatial_variance: number; busyness: number; source_prompt?: string }>;
        temporal?: Array<{ key: string; duration: number; motion_trend: string; source_prompt?: string }>;
        technical?: Array<{ key: string; width: number; height: number; fps: number; source_prompt?: string }>;
        audio_semantic?: Array<{ key: string; role: string; mood?: string; tempo?: string; source_prompt?: string; name?: string }>;
        time?: Array<{ key: string; duration: number; fps: number; source_prompt?: string }>;
        gradient?: Array<{ key: string; gradient_type: string; strength?: number; depth_breakdown?: Record<string, unknown>; source_prompt?: string }>;
        camera?: Array<{ key: string; motion_type: string; speed?: string; depth_breakdown?: Record<string, unknown>; source_prompt?: string }>;
        transition?: Array<{ key: string; type: string; duration_seconds?: number; source_prompt?: string }>;
        depth?: Array<{ key: string; parallax_strength?: number; layer_count?: number; source_prompt?: string }>;
        narrative?: Record<string, Array<{ key: string; value?: string; source_prompt?: string; name?: string }>>;
        job_id?: string;
      };
      try {
        body = (await request.json()) as typeof body;
      } catch {
        return err("Invalid JSON");
      }
      const results: Record<string, number> = { static_colors: 0, static_sound: 0, narrative: 0, colors: 0, blends: 0, motion: 0, lighting: 0, composition: 0, graphics: 0, temporal: 0, technical: 0, audio_semantic: 0, time: 0, gradient: 0, camera: 0, transition: 0, depth: 0 };
      let itemsProcessed = 0;
      let truncated = false;

      try {
      // Static registry: per-frame color entries
      for (const c of body.static_colors || []) {
        if (itemsProcessed >= DISCOVERIES_MAX_ITEMS) { truncated = true; break; }
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
        itemsProcessed++;
      }
      // Static registry: per-frame sound entries
      for (const s of body.static_sound || []) {
        if (itemsProcessed >= DISCOVERIES_MAX_ITEMS) { truncated = true; break; }
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
        itemsProcessed++;
      }
      // Narrative registry: themes, plots, settings, genre, mood, scene_type
      const narrativeAspects = ["genre", "mood", "plots", "settings", "themes", "style", "scene_type"];
      narrative_loop: for (const aspect of narrativeAspects) {
        for (const item of body.narrative?.[aspect] || []) {
          if (itemsProcessed >= DISCOVERIES_MAX_ITEMS) { truncated = true; break narrative_loop; }
          const key = (item.key || "").trim().toLowerCase();
          if (!key) continue;
          const existing = await env.DB.prepare("SELECT id, name, count FROM narrative_entries WHERE aspect = ? AND entry_key = ?").bind(aspect, key).first();
          if (existing) {
            await env.DB.prepare("UPDATE narrative_entries SET count = count + 1 WHERE aspect = ? AND entry_key = ?").bind(aspect, key).run();
          } else {
            const valueStr = (item.value ?? item.key ?? key).slice(0, 200);
            const name = (item.name && item.name.trim()) ? item.name.trim() : (valueStr || (await generateUniqueName(env)));
            if (!(item.name && item.name.trim())) await env.DB.prepare("INSERT INTO name_reserve (name) VALUES (?)").bind(name).run();
            await env.DB.prepare(
              "INSERT INTO narrative_entries (id, aspect, entry_key, value, count, sources_json, name) VALUES (?, ?, ?, ?, 1, ?, ?)"
            ).bind(uuid(), aspect, key, valueStr, item.source_prompt ? JSON.stringify([item.source_prompt.slice(0, 80)]) : null, name).run();
          }
          results.narrative++;
          itemsProcessed++;
        }
      }
      for (const c of body.colors || []) {
        if (itemsProcessed >= DISCOVERIES_MAX_ITEMS) { truncated = true; break; }
        const existing = await env.DB.prepare("SELECT id, name, count FROM learned_colors WHERE color_key = ?").bind(c.key).first();
        const depthJson = c.depth_breakdown && typeof c.depth_breakdown === "object" ? JSON.stringify(c.depth_breakdown) : null;
        if (existing) {
          await env.DB.prepare("UPDATE learned_colors SET count = count + 1 WHERE color_key = ?").bind(c.key).run();
          if (depthJson) {
            await env.DB.prepare("UPDATE learned_colors SET depth_breakdown_json = ? WHERE color_key = ?").bind(depthJson, c.key).run();
          }
        } else {
          const name = (c.name && String(c.name).trim()) || await generateUniqueName(env);
          if (!c.name || !String(c.name).trim()) await env.DB.prepare("INSERT INTO name_reserve (name) VALUES (?)").bind(name).run();
          await env.DB.prepare(
            "INSERT INTO learned_colors (id, color_key, r, g, b, count, sources_json, name, depth_breakdown_json) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)"
          ).bind(uuid(), c.key, c.r, c.g, c.b, c.source_prompt ? JSON.stringify([c.source_prompt.slice(0, 80)]) : null, name, depthJson).run();
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
          await env.DB.prepare("INSERT INTO name_reserve (name) VALUES (?)").bind(name).run();
        }
        await env.DB.prepare(
          "INSERT INTO learned_blends (id, name, domain, inputs_json, output_json, primitive_depths_json, source_prompt) VALUES (?, ?, ?, ?, ?, ?, ?)"
        ).bind(uuid(), name, b.domain, JSON.stringify(b.inputs), JSON.stringify(b.output), b.primitive_depths ? JSON.stringify(b.primitive_depths) : null, (b.source_prompt || "").slice(0, 120)).run();
        results.blends++;
        itemsProcessed++;
      }
      for (const t of body.time || []) {
        if (itemsProcessed >= DISCOVERIES_MAX_ITEMS) { truncated = true; break; }
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
        itemsProcessed++;
      }
      for (const m of body.motion || []) {
        if (itemsProcessed >= DISCOVERIES_MAX_ITEMS) { truncated = true; break; }
        const existing = await env.DB.prepare("SELECT id FROM learned_motion WHERE profile_key = ?").bind(m.key).first();
        if (existing) {
          await env.DB.prepare("UPDATE learned_motion SET count = count + 1 WHERE profile_key = ?").bind(m.key).run();
        } else {
          const name = await generateUniqueName(env);
          await env.DB.prepare("INSERT INTO name_reserve (name) VALUES (?)").bind(name).run();
          await env.DB.prepare(
            "INSERT INTO learned_motion (id, profile_key, motion_level, motion_std, motion_trend, motion_direction, motion_rhythm, count, sources_json, name, depth_breakdown_json) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)"
          ).bind(uuid(), m.key, m.motion_level, m.motion_std, m.motion_trend, m.motion_direction ?? "neutral", m.motion_rhythm ?? "steady", m.source_prompt ? JSON.stringify([m.source_prompt.slice(0, 80)]) : null, name, m.depth_breakdown ? JSON.stringify(m.depth_breakdown) : null).run();
        }
        results.motion++;
        itemsProcessed++;
      }
      for (const l of body.lighting || []) {
        if (itemsProcessed >= DISCOVERIES_MAX_ITEMS) { truncated = true; break; }
        const existing = await env.DB.prepare("SELECT id FROM learned_lighting WHERE profile_key = ?").bind(l.key).first();
        if (existing) {
          await env.DB.prepare("UPDATE learned_lighting SET count = count + 1 WHERE profile_key = ?").bind(l.key).run();
        } else {
          const name = await generateUniqueName(env);
          await env.DB.prepare("INSERT INTO name_reserve (name) VALUES (?)").bind(name).run();
          await env.DB.prepare(
            "INSERT INTO learned_lighting (id, profile_key, brightness, contrast, saturation, count, sources_json, name, depth_breakdown_json) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)"
          ).bind(uuid(), l.key, l.brightness, l.contrast, l.saturation, l.source_prompt ? JSON.stringify([l.source_prompt.slice(0, 80)]) : null, name, l.depth_breakdown ? JSON.stringify(l.depth_breakdown) : null).run();
        }
        results.lighting++;
        itemsProcessed++;
      }
      for (const c of body.composition || []) {
        if (itemsProcessed >= DISCOVERIES_MAX_ITEMS) { truncated = true; break; }
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
        itemsProcessed++;
      }
      for (const g of body.graphics || []) {
        if (itemsProcessed >= DISCOVERIES_MAX_ITEMS) { truncated = true; break; }
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
        itemsProcessed++;
      }
      for (const t of body.temporal || []) {
        if (itemsProcessed >= DISCOVERIES_MAX_ITEMS) { truncated = true; break; }
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
        itemsProcessed++;
      }
      for (const t of body.technical || []) {
        if (itemsProcessed >= DISCOVERIES_MAX_ITEMS) { truncated = true; break; }
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
        itemsProcessed++;
      }
      for (const a of body.audio_semantic || []) {
        if (itemsProcessed >= DISCOVERIES_MAX_ITEMS) { truncated = true; break; }
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
        itemsProcessed++;
      }
      for (const g of body.gradient || []) {
        if (itemsProcessed >= DISCOVERIES_MAX_ITEMS) { truncated = true; break; }
        const existing = await env.DB.prepare("SELECT id FROM learned_gradient WHERE profile_key = ?").bind(g.key).first();
        if (existing) {
          await env.DB.prepare("UPDATE learned_gradient SET count = count + 1 WHERE profile_key = ?").bind(g.key).run();
        } else {
          const name = await generateUniqueName(env);
          await env.DB.prepare("INSERT INTO name_reserve (name) VALUES (?)").bind(name).run();
          await env.DB.prepare(
            "INSERT INTO learned_gradient (id, profile_key, gradient_type, strength, count, sources_json, name, depth_breakdown_json) VALUES (?, ?, ?, ?, 1, ?, ?, ?)"
          ).bind(uuid(), g.key, g.gradient_type ?? "angled", g.strength ?? null, g.source_prompt ? JSON.stringify([g.source_prompt.slice(0, 80)]) : null, name, g.depth_breakdown ? JSON.stringify(g.depth_breakdown) : null).run();
        }
        results.gradient++;
        itemsProcessed++;
      }
      for (const c of body.camera || []) {
        if (itemsProcessed >= DISCOVERIES_MAX_ITEMS) { truncated = true; break; }
        const existing = await env.DB.prepare("SELECT id FROM learned_camera WHERE profile_key = ?").bind(c.key).first();
        if (existing) {
          await env.DB.prepare("UPDATE learned_camera SET count = count + 1 WHERE profile_key = ?").bind(c.key).run();
        } else {
          const name = await generateUniqueName(env);
          await env.DB.prepare("INSERT INTO name_reserve (name) VALUES (?)").bind(name).run();
          await env.DB.prepare(
            "INSERT INTO learned_camera (id, profile_key, motion_type, speed, count, sources_json, name, depth_breakdown_json) VALUES (?, ?, ?, ?, 1, ?, ?, ?)"
          ).bind(uuid(), c.key, c.motion_type ?? "static", c.speed ?? null, c.source_prompt ? JSON.stringify([c.source_prompt.slice(0, 80)]) : null, name, c.depth_breakdown ? JSON.stringify(c.depth_breakdown) : null).run();
        }
        results.camera++;
        itemsProcessed++;
      }
      for (const t of body.transition || []) {
        if (itemsProcessed >= DISCOVERIES_MAX_ITEMS) { truncated = true; break; }
        const existing = await env.DB.prepare("SELECT id FROM learned_transition WHERE profile_key = ?").bind(t.key).first();
        if (existing) {
          await env.DB.prepare("UPDATE learned_transition SET count = count + 1 WHERE profile_key = ?").bind(t.key).run();
        } else {
          const name = await generateUniqueName(env);
          await env.DB.prepare("INSERT INTO name_reserve (name) VALUES (?)").bind(name).run();
          await env.DB.prepare(
            "INSERT INTO learned_transition (id, profile_key, type, duration_seconds, count, sources_json, name) VALUES (?, ?, ?, ?, 1, ?, ?)"
          ).bind(uuid(), t.key, t.type ?? "cut", t.duration_seconds ?? null, t.source_prompt ? JSON.stringify([t.source_prompt.slice(0, 80)]) : null, name).run();
        }
        results.transition++;
        itemsProcessed++;
      }
      for (const d of body.depth || []) {
        if (itemsProcessed >= DISCOVERIES_MAX_ITEMS) { truncated = true; break; }
        const existing = await env.DB.prepare("SELECT id FROM learned_depth WHERE profile_key = ?").bind(d.key).first();
        if (existing) {
          await env.DB.prepare("UPDATE learned_depth SET count = count + 1 WHERE profile_key = ?").bind(d.key).run();
        } else {
          const name = await generateUniqueName(env);
          await env.DB.prepare("INSERT INTO name_reserve (name) VALUES (?)").bind(name).run();
          await env.DB.prepare(
            "INSERT INTO learned_depth (id, profile_key, parallax_strength, layer_count, count, sources_json, name) VALUES (?, ?, ?, ?, 1, ?, ?)"
          ).bind(uuid(), d.key, d.parallax_strength ?? null, d.layer_count ?? null, d.source_prompt ? JSON.stringify([d.source_prompt.slice(0, 80)]) : null, name).run();
        }
        results.depth++;
        itemsProcessed++;
      }
      const totalResults = Object.values(results).reduce((a, b) => a + b, 0);
      const jobId = typeof (body as { job_id?: string }).job_id === "string" ? (body as { job_id: string }).job_id.trim() : null;
      // Record discovery run when job_id present (even if totalResults=0) so diagnostics show "attempted"
      if (jobId) {
        try {
          await env.DB.prepare("INSERT INTO discovery_runs (id, job_id) VALUES (?, ?)")
            .bind(uuid(), jobId).run();
        } catch {
          // Ignore duplicate or missing table
        }
      }
      // Do not use KV delete (free tier limit). Stats cache expires via TTL; GET recomputes when stale.
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
        created_at: r.created_at,
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
      // Pure (static) colors for random-per-pixel creation: origin + discovered per-frame colors (include count for underused bias)
      const staticColorRows = await env.DB.prepare(
        "SELECT color_key, r, g, b, count, created_at FROM static_colors ORDER BY count DESC LIMIT ?"
      ).bind(limit).all<{ color_key: string; r: number; g: number; b: number; count: number; created_at: string | null }>();
      const static_colors: Record<string, { r: number; g: number; b: number; count?: number; created_at?: string }> = {};
      for (const r of staticColorRows.results || []) {
        static_colors[r.color_key] = { r: r.r, g: r.g, b: r.b, count: r.count, created_at: r.created_at ?? undefined };
      }
      // Pure (static) sound mesh: origin + discovered per-instant sounds (include count for underused bias)
      const staticSoundRows = await env.DB.prepare(
        "SELECT sound_key, tone, timbre, amplitude, name, count, created_at FROM static_sound ORDER BY count DESC LIMIT ?"
      ).bind(limit).all<{ sound_key: string; tone: string | null; timbre: string | null; amplitude: number | null; name: string | null; count: number; created_at: string | null }>();
      const static_sound = (staticSoundRows.results || []).map((r) => ({
        key: r.sound_key,
        tone: r.tone ?? undefined,
        timbre: r.timbre ?? undefined,
        amplitude: r.amplitude ?? undefined,
        name: r.name ?? undefined,
        count: r.count,
        created_at: r.created_at ?? undefined,
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
        static_colors,
        static_sound,
      });
      } catch (e) {
        console.error("GET /api/knowledge/for-creation failed:", e);
        return json({ error: "Failed to load for-creation", details: String(e) }, 500);
      }
    }

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
          const inDb = await env.DB.prepare("SELECT 1 FROM learned_blends WHERE name = ?").bind(name).first();
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
            const rows = await env.DB.prepare(
              `SELECT id, name, r, g, b FROM ${table} WHERE name GLOB 'dsc_*' OR name GLOB 'Novel*' OR name GLOB 'color_*' LIMIT ?`
            ).bind(maxRows).all<{ id: string; name: string; r: number; g: number; b: number }>();
            for (const r of rows.results || []) {
              const row = r as { id: string; name: string | null; r: number; g: number; b: number };
              if (updated >= maxRows) break;
              if (shouldBackfillColorName(row.name)) {
                const oldName = row.name;
                const newName = rgbToSemanticColorName(row.r ?? 0, row.g ?? 0, row.b ?? 0, usedNames);
                usedNames.add(newName);
                if (!dryRun) {
                  await env.DB.prepare(`UPDATE ${table} SET name = ? WHERE id = ?`)
                    .bind(newName, row.id)
                    .run();
                  await cascadeNameUpdate(env, oldName, newName);
                }
                updated++;
              }
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
          { table: "narrative_entries", idCol: "id", nameCol: "name" },
        ];
        const otherTables = tableFilter
          ? otherTablesAll.filter((o) => o.table === tableFilter)
          : otherTablesAll;
        for (const { table, idCol, nameCol } of otherTables) {
          try {
            // Include dsc_*, Novel*, and long names (9+ chars) that may be gibberish
            const rows = await env.DB.prepare(
              `SELECT ${idCol}, ${nameCol} FROM ${table} WHERE ${nameCol} GLOB 'dsc_*' OR ${nameCol} GLOB 'Novel*' OR LENGTH(TRIM(${nameCol})) > 9 LIMIT ?`
            ).bind(maxRows).all<{ id: string; name: string }>();
            for (const r of rows.results || []) {
              const row = r as { id: string; name: string | null };
              if (updated >= maxRows) break;
              if (isGibberishName(row.name)) {
                const oldName = row.name;
                const newName = await pickUniqueName();
                if (!dryRun) {
                  await env.DB.prepare(`UPDATE ${table} SET ${nameCol} = ? WHERE ${idCol} = ?`)
                    .bind(newName, row.id)
                    .run();
                  await cascadeNameUpdate(env, oldName, newName);
                }
                updated++;
              }
            }
          } catch {
            /* table may not exist */
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
          const r = await env.DB.prepare(
            "SELECT id, r, g, b FROM static_colors LIMIT ?"
          ).bind(limit).all<{ id: string; r: number; g: number; b: number }>();
          rows = r.results || [];
        } else if (table === "learned_colors") {
          const r = await env.DB.prepare(
            "SELECT id, color_key, r, g, b FROM learned_colors LIMIT ?"
          ).bind(limit).all<{ id: string; color_key: string; r: number; g: number; b: number }>();
          rows = r.results || [];
        } else if (table === "learned_motion") {
          const r = await env.DB.prepare(
            "SELECT id, motion_level, motion_trend FROM learned_motion LIMIT ?"
          ).bind(limit).all<{ id: string; motion_level: number; motion_trend: string }>();
          rows = r.results || [];
        } else if (table === "learned_lighting") {
          const r = await env.DB.prepare(
            "SELECT id, brightness, contrast, saturation FROM learned_lighting LIMIT ?"
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
            await env.DB.prepare(
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

    // GET /api/registries/coverage — counts and coverage % per registry for completion targeting (§2.1, §2.8)
    if (path === "/api/registries/coverage" && request.method === "GET") {
      const STATIC_COLOR_ESTIMATED_CELLS = 27951;
      const NARRATIVE_ORIGIN_SIZES: Record<string, number> = {
        genre: 7, mood: 7, style: 5, plots: 4, settings: 8, themes: 8, scene_type: 8,
      };
      const narrativeAspects = ["genre", "mood", "themes", "plots", "settings", "style", "scene_type"];

      let staticColorsCount = 0;
      let staticSoundCount = 0;
      let learnedColorsCount = 0;
      const soundPrimitives = new Set<string>();

      try {
        const sc = await env.DB.prepare("SELECT COUNT(*) as c FROM static_colors").first<{ c: number }>();
        staticColorsCount = sc?.c ?? 0;
      } catch { /* table may not exist */ }
      try {
        const ss = await env.DB.prepare("SELECT COUNT(*) as c FROM static_sound").first<{ c: number }>();
        staticSoundCount = ss?.c ?? 0;
      } catch { /* table may not exist */ }
      try {
        const rows = await env.DB.prepare("SELECT depth_breakdown_json FROM static_sound LIMIT 500")
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
      try {
        const lc = await env.DB.prepare("SELECT COUNT(*) as c FROM learned_colors").first<{ c: number }>();
        learnedColorsCount = lc?.c ?? 0;
      } catch { /* ignore */ }

      const staticColorsCoveragePct = STATIC_COLOR_ESTIMATED_CELLS > 0
        ? Math.min(100, Math.round((100 * staticColorsCount) / STATIC_COLOR_ESTIMATED_CELLS * 100) / 100)
        : 0;
      const narrative: Record<string, { count: number; origin_size: number; coverage_pct: number; entry_keys: string[] }> = {};
      for (const aspect of narrativeAspects) {
        const originSize = NARRATIVE_ORIGIN_SIZES[aspect] ?? 0;
        try {
          const r = await env.DB.prepare(
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

      const coverage = {
        static_colors_count: staticColorsCount,
        static_colors_estimated_cells: STATIC_COLOR_ESTIMATED_CELLS,
        static_colors_coverage_pct: staticColorsCoveragePct,
        static_sound_count: staticSoundCount,
        static_sound_has_silence: soundPrimitives.has("silence"),
        static_sound_has_rumble: soundPrimitives.has("rumble"),
        static_sound_has_tone: soundPrimitives.has("tone"),
        static_sound_has_hiss: soundPrimitives.has("hiss"),
        static_sound_all_primitives: soundPrimitives.has("silence") && soundPrimitives.has("rumble") && soundPrimitives.has("tone") && soundPrimitives.has("hiss"),
        learned_colors_count: learnedColorsCount,
        narrative,
        narrative_min_coverage_pct: narrativeAspects.length
          ? Math.min(...narrativeAspects.map((a) => narrative[a]?.coverage_pct ?? 0))
          : 0,
      };
      return json(coverage);
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
      // Canonical color key: always "r,g,b" (strip optional _opacity suffix from static keys for consistent export)
      const normalizeColorKey = (key: string): string => {
        const i = key.indexOf("_");
        return i > 0 ? key.slice(0, i) : key;
      };
      // Color primitives only (depth_breakdown must reference these; theme/preset names go to theme_breakdown; opacity to opacity_pct)
      const COLOR_PRIMITIVES = new Set([
        "black", "white", "red", "green", "blue", "yellow", "cyan", "magenta", "orange", "purple",
        "pink", "brown", "navy", "gray", "olive", "teal",
      ]);
      type DepthSplit = { depth_breakdown: Record<string, number>; opacity_pct?: number; theme_breakdown?: Record<string, number> };
      const splitDepthBreakdown = (raw: Record<string, number> | null): DepthSplit => {
        const depth_breakdown: Record<string, number> = {};
        let opacity_pct: number | undefined;
        const theme_breakdown: Record<string, number> = {};
        if (!raw || typeof raw !== "object") return { depth_breakdown };
        for (const [k, v] of Object.entries(raw)) {
          const num = typeof v === "number" ? (v <= 1 ? Math.round(v * 100) : Math.round(v)) : 0;
          if (k === "opacity") opacity_pct = num;
          else if (COLOR_PRIMITIVES.has(k)) depth_breakdown[k] = num;
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
      const staticColors = await env.DB.prepare(
        "SELECT color_key, r, g, b, name, count, depth_breakdown_json FROM static_colors ORDER BY count DESC LIMIT ?"
      ).bind(regLimit).all<{ color_key: string; r: number; g: number; b: number; name: string; count: number; depth_breakdown_json: string | null }>();
      const staticSound = await env.DB.prepare(
        "SELECT sound_key, name, count, depth_breakdown_json, strength_pct FROM static_sound ORDER BY count DESC LIMIT ?"
      ).bind(regLimit).all<{ sound_key: string; name: string; count: number; depth_breakdown_json: string | null; strength_pct: number | null }>();
      const learnedColors = await env.DB.prepare(
        "SELECT color_key, r, g, b, name, count, depth_breakdown_json FROM learned_colors ORDER BY count DESC LIMIT ?"
      ).bind(regLimit).all<{ color_key: string; r: number; g: number; b: number; name: string; count: number; depth_breakdown_json: string | null }>();
      const learnedMotion = await env.DB.prepare(
        "SELECT profile_key, motion_trend, name, count FROM learned_motion ORDER BY count DESC LIMIT ?"
      ).bind(regLimit).all<{ profile_key: string; motion_trend: string; name: string | null; count: number }>();
      const blends = await env.DB.prepare(
        "SELECT name, domain, output_json, primitive_depths_json FROM learned_blends ORDER BY created_at DESC LIMIT ?"
      ).bind(regLimit).all<{ name: string; domain: string; output_json: string; primitive_depths_json: string | null }>();
      // Merge discovery tables into dynamic (living plan §1.2 / Priority 1): per-window discoveries appear in export
      const learnedGradientRows = await env.DB.prepare(
        "SELECT profile_key, gradient_type, name, count, depth_breakdown_json FROM learned_gradient ORDER BY count DESC LIMIT ?"
      ).bind(regLimit).all<{ profile_key: string; gradient_type: string; name: string; count: number; depth_breakdown_json: string | null }>();
      const learnedCameraRows = await env.DB.prepare(
        "SELECT profile_key, motion_type, name, count, depth_breakdown_json FROM learned_camera ORDER BY count DESC LIMIT ?"
      ).bind(regLimit).all<{ profile_key: string; motion_type: string; name: string; count: number; depth_breakdown_json: string | null }>();
      let learnedAudioSemanticRows: Array<{ profile_key: string; role: string; name: string; count: number }> = [];
      try {
        const r = await env.DB.prepare(
          "SELECT profile_key, role, name, count FROM learned_audio_semantic ORDER BY count DESC LIMIT ?"
        ).bind(regLimit).all<{ profile_key: string; role: string; name: string; count: number }>();
        learnedAudioSemanticRows = r.results || [];
      } catch {
        // table may not exist
      }
      const narrativeAspects = ["genre", "mood", "themes", "plots", "settings", "style", "scene_type"];
      const narrative: Record<string, Array<{ entry_key: string; value: string; name: string; count: number }>> = {};
      const NARRATIVE_LOW_COUNT_THRESHOLD = 5;
      for (const aspect of narrativeAspects) {
        const rows = await env.DB.prepare(
          "SELECT entry_key, value, name, count FROM narrative_entries WHERE aspect = ? ORDER BY count DESC LIMIT ?"
        ).bind(aspect, regLimit).all<{ entry_key: string; value: string | null; name: string; count: number }>();
        narrative[aspect] = (rows.results || []).map((r) => {
          const value = r.value || r.entry_key;
          const displayName = r.count < NARRATIVE_LOW_COUNT_THRESHOLD ? value : fixNarrativeName(r.name);
          return {
            entry_key: r.entry_key,
            value,
            name: displayName,
            count: r.count,
          };
        });
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
      let linguistic: Array<{ span: string; canonical: string; domain: string; variant_type: string; count: number }> = [];
      try {
        const lingRows = await env.DB.prepare(
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
        return { name: b.name, domain: b.domain, key: b.output_json.slice(0, 80), depth_pct, depth_breakdown };
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
        const l = await env.DB.prepare(
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
        const c = await env.DB.prepare(
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
        const g = await env.DB.prepare(
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
        const t = await env.DB.prepare(
          "SELECT profile_key, name FROM learned_temporal ORDER BY count DESC LIMIT ?"
        ).bind(regLimit).all<{ profile_key: string; name: string }>();
        learnedTemporalRows = (t.results || []).map((r) => ({
          name: r.name || r.profile_key,
          key: r.profile_key,
          depth_pct: 0,
          depth_breakdown: {} as Record<string, number>,
        }));
      } catch {
        // table may not exist
      }
      try {
        const tech = await env.DB.prepare(
          "SELECT profile_key, name FROM learned_technical ORDER BY count DESC LIMIT ?"
        ).bind(regLimit).all<{ profile_key: string; name: string }>();
        learnedTechnicalRows = (tech.results || []).map((r) => ({
          name: r.name || r.profile_key,
          key: r.profile_key,
          depth_pct: 0,
          depth_breakdown: {} as Record<string, number>,
        }));
      } catch {
        // table may not exist
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
      const motionFromLearned = (learnedMotion.results || []).map((r) => ({ key: r.profile_key, name: r.name || r.profile_key, trend: r.motion_trend, count: r.count }));
      const motionFromBlends = motionBlendsFromBlends.map((b) => ({ key: b.key, name: b.name, trend: "—" as const, count: 0 }));
      const motionKeysPresent = new Set([...motionFromLearned.map((m) => m.key), ...motionFromBlends.map((b) => b.key)]);
      const motionWithCanonical = [...motionFromLearned, ...motionFromBlends];
      for (const canonical of dynamicCanonical.motion) {
        if (!motionKeysPresent.has(canonical)) {
          motionKeysPresent.add(canonical);
          motionWithCanonical.push({ key: canonical, name: canonical, trend: "—", count: 0 });
        }
      }
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
                    raw[k] = typeof v === "number" ? (v <= 1 ? Math.round(v * 100) : Math.round(v)) : 0;
                  }
                }
                for (const [k, v] of Object.entries(stored)) {
                  if (k === "origin_colors") continue;
                  if (typeof v === "number") raw[k] = k === "opacity" ? Math.round(v * 100) : (v <= 1 ? Math.round(v * 100) : Math.round(v));
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
            const SOUND_PRIMITIVES = ["silence", "rumble", "tone", "hiss"];
            const stripSoundPrefix = (name: string | null): string => {
              if (!name || typeof name !== "string") return name ?? "";
              const n = name.trim();
              return n.toLowerCase().startsWith("sound_") ? n.slice(6).trim() || n : n;
            };
            const fromDb = (staticSound.results || []).map((r) => {
              const depth_breakdown = r.depth_breakdown_json ? (JSON.parse(r.depth_breakdown_json) as Record<string, unknown>) : undefined;
              return { key: r.sound_key, name: stripSoundPrefix(r.name), count: r.count, strength_pct: r.strength_pct ?? undefined, depth_breakdown };
            });
            const keysPresent = new Set(fromDb.map((s) => s.key));
            for (const key of SOUND_PRIMITIVES) {
              if (!keysPresent.has(key)) {
                keysPresent.add(key);
                fromDb.push({ key, name: key, count: 0, strength_pct: undefined, depth_breakdown: undefined });
              }
            }
            return fromDb;
          })(),
      };
      const dynamicPayload = {
          colors: ensureUniqueColorNames((learnedColors.results || []).map((r) => {
            let depth_pct: number;
            let depth_breakdown: Record<string, number>;
            let opacity_pct: number | undefined;
            let theme_breakdown: Record<string, number> | undefined;
            if (r.depth_breakdown_json) {
              try {
                const stored = JSON.parse(r.depth_breakdown_json) as Record<string, number>;
                const raw: Record<string, number> = {};
                for (const [k, v] of Object.entries(stored)) {
                  raw[k] = typeof v === "number" ? (v <= 1 ? Math.round(v * 100) : Math.round(v)) : 0;
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
            const out: Record<string, unknown> = { key, name: r.name, count: r.count, depth_pct, depth_breakdown };
            if (opacity_pct != null) out.opacity_pct = opacity_pct;
            if (theme_breakdown && Object.keys(theme_breakdown).length > 0) out.theme_breakdown = theme_breakdown;
            return out as { key: string; name: string; count: number; depth_pct: number; depth_breakdown: Record<string, number>; opacity_pct?: number; theme_breakdown?: Record<string, number> };
          })),
          motion: motionWithCanonical,
          gradient: gradientBlends,
          camera: cameraBlends,
          sound: audioBlends,
          colors_from_blends: colorBlendsFromBlends,
          lighting: lightingBlends,
          composition: compositionBlends,
          graphics: graphicsBlends,
          temporal: temporalBlends,
          technical: technicalBlends,
          blends: otherBlends,
      };
      return json({
        static_primitives: staticPrimitives,
        dynamic_canonical: dynamicCanonical,
        static: staticPayload,
        dynamic: dynamicPayload,
        narrative,
        interpretation,
        linguistic,
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
        const totalMotion = await env.DB.prepare("SELECT COALESCE(SUM(count), 0) as s FROM learned_motion").first<{ s: number }>();
        const topMotion = await env.DB.prepare(
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
      let coverage_snapshot: { static_colors_coverage_pct?: number; narrative_min_coverage_pct?: number; static_sound_coverage_pct?: number } | null = null;
      try {
        const sc = await env.DB.prepare("SELECT COUNT(*) as c FROM static_colors").first<{ c: number }>();
        const staticCount = sc?.c ?? 0;
        const staticCells = 27951;
        const staticPct = staticCells > 0 ? Math.round((100 * staticCount) / staticCells * 100) / 100 : 0;
        const narrativeSizes: Record<string, number> = { genre: 7, mood: 7, style: 5, plots: 4, settings: 8, themes: 8, scene_type: 8 };
        const aspects = Object.keys(narrativeSizes);
        let minNarrativePct = 100;
        for (const aspect of aspects) {
          const r = await env.DB.prepare("SELECT COUNT(DISTINCT entry_key) as c FROM narrative_entries WHERE aspect = ?").bind(aspect).first<{ c: number }>();
          const count = r?.c ?? 0;
          const size = narrativeSizes[aspect] ?? 1;
          const pct = size > 0 ? (100 * count) / size : 100;
          if (pct < minNarrativePct) minNarrativePct = pct;
        }
        minNarrativePct = Math.round(minNarrativePct * 100) / 100;
        let staticSoundPct: number | undefined;
        try {
          const ss = await env.DB.prepare("SELECT COUNT(DISTINCT sound_key) as c FROM static_sound").first<{ c: number }>();
          const soundCount = ss?.c ?? 0;
          const primitiveToneTarget = 5;
          staticSoundPct = Math.round(Math.min(100, (100 * soundCount) / primitiveToneTarget) * 100) / 100;
        } catch {
          /* static_sound may not exist */
        }
        coverage_snapshot = {
          static_colors_coverage_pct: staticPct,
          narrative_min_coverage_pct: minNarrativePct,
          ...(staticSoundPct !== undefined ? { static_sound_coverage_pct: staticSoundPct } : {}),
        };
      } catch {
        /* optional */
      }

      return json({
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
      });
    }

    // GET /api/metrics — Prometheus-compatible metrics for dashboards
    if (path === "/api/metrics" && request.method === "GET") {
      try {
        const last = 20;
        const completed = await env.DB.prepare(
          "SELECT id FROM jobs WHERE status = 'completed' AND r2_key IS NOT NULL ORDER BY updated_at DESC LIMIT ?"
        ).bind(last).all<{ id: string }>();
        const ids = (completed.results || []).map((r) => r.id);
        let withLearning = 0;
        let withDiscovery = 0;
        if (ids.length > 0) {
          const ph = ids.map(() => "?").join(",");
          const lr = await env.DB.prepare(`SELECT COUNT(DISTINCT job_id) as c FROM learning_runs WHERE job_id IN (${ph})`).bind(...ids).first<{ c: number }>();
          withLearning = lr?.c ?? 0;
          try {
            const dr = await env.DB.prepare(`SELECT COUNT(DISTINCT job_id) as c FROM discovery_runs WHERE job_id IN (${ph})`).bind(...ids).first<{ c: number }>();
            withDiscovery = dr?.c ?? 0;
          } catch { /* discovery_runs may not exist */ }
        }
        const totalRuns = ids.length;
        const precision = totalRuns > 0 ? (withLearning / totalRuns) * 100 : 0;
        const discoveryRate = totalRuns > 0 ? (withDiscovery / totalRuns) * 100 : 0;
        const jobCount = await env.DB.prepare("SELECT COUNT(*) as c FROM jobs WHERE status = 'completed'").first<{ c: number }>();
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
          hint:
          missing_learning > 0 || missing_discovery > 0
            ? "Missing learning: POST /api/learning may have failed or job completed via different path. Missing discovery: POST /api/knowledge/discoveries with job_id may have failed or path did not pass job_id."
            : null,
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

// Semantic name parts (mirrors Python blend_names.py) — no gibberish
const SEMANTIC_START = ["am", "vel", "cor", "sil", "riv", "mist", "dawn", "dusk", "wave", "drift", "soft", "deep", "cool", "warm", "star", "sky", "sea", "frost", "dew", "rose", "gold", "pearl", "sage", "mint", "vine", "bloom", "shade", "glow", "flow", "haze", "vale", "storm", "leaf", "cloud", "wind", "rain", "brook", "sun", "lune", "slate", "flax", "iron", "stone", "oak", "pine", "cedar", "willow", "maple", "ivory", "copper", "bronze", "chalk", "linen", "wool"];
const SEMANTIC_END = ["ber", "vet", "al", "ver", "er", "en", "ow", "or", "um", "in", "ar", "ace", "ine", "ure", "ish", "ing", "lyn", "tor", "nel", "ton", "ley", "well", "brook", "field", "wood", "light", "fall", "rise", "ford", "dale", "mont", "view", "crest", "haven", "mere", "stone", "vale", "mist", "glow", "bloom", "stream", "ridge", "shore"];
const SEMANTIC_WORDS = ["amber", "velvet", "coral", "silver", "river", "mist", "dawn", "dusk", "wave", "drift", "soft", "deep", "cool", "warm", "calm", "star", "sky", "sea", "frost", "dew", "rose", "gold", "pearl", "sage", "mint", "vine", "bloom", "shade", "glow", "flow", "haze", "vale", "storm", "leaf", "cloud", "wind", "rain", "brook", "sun", "ember", "azure", "lark", "fern", "cliff", "marsh", "glen", "haven", "fall", "rise", "ford", "dale", "mont", "view", "crest", "mere", "worth", "slate", "stone", "iron", "flax", "oak", "pine", "cedar", "willow", "maple", "ivory", "copper", "bronze", "chalk", "linen", "wool", "silk", "jade"];

function inventSemanticWord(seed: number): string {
  const r = Math.abs(seed) % 0x7fffffff;
  const wordIdx = r % SEMANTIC_WORDS.length;
  const candidate = SEMANTIC_WORDS[wordIdx];
  if (candidate.length >= 4 && candidate.length <= 18) return candidate;
  const sIdx = (r >> 7) % SEMANTIC_START.length;
  const start = SEMANTIC_START[sIdx];
  for (let k = 0; k < SEMANTIC_END.length; k++) {
    const rr = (r * 7919 + 1237 + k) % 0x7fffffff;
    const eIdx = rr % SEMANTIC_END.length;
    const end = SEMANTIC_END[eIdx];
    if (start && end && start[start.length - 1] === end[0]) continue;
    let word = start + end;
    if (word.length > 18) word = word.slice(0, 18);
    if (word.length < 4) word = word + end.slice(0, Math.min(end.length, 4 - word.length));
    return word.slice(0, 18);
  }
  return (start + SEMANTIC_END[0]).slice(0, 18);
}

function toTitleCase(s: string): string {
  return s.length > 1 ? s[0].toUpperCase() + s.slice(1).toLowerCase() : s.toUpperCase();
}

function isGibberishName(name: string | null): boolean {
  if (!name || typeof name !== "string") return false;
  const n = name.trim().toLowerCase();
  if (n.length < 4) return false;
  if (/^dsc_[a-f0-9]+$/i.test(n)) return true;
  if (n.startsWith("novel") && /^\d+$/.test(n.slice(5))) return true;
  if (SEMANTIC_WORDS.some((w) => w === n)) return false;
  if (SEMANTIC_START.some((s) => n.startsWith(s))) return false;
  if (SEMANTIC_END.some((e) => n.endsWith(e))) return false;
  if (n.length <= 8) return false;
  return true;
}

// Gibberish prompt detection (mirrors Python interpretation/gibberish.py)
const KNOWN_WORDS = new Set([
  "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "by", "from", "as",
  "is", "was", "are", "were", "be", "been", "have", "has", "had", "do", "does", "did", "will", "would",
  "could", "should", "can", "may", "might", "must", "shall", "video", "motion", "flow", "calm", "slow",
  "fast", "bright", "dark", "soft", "dreamy", "abstract", "cinematic", "minimal", "realistic", "style",
  "feel", "look", "vibe", "mood", "tone", "color", "colours", "blue", "red", "green", "ocean", "sunset",
  "night", "day", "golden", "hour", "warm", "cool", "gradient", "smooth", "gentle", "peaceful",
  "energetic", "dynamic", "static", "pan", "zoom", "tilt", "tracking", "handheld", "documentary",
  "neon", "pastel", "vintage", "modern", "retro", "nostalgic", "melancholic", "serene", "dramatic",
  "subtle", "bold", "muted", "vibrant", "intense", "explainer", "tutorial", "explain", "gradual",
  "symmetric", "silence", "ambient", "music", "sfx", "balanced", "slight", "bilateral", "centered",
  "lit", "chill", "vibing", "vibes", "lowkey", "glowy", "mellow",
]);
const GIBBERISH_RE = /(?:[bcdfghjklmnpqrstvwxz]{4,}|([a-z]{2})\1{2,}|[qxjz]{2,})/i;

// RGB → semantic color vocabulary (mirrors Python blend_names.py)
const RGB_COLOR_VOCAB: Record<string, string[]> = {
  shadow: ["shadow", "charcoal", "obsidian", "onyx", "raven", "coal", "ink"],
  graphite: ["graphite", "iron", "lead", "pewter", "gunmetal"],
  slate: ["slate", "stone", "flint", "ash", "steel", "silver"],
  mist: ["mist", "fog", "haze", "pearl", "cloud", "frost"],
  ember: ["ember", "rust", "copper", "terracotta", "brick"],
  sunset: ["sunset", "coral", "salmon", "blush", "apricot", "tangerine"],
  rust: ["rust", "sienna", "ochre", "bronze", "umber"],
  moss: ["moss", "sage", "fern", "olive", "jade"],
  forest: ["forest", "pine", "cedar", "evergreen", "laurel"],
  olive: ["olive", "khaki", "sand", "tan", "taupe"],
  teal: ["teal", "turquoise", "aqua", "cyan", "mint"],
  violet: ["violet", "lavender", "lilac", "plum", "amethyst"],
  ocean: ["ocean", "navy", "indigo", "sapphire", "azure"],
  midnight: ["midnight", "twilight", "dusk", "deep", "abyss"],
  neutral: ["stone", "sand", "linen", "ivory", "cream"],
};

function rgbToSemanticHint(r: number, g: number, b: number): string {
  const mx = Math.max(r, g, b);
  const mn = Math.min(r, g, b);
  if (mx < 50) return "shadow";
  if (mx - mn < 40) {
    const lum = (r + g + b) / 3;
    if (lum < 80) return "graphite";
    if (lum < 140) return "slate";
    return "mist";
  }
  if (r >= g && r >= b && r > 0) return b > g ? "ember" : r > 180 ? "sunset" : "rust";
  if (g >= r && g >= b && g > 0) return r > b ? "moss" : g > 120 ? "forest" : "olive";
  if (b >= r && b >= g && b > 0) return g > r ? "teal" : r > g ? "violet" : b > 140 ? "ocean" : "midnight";
  return "neutral";
}

/** Cascade oldName→newName to prompts and sources when backfilling registry names. */
async function cascadeNameUpdate(env: Env, oldName: string, newName: string): Promise<void> {
  if (!oldName || oldName === newName) return;
  const like = "%" + oldName.replace(/[%_]/g, "\\$&") + "%";
  const tables: { table: string; col: string }[] = [
    { table: "learning_runs", col: "prompt" },
    { table: "interpretations", col: "prompt" },
    { table: "interpretations", col: "instruction_json" },
    { table: "jobs", col: "prompt" },
    { table: "learned_blends", col: "source_prompt" },
    { table: "learned_blends", col: "inputs_json" },
    { table: "learned_blends", col: "output_json" },
    { table: "learned_blends", col: "primitive_depths_json" },
    { table: "static_colors", col: "sources_json" },
    { table: "static_sound", col: "sources_json" },
    { table: "learned_colors", col: "sources_json" },
    { table: "learned_motion", col: "sources_json" },
    { table: "learned_lighting", col: "sources_json" },
    { table: "learned_composition", col: "sources_json" },
    { table: "learned_graphics", col: "sources_json" },
    { table: "learned_temporal", col: "sources_json" },
    { table: "learned_technical", col: "sources_json" },
    { table: "learned_gradient", col: "sources_json" },
    { table: "learned_camera", col: "sources_json" },
    { table: "learned_time", col: "sources_json" },
    { table: "narrative_entries", col: "sources_json" },
  ];
  for (const { table, col } of tables) {
    try {
      await env.DB.prepare(
        `UPDATE ${table} SET ${col} = REPLACE(${col}, ?, ?) WHERE ${col} LIKE ? ESCAPE '\\'`
      )
        .bind(oldName, newName, like)
        .run();
    } catch {
      /* table/col may not exist */
    }
  }
}

function shouldBackfillColorName(name: string | null): boolean {
  if (!name || typeof name !== "string") return true;
  const n = name.trim().toLowerCase();
  if (n.length < 4) return false;
  const realColorWords = new Set([
    "amber", "velvet", "coral", "silver", "river", "mist", "dawn", "dusk", "wave",
    "slate", "stone", "iron", "oak", "pine", "cedar", "jade", "shadow", "graphite",
    "ember", "rust", "sienna", "sage", "fern", "olive", "teal", "ocean", "navy",
    "violet", "lavender", "pearl", "cloud", "frost", "ink", "coal", "ash",
  ]);
  if (realColorWords.has(n)) return false;
  if (n.startsWith("color_")) return true;
  if (SEMANTIC_WORDS.some((w) => w === n)) return false;
  if (SEMANTIC_START.some((s) => n.startsWith(s)) && SEMANTIC_END.some((e) => n.endsWith(e))) return true;
  return isGibberishName(name);
}

function isGibberishPrompt(prompt: string, strict = false): boolean {
  if (!prompt || typeof prompt !== "string") return true;
  const text = prompt.trim();
  if (text.length < 3) return false;
  const lower = text.toLowerCase();
  if (GIBBERISH_RE.test(lower)) return true;
  const words = lower.match(/[a-z]{3,}/g) || [];
  if (!words.length) return false;
  const known = words.filter((w) => KNOWN_WORDS.has(w)).length;
  const ratio = known / words.length;
  const longUnknown = words.filter((w) => w.length >= 10 && !KNOWN_WORDS.has(w));
  if (longUnknown.length > 0) return true;
  const avgLen = words.reduce((s, w) => s + w.length, 0) / words.length;
  if (strict) {
    if (ratio < 0.25 && avgLen > 6) return true;
    if (ratio < 0.15) return true;
  } else if (ratio < 0.15 && avgLen > 7) return true;
  return false;
}

async function generateUniqueName(env: Env): Promise<string> {
  for (let attempt = 0; attempt < 50; attempt++) {
    const seed = Math.floor(Math.random() * 1000000) + attempt * 7919;
    const word = inventSemanticWord(seed);
    if (word.length >= 4) {
      const name = toTitleCase(word);
      const inReserve = await env.DB.prepare("SELECT name FROM name_reserve WHERE name = ?").bind(name).first();
      const inBlends = await env.DB.prepare("SELECT name FROM learned_blends WHERE name = ?").bind(name).first();
      const inStatic = await env.DB.prepare("SELECT name FROM static_colors WHERE name = ?").bind(name).first();
      const inLearned = await env.DB.prepare("SELECT name FROM learned_colors WHERE name = ?").bind(name).first();
      if (!inReserve && !inBlends && !inStatic && !inLearned) return name;
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
