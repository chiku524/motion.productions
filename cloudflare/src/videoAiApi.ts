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

export type VideoAiEnv = {
  OPENAI_API_KEY?: string;
  OPENAI_MODEL?: string;
  VIDEO_AI_RENDER_URL?: string;
  VIDEO_AI_RENDER_SECRET?: string;
};

export async function handleVideoAiApi(
  request: Request,
  env: VideoAiEnv,
  path: string,
): Promise<Response | null> {
  if (!path.startsWith("/video-ai/api/")) return null;

  const sub = path.slice("/video-ai/api".length);
  const route = sub === "" ? "/" : sub;

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

    const res = await fetch(`${base}/render`, {
      method: "POST",
      headers,
      body: JSON.stringify({ recipe }),
    });

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

  return json({ error: "Not found" }, 404);
}
