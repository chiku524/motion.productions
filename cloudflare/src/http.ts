export const corsHeaders: Record<string, string> = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, PATCH, PUT, DELETE, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Motion-Api-Key, X-Video-AI-Key",
};

export function json<T>(data: T, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json", ...corsHeaders },
  });
}

export function err(message: string, status = 400): Response {
  return json({ error: message }, status);
}

export function uuid(): string {
  return crypto.randomUUID();
}

/** Opacity may be stored as 0–1, 0–100, or mis-scaled (e.g. 10000); normalize to 0–100 for UI/export. */
export function normalizeOpacityToPercent(v: unknown): number {
  if (typeof v !== "number" || !Number.isFinite(v)) return 0;
  if (v <= 1) return Math.round(v * 100);
  if (v <= 100) return Math.round(v);
  if (v <= 10000) return Math.min(100, Math.round(v / 100));
  return 100;
}
