/**
 * R2 free-tier guard rails (10 GB-month storage, 1M Class A / 10M Class B ops per month; deletes are free).
 *
 * - Uploads are size capped (R2_MAX_UPLOAD_BYTES, default 25 MB) and refused with 507 when the tracked usage would
 *   exceed R2_BUDGET_BYTES (default 8 GB, leaving 20% headroom under the 10 GB free tier).
 * - Usage is tracked in ONE small object (`_meta/usage.json`) so hot paths never list(): one Class B get (memoised
 *   60 s per isolate) plus one Class A put per accepted upload.
 * - Retention: a daily cron (and an emergency sweep when an upload would not fit) lists the bucket (1 Class A per
 *   1,000 objects), deletes objects older than R2_RETENTION_DAYS (default 7), then evicts oldest-first down to 80% of
 *   the budget. The sweep also re-measures true usage, correcting counter drift.
 * - Loop clips are NOT uploaded by default (the loops delete renders after discovery); see jobs.ts `/complete`.
 */
import type { Env } from "./env";
import { json } from "./http";

export const USAGE_KEY = "_meta/usage.json";
export const DEFAULT_MAX_UPLOAD_BYTES = 25 * 1024 * 1024;
export const DEFAULT_BUDGET_BYTES = 8_000_000_000;
export const DEFAULT_RETENTION_DAYS = 7;
const EVICT_TARGET_FRACTION = 0.8;
const MAX_LIST_PAGES = 60; // 60k objects per sweep keeps CPU bounded; the next sweep continues
const EMERGENCY_SWEEP_MIN_INTERVAL_MS = 10 * 60 * 1000;
const USAGE_MEMO_MS = 60 * 1000;

export type R2Usage = { bytes: number; objects: number; updated_at: string; last_sweep_at: string | null };
export type R2Config = { maxUploadBytes: number; budgetBytes: number; retentionDays: number };

function positiveInt(raw: string | undefined, fallback: number, min = 1): number {
  const n = raw == null ? NaN : Number(raw);
  return Number.isFinite(n) && n >= min ? Math.floor(n) : fallback;
}

export function r2Config(env: Pick<Env, "R2_MAX_UPLOAD_BYTES" | "R2_BUDGET_BYTES" | "R2_RETENTION_DAYS">): R2Config {
  return {
    maxUploadBytes: positiveInt(env.R2_MAX_UPLOAD_BYTES, DEFAULT_MAX_UPLOAD_BYTES),
    budgetBytes: positiveInt(env.R2_BUDGET_BYTES, DEFAULT_BUDGET_BYTES),
    retentionDays: positiveInt(env.R2_RETENTION_DAYS, DEFAULT_RETENTION_DAYS),
  };
}

let usageMemo: { at: number; usage: R2Usage } | null = null;
let lastEmergencySweepAt = 0;

export function __resetR2BudgetMemory(): void {
  usageMemo = null;
  lastEmergencySweepAt = 0;
}

function emptyUsage(): R2Usage {
  return { bytes: 0, objects: 0, updated_at: new Date(0).toISOString(), last_sweep_at: null };
}

export async function readUsage(env: Env, fresh = false): Promise<R2Usage> {
  const now = Date.now();
  if (!fresh && usageMemo && now - usageMemo.at < USAGE_MEMO_MS) return usageMemo.usage;
  let usage = emptyUsage();
  const obj = await env.VIDEOS.get(USAGE_KEY);
  if (obj) {
    try {
      const parsed = JSON.parse(await obj.text()) as Partial<R2Usage>;
      usage = {
        bytes: Math.max(0, Number(parsed.bytes) || 0),
        objects: Math.max(0, Number(parsed.objects) || 0),
        updated_at: typeof parsed.updated_at === "string" ? parsed.updated_at : usage.updated_at,
        last_sweep_at: typeof parsed.last_sweep_at === "string" ? parsed.last_sweep_at : null,
      };
    } catch {
      /* corrupt counter: treated as empty; the next sweep re-measures */
    }
  }
  usageMemo = { at: now, usage };
  return usage;
}

async function writeUsage(env: Env, usage: R2Usage): Promise<void> {
  await env.VIDEOS.put(USAGE_KEY, JSON.stringify(usage), { httpMetadata: { contentType: "application/json" } });
  usageMemo = { at: Date.now(), usage };
}

export type ReserveResult = { ok: true } | { ok: false; status: 413 | 507; error: string; details: Record<string, unknown> };

/** Cheap pre-check (no body read) for a declared size. */
export function checkDeclaredSize(env: Env, sizeBytes: number): ReserveResult {
  const cfg = r2Config(env);
  if (sizeBytes > cfg.maxUploadBytes) {
    return { ok: false, status: 413, error: "Upload too large", details: { max_bytes: cfg.maxUploadBytes, got_bytes: sizeBytes } };
  }
  return { ok: true };
}

/** Ensure `sizeBytes` fits in the budget; runs a rate-limited emergency sweep if it does not. */
export async function reserveUpload(env: Env, sizeBytes: number): Promise<ReserveResult> {
  const cfg = r2Config(env);
  const tooBig = checkDeclaredSize(env, sizeBytes);
  if (!tooBig.ok) return tooBig;
  let usage = await readUsage(env);
  if (usage.bytes + sizeBytes <= cfg.budgetBytes) return { ok: true };
  const now = Date.now();
  if (now - lastEmergencySweepAt >= EMERGENCY_SWEEP_MIN_INTERVAL_MS) {
    lastEmergencySweepAt = now;
    await sweepR2(env, { reason: "emergency" });
    usage = await readUsage(env, true);
    if (usage.bytes + sizeBytes <= cfg.budgetBytes) return { ok: true };
  }
  return {
    ok: false,
    status: 507,
    error: "R2 storage budget exhausted",
    details: { used_bytes: usage.bytes, budget_bytes: cfg.budgetBytes, needed_bytes: sizeBytes },
  };
}

/** Record an accepted upload (read-modify-write of the counter; the sweep corrects drift). */
export async function recordPut(env: Env, sizeBytes: number): Promise<void> {
  const usage = await readUsage(env);
  await writeUsage(env, {
    bytes: usage.bytes + sizeBytes,
    objects: usage.objects + 1,
    updated_at: new Date().toISOString(),
    last_sweep_at: usage.last_sweep_at,
  });
}

export type SweepResult = {
  reason: string;
  listed: number;
  deleted_expired: number;
  deleted_evicted: number;
  bytes_before: number;
  bytes_after: number;
  objects_after: number;
  truncated: boolean;
};

/** Delete expired objects, then oldest-first until usage is <= 80% of budget. Runs from cron/admin/emergency only. */
export async function sweepR2(env: Env, opts: { reason?: string; now?: number } = {}): Promise<SweepResult> {
  const cfg = r2Config(env);
  const now = opts.now ?? Date.now();
  const cutoff = now - cfg.retentionDays * 86_400_000;
  const keep: { key: string; size: number; at: number }[] = [];
  const expired: string[] = [];
  let listed = 0;
  let bytesBefore = 0;
  let cursor: string | undefined;
  let pages = 0;
  let truncated = false;
  do {
    const page = await env.VIDEOS.list({ limit: 1000, cursor });
    pages++;
    for (const o of page.objects) {
      if (o.key.startsWith("_meta/")) continue;
      listed++;
      bytesBefore += o.size;
      const at = o.uploaded instanceof Date ? o.uploaded.getTime() : Number(o.uploaded) || 0;
      if (at < cutoff) expired.push(o.key);
      else keep.push({ key: o.key, size: o.size, at });
    }
    cursor = page.truncated ? page.cursor : undefined;
    if (cursor && pages >= MAX_LIST_PAGES) {
      truncated = true;
      break;
    }
  } while (cursor);

  let bytesAfter = keep.reduce((n, o) => n + o.size, 0);
  const evicted: string[] = [];
  const target = Math.floor(cfg.budgetBytes * EVICT_TARGET_FRACTION);
  if (bytesAfter > cfg.budgetBytes) {
    keep.sort((a, b) => a.at - b.at);
    let i = 0;
    while (bytesAfter > target && i < keep.length) {
      evicted.push(keep[i].key);
      bytesAfter -= keep[i].size;
      i++;
    }
    keep.splice(0, i);
  }
  for (const list of [expired, evicted]) {
    for (let i = 0; i < list.length; i += 1000) await env.VIDEOS.delete(list.slice(i, i + 1000));
  }
  const usage: R2Usage = {
    bytes: bytesAfter,
    objects: keep.length,
    updated_at: new Date(now).toISOString(),
    last_sweep_at: new Date(now).toISOString(),
  };
  // A truncated listing under-counts: keep the larger of measured/previous so we do not over-admit uploads.
  if (truncated) {
    const prev = await readUsage(env, true);
    usage.bytes = Math.max(usage.bytes, prev.bytes);
  }
  await writeUsage(env, usage);
  return {
    reason: opts.reason ?? "manual",
    listed,
    deleted_expired: expired.length,
    deleted_evicted: evicted.length,
    bytes_before: bytesBefore,
    bytes_after: usage.bytes,
    objects_after: usage.objects,
    truncated,
  };
}

/** Admin routes (mutating route is protected by the global API secret check). */
export async function handleR2Admin(request: Request, env: Env, path: string): Promise<Response | null> {
  if (path === "/api/admin/r2/usage" && request.method === "GET") {
    const cfg = r2Config(env);
    const usage = await readUsage(env, true);
    return json({ usage, config: cfg, headroom_bytes: Math.max(0, cfg.budgetBytes - usage.bytes) });
  }
  if (path === "/api/admin/r2/sweep" && request.method === "POST") {
    return json(await sweepR2(env, { reason: "admin" }));
  }
  return null;
}