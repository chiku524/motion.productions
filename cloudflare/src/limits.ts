/**
 * Cloudflare Free-tier limit detection + graceful-degradation helpers.
 *
 * Free-tier hard limits (reset 00:00 UTC): D1 5M rows read / 100k rows written per day,
 * KV 100k reads / 1,000 writes per day. When one is hit the platform throws; we must
 * answer with stale/degraded data instead of a hard 5xx so the site and loops keep running.
 */

import { corsHeaders } from "./http";

const LIMIT_PATTERNS: RegExp[] = [
  /daily .*limit/i,
  /limit exceeded/i,
  /exceeded (the |your |its )?(free|daily|maximum|max|quota)/i,
  /(free tier|free plan|quota)/i,
  /rows? (read|written).*(limit|exceed)/i,
  /(kv|d1).*(limit|quota)/i,
  /too many requests/i,
  /\b429\b/,
  /\b7429\b/, // D1: exceeded CPU time limit
  /overloaded/i,
];

export function isFreeTierLimitError(e: unknown): boolean {
  if (e == null) return false;
  const parts: string[] = [];
  if (typeof e === "string") parts.push(e);
  if (e instanceof Error) {
    parts.push(e.message);
    const cause = (e as { cause?: unknown }).cause;
    if (cause instanceof Error) parts.push(cause.message);
    else if (typeof cause === "string") parts.push(cause);
  } else if (typeof e === "object") {
    const m = (e as { message?: unknown }).message;
    if (typeof m === "string") parts.push(m);
  }
  const text = parts.join(" | ");
  if (!text) return false;
  return LIMIT_PATTERNS.some((re) => re.test(text));
}

/** Seconds the client should wait before retrying after a limit error (next reset is <= 24 h away; poll gently). */
export const LIMIT_RETRY_AFTER_SEC = 900;

export function degradedBody(extra: Record<string, unknown> = {}): Record<string, unknown> {
  return { degraded: true, error: "free_tier_limit", retry_after_ms: LIMIT_RETRY_AFTER_SEC * 1000, ...extra };
}
/**
 * Response for a request that hit a daily limit. Reads get HTTP 200 with a degraded marker (callers keep running on
 * stale data); writes get 503 + Retry-After so clients back off instead of hammering a blocked binding.
 */
export function limitResponse(method: string, extra: Record<string, unknown> = {}): Response {
  const body = JSON.stringify(degradedBody(extra));
  const isRead = method === "GET" || method === "HEAD";
  return new Response(body, {
    status: isRead ? 200 : 503,
    headers: {
      "Content-Type": "application/json",
      "X-Degraded": "free_tier_limit",
      "Retry-After": String(LIMIT_RETRY_AFTER_SEC),
      ...corsHeaders,
    },
  });
}
