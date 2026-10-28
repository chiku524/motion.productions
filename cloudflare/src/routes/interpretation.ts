/**
 * Interpretation queue + linguistic registry API routes.
 */
import type { Env } from "../env";
import { getDb } from "../db";
import { json, err, uuid } from "../http";
import { isGibberishPrompt } from "../naming";
import { getSnapshot } from "../snapshotCache";
import { isFreeTierLimitError, limitResponse } from "../limits";

export async function handleInterpretationRoutes(
  request: Request,
  env: Env,
  path: string,
): Promise<Response | null> {
  const db = getDb(env);

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
  await db.prepare(
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
  const rows = await db.prepare(
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
  const row = await db.prepare("SELECT id, status FROM interpretations WHERE id = ?").bind(id).first();
  if (!row) return err("Interpretation job not found", 404);
  if ((row as { status: string }).status !== "pending") return err("Already interpreted", 400);
  await db.prepare(
    "UPDATE interpretations SET instruction_json = ?, status = 'done', updated_at = datetime('now') WHERE id = ?"
  )
    .bind(JSON.stringify(instruction), id)
    .run();
  return json({ id, status: "done" });
}

// GET /api/interpret/backfill-prompts — prompts from jobs not yet in interpretations (for interpretation worker)
if (path === "/api/interpret/backfill-prompts" && request.method === "GET") {
  const limit = Math.min(parseInt(new URL(request.url).searchParams.get("limit") || "30", 10), 100);
  const backfillCacheKey = `interpret:backfill-prompts:${limit}`;
  // Avoid jobs ⟕ interpretations DISTINCT join (full-scan → D1 CPU 7429 / ~36s 503 under loop load).
  // Cheap path: recent jobs by created_at index, then IN-check against interpretations.
  try {
    const backfillSnap = await getSnapshot<string>(
      env,
      backfillCacheKey,
      { softTtlSec: 900, hardTtlSec: 86400 },
      async () => {
    const scan = Math.min(Math.max(limit * 4, 40), 200);
    const recent = await db
      .prepare(
        "SELECT prompt FROM jobs WHERE prompt IS NOT NULL AND prompt != '' ORDER BY created_at DESC LIMIT ?",
      )
      .bind(scan)
      .all<{ prompt: string }>();
    const seen = new Set<string>();
    const candidates: string[] = [];
    for (const r of recent.results || []) {
      const p = (r.prompt || "").trim();
      if (!p || seen.has(p) || isGibberishPrompt(p, true)) continue;
      seen.add(p);
      candidates.push(p);
    }
    const done = new Set<string>();
    const chunkSize = 40;
    for (let i = 0; i < candidates.length; i += chunkSize) {
      const chunk = candidates.slice(i, i + chunkSize);
      if (!chunk.length) break;
      const placeholders = chunk.map(() => "?").join(",");
      const rows = await db
        .prepare(
          `SELECT prompt FROM interpretations WHERE status = 'done' AND prompt IN (${placeholders})`,
        )
        .bind(...chunk)
        .all<{ prompt: string }>();
      for (const r of rows.results || []) {
        if (r.prompt) done.add(r.prompt);
      }
    }
    const prompts = candidates.filter((p) => !done.has(p)).slice(0, limit);
    return JSON.stringify({ prompts });
      },
    );
    return new Response(backfillSnap.value, { headers: { "Content-Type": "application/json", "X-Cache": backfillSnap.source === "built" ? "MISS" : "HIT" } });
  } catch (e) {
    if (isFreeTierLimitError(e)) return limitResponse("GET", { prompts: [] });
    console.error("GET /api/interpret/backfill-prompts failed:", e);
    return json({ error: "Failed to load backfill prompts", details: String(e), prompts: [] }, 503);
  }
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
  const INTERPRET_BATCH_MAX = 50; // Workers Paid: 1000 queries/request; 1 per insert
  const toInsert = items.slice(0, INTERPRET_BATCH_MAX);
  let inserted = 0;
  let rowsWritten = 0;
  for (const it of toInsert) {
    const prompt = typeof it.prompt === "string" ? it.prompt.trim() : "";
    if (!prompt) continue;
    if (isGibberishPrompt(prompt, true)) continue;
    const instruction = it.instruction && typeof it.instruction === "object" ? it.instruction : null;
    if (!instruction) continue;
    const source = typeof it.source === "string" && /^(web|worker|loop|backfill)$/.test(it.source) ? it.source : "backfill";
    const id = uuid();
    try {
      const r = await db.prepare(
        "INSERT INTO interpretations (id, prompt, instruction_json, source, status) VALUES (?, ?, ?, ?, 'done')"
      )
        .bind(id, prompt, JSON.stringify(instruction), source)
        .run();
      rowsWritten += Number((r.meta as { rows_written?: number } | undefined)?.rows_written) || 0;
      inserted++;
    } catch {
      // Skip duplicate or constraint error
    }
  }
  return json({ inserted, rows_written: rowsWritten }, inserted > 0 ? 201 : 200);
}

// GET /api/linguistic-registry — fetch all mappings for interpretation (span -> canonical by domain)
if (path === "/api/linguistic-registry" && request.method === "GET") {
  try {
    const domain = new URL(request.url).searchParams.get("domain");
    const q = domain
      ? "SELECT span, canonical, domain, variant_type, count FROM linguistic_registry WHERE domain = ?"
      : "SELECT span, canonical, domain, variant_type, count FROM linguistic_registry";
    const stmt = domain ? db.prepare(q).bind(domain) : db.prepare(q);
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
// Workers Paid: 1000 queries/request. ~2 queries/item. Cap at 100 for efficiency (~200 queries).
if (path === "/api/linguistic-registry/batch" && request.method === "POST") {
  let body: { items: Array<{ span: string; canonical: string; domain: string; variant_type?: string; count?: number }> };
  try {
    body = (await request.json()) as typeof body;
  } catch {
    return err("Invalid JSON");
  }
  const items = Array.isArray(body.items) ? body.items : [];
  if (items.length === 0) return json({ inserted: 0, updated: 0 });
  const LINGUISTIC_BATCH_MAX = 100;
  // One db.batch of upserts (was: SELECT + UPDATE/INSERT per item). Repeats inside the request are summed, and a client
  // that coalesced N sightings sends `count: N`. Cost: 1 row written per EXISTING span, 1 + 4 index rows per new span.
  const merged = new Map<string, { span: string; canonical: string; domain: string; variantType: string; count: number }>();
  for (const it of items.slice(0, LINGUISTIC_BATCH_MAX)) {
    const span = typeof it.span === "string" ? it.span.trim().toLowerCase() : "";
    const canonical = typeof it.canonical === "string" ? it.canonical.trim() : "";
    const domain = typeof it.domain === "string" ? it.domain.trim() : "";
    const variantType = typeof it.variant_type === "string" ? it.variant_type : "synonym";
    if (!span || !canonical || !domain) continue;
    const n = Math.floor(Number(it.count));
    const count = Number.isFinite(n) && n >= 1 ? Math.min(n, 1000) : 1;
    const k = `${domain}\u0000${span}`;
    const prev = merged.get(k);
    if (prev) prev.count += count;
    else merged.set(k, { span, canonical, domain, variantType, count });
  }
  const rows = [...merged.values()];
  if (rows.length === 0) return json({ inserted: 0, updated: 0, rows_written: 0 });
  let inserted = 0;
  let updated = 0;
  let rowsWritten = 0;
  try {
    const res = await db.batch(
      rows.map((r) =>
        db
          .prepare(
            "INSERT INTO linguistic_registry (id, span, canonical, domain, variant_type, count) VALUES (?, ?, ?, ?, ?, ?) " +
              "ON CONFLICT(span, domain) DO UPDATE SET count = count + excluded.count, updated_at = datetime('now') RETURNING count",
          )
          .bind(uuid(), r.span, r.canonical, r.domain, r.variantType, r.count),
      ),
    );
    res.forEach((x, i) => {
      const c = ((x.results || [])[0] as { count?: number } | undefined)?.count;
      if (c === rows[i].count) inserted++;
      else updated++;
      rowsWritten += Number((x.meta as { rows_written?: number } | undefined)?.rows_written) || 0;
    });
  } catch (e) {
    if (isFreeTierLimitError(e)) return limitResponse("POST", { inserted: 0, updated: 0, rows_written: 0 });
    // missing table etc.: same best-effort behaviour as before
  }
  return json({ inserted, updated, rows_written: rowsWritten }, inserted > 0 || updated > 0 ? 201 : 200);
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
  const source =
    typeof body.source === "string" && /^(web|worker|loop|backfill|generate|bridge)$/.test(body.source)
      ? body.source
      : "worker";
  // Skip gibberish for completed video-run sources so every render is recorded in the registry
  if (!/^(loop|bridge|web)$/.test(source) && isGibberishPrompt(prompt, true)) {
    return err("prompt appears to be gibberish; interpretation registry requires meaningful prompts");
  }
  const instruction = body.instruction && typeof body.instruction === "object" ? body.instruction : null;
  if (!instruction) return err("instruction is required");
  const id = uuid();
  const r = await db.prepare(
    "INSERT INTO interpretations (id, prompt, instruction_json, source, status) VALUES (?, ?, ?, ?, 'done')"
  )
    .bind(id, prompt, JSON.stringify(instruction), source)
    .run();
  const rowsWritten = Number((r.meta as { rows_written?: number } | undefined)?.rows_written) || 0;
  return json({ id, prompt: prompt.slice(0, 200), status: "done", rows_written: rowsWritten }, 201);
}


  return null;
}
