import { Hono } from "hono";
import { cors } from "hono/cors";
import { planRecipe } from "../planner";

export interface Env {
  ASSETS: Fetcher;
  OPENAI_API_KEY?: string;
  OPENAI_MODEL?: string;
  /** Optional: URL of Node render service (e.g. http://127.0.0.1:8788) for /api/render proxy */
  VIDEO_AI_RENDER_URL?: string;
  VIDEO_AI_RENDER_SECRET?: string;
}

const app = new Hono<{ Bindings: Env }>();

app.use(
  "/*",
  cors({
    origin: "*",
    allowMethods: ["GET", "POST", "OPTIONS"],
    allowHeaders: ["Content-Type", "X-Video-AI-Key"],
  }),
);

app.options("/*", (c) => c.body(null, 204));

app.get("/api/health", (c) =>
  c.json({ ok: true, service: "video-ai-worker", ts: new Date().toISOString() }),
);

app.post("/api/plan", async (c) => {
  let body: { prompt?: string; targetDurationSec?: number; maxDurationSec?: number };
  try {
    body = await c.req.json();
  } catch {
    return c.json({ error: "Invalid JSON" }, 400);
  }
  const prompt = typeof body.prompt === "string" ? body.prompt.trim() : "";
  if (!prompt) return c.json({ error: "Missing prompt" }, 400);

  try {
    const { recipe, source } = await planRecipe({
      prompt,
      targetDurationSec: body.targetDurationSec,
      maxDurationSec: body.maxDurationSec,
      openaiApiKey: c.env.OPENAI_API_KEY,
      openaiModel: c.env.OPENAI_MODEL,
    });
    return c.json({ recipe, source });
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e);
    return c.json({ error: message }, 502);
  }
});

/**
 * Proxies to the Node FFmpeg service when VIDEO_AI_RENDER_URL is set (local dev or private URL).
 * In production you typically call the render service from your backend or a Workflow step instead.
 */
app.post("/api/render", async (c) => {
  const base = c.env.VIDEO_AI_RENDER_URL?.replace(/\/$/, "");
  if (!base) {
    return c.json(
      {
        error:
          "VIDEO_AI_RENDER_URL is not configured. Run the Node render service and set this secret/binding, or POST the recipe directly to the render server.",
      },
      501,
    );
  }

  let recipe: unknown;
  try {
    const body = await c.req.json();
    recipe = body && typeof body === "object" && "recipe" in body ? (body as { recipe: unknown }).recipe : body;
  } catch {
    return c.json({ error: "Invalid JSON" }, 400);
  }

  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (c.env.VIDEO_AI_RENDER_SECRET) {
    headers["X-Video-AI-Key"] = c.env.VIDEO_AI_RENDER_SECRET;
  }

  const res = await fetch(`${base}/render`, {
    method: "POST",
    headers,
    body: JSON.stringify({ recipe }),
  });

  if (!res.ok) {
    const text = await res.text();
    return c.json({ error: `Render service ${res.status}`, detail: text.slice(0, 400) }, 502);
  }

  return new Response(res.body, {
    headers: {
      "Content-Type": "video/mp4",
      "Cache-Control": "no-store",
    },
  });
});

app.notFound((c) => c.env.ASSETS.fetch(c.req.raw));

export default { fetch: app.fetch };
