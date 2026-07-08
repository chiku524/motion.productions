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
}
