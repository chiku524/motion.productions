import { serve } from "@hono/node-server";
import { Hono } from "hono";
import { cors } from "hono/cors";
import { readFile, rm } from "node:fs/promises";
import { VideoRecipeSchema } from "../schema/recipe";
import { renderRecipeToMp4 } from "./ffmpeg-pipeline";

const app = new Hono();

app.use(
  "/*",
  cors({
    origin: "*",
    allowMethods: ["GET", "POST", "OPTIONS"],
    allowHeaders: ["Content-Type", "X-Video-AI-Key"],
  }),
);

app.get("/health", (c) => c.json({ ok: true, service: "video-ai-render" }));

app.post("/render", async (c) => {
  const secret = process.env.VIDEO_AI_RENDER_SECRET;
  if (secret) {
    const key = c.req.header("X-Video-AI-Key");
    if (key !== secret) return c.json({ error: "Unauthorized" }, 401);
  }

  let body: unknown;
  try {
    body = await c.req.json();
  } catch {
    return c.json({ error: "Invalid JSON" }, 400);
  }

  const raw =
    body && typeof body === "object" && "recipe" in body
      ? (body as { recipe: unknown }).recipe
      : body;

  const parsed = VideoRecipeSchema.safeParse(raw);
  if (!parsed.success) {
    return c.json({ error: "Invalid recipe", details: parsed.error.flatten() }, 400);
  }

  try {
    const { outputPath, workDir } = await renderRecipeToMp4(parsed.data);
    const buf = await readFile(outputPath);
    await rm(workDir, { recursive: true, force: true });
    return new Response(buf, {
      headers: {
        "Content-Type": "video/mp4",
        "Cache-Control": "no-store",
      },
    });
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e);
    return c.json({ error: message }, 500);
  }
});

const port = Number(process.env.VIDEO_AI_RENDER_PORT ?? "8788");
console.info(`video-ai render listening on http://127.0.0.1:${port}`);
serve({ fetch: app.fetch, port, hostname: "127.0.0.1" });
