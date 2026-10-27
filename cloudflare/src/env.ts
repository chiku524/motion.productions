/**
 * Cloudflare Worker environment bindings.
 */
export interface Env {
  DB: D1Database;
  VIDEOS: R2Bucket;
  MOTION_KV: KVNamespace;
  ASSETS: Fetcher;
  /** Shared secret for mutating /api/* (Bearer or X-Motion-Api-Key). Unset = allow (local dev). */
  MOTION_API_SECRET?: string;
  /** Video AI lab (/video-ai) — optional OpenAI + render proxy */
  OPENAI_API_KEY?: string;
  OPENAI_MODEL?: string;
  VIDEO_AI_RENDER_URL?: string;
  VIDEO_AI_RENDER_SECRET?: string;
  /** Python procedural render service (engine=procedural) */
  PROCEDURAL_RENDER_URL?: string;
  /** Max raw items accepted per POST /api/knowledge/discoveries (default 40, 3-80). */
  DISCOVERIES_MAX_ITEMS?: string;
  /** "1" re-enables the legacy single-writer KV lease for discoveries (costs 2 KV writes per POST; default off). */
  DISCOVERY_LEASE?: string;
  /** R2 free-tier guards (see docs/R2_FREE_TIER.md). Bytes / days; all optional. */
  R2_MAX_UPLOAD_BYTES?: string;
  R2_BUDGET_BYTES?: string;
  R2_RETENTION_DAYS?: string;
  /** D1 log retention (src/retention.ts): days to keep (3), rows per delete batch (<=500), batches per table per day (3), rows-written budget per daily run (6000), "1" disables. */
  RETENTION_DAYS?: string;
  RETENTION_BATCH_ROWS?: string;
  RETENTION_MAX_BATCHES?: string;
  RETENTION_WRITE_BUDGET?: string;
  RETENTION_DISABLED?: string;
  RETENTION_CHECK_INTERVAL_SEC?: string;
}
