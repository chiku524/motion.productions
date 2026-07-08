import type { Env } from "./env";
import { err } from "./http";

const MUTATING = new Set(["POST", "PUT", "PATCH", "DELETE"]);

/**
 * When MOTION_API_SECRET is set, mutating requests must present it via
 * Authorization: Bearer <secret> or X-Motion-Api-Key: <secret>.
 * When unset (local wrangler), writes are allowed for DX.
 */
export function requireApiSecret(request: Request, env: Env): Response | null {
  if (!MUTATING.has(request.method.toUpperCase())) return null;
  const secret = (env.MOTION_API_SECRET || "").trim();
  if (!secret) return null;

  const auth = request.headers.get("Authorization") || "";
  const bearer = auth.toLowerCase().startsWith("bearer ") ? auth.slice(7).trim() : "";
  const headerKey = (request.headers.get("X-Motion-Api-Key") || "").trim();
  if (bearer === secret || headerKey === secret) return null;
  return err("Unauthorized", 401);
}

export function isMutatingMethod(method: string): boolean {
  return MUTATING.has(method.toUpperCase());
}
