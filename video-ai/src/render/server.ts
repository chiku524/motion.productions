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

app.post("/jobs", async (c) => {
  const secret = process.env.VIDEO_AI_RENDER_SECRET;
  if (secret) {
    const key = c.req.header("X-Video-AI-Key");
    if (key !== secret) return c.json({ error: "Unauthorized" }, 401);
  }

  let body: {
    jobId?: string;
    recipeKey?: string;
    outputKey?: string;
    completeUrl?: string;
  };
  try {
    body = await c.req.json();
  } catch {
    return c.json({ error: "Invalid JSON" }, 400);
  }

  const jobId = typeof body.jobId === "string" ? body.jobId.trim() : "";
  const recipeKey = typeof body.recipeKey === "string" ? body.recipeKey.trim() : "";
  const outputKey = typeof body.outputKey === "string" ? body.outputKey.trim() : "";
  const completeUrl = typeof body.completeUrl === "string" ? body.completeUrl.trim() : "";
  if (!jobId || !recipeKey || !outputKey || !completeUrl) {
    return c.json({ error: "Missing jobId, recipeKey, outputKey, or completeUrl" }, 400);
  }

  const uuidRe = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
  if (!uuidRe.test(jobId)) {
    return c.json({ error: "Invalid jobId" }, 400);
  }
  const expectedPrefix = `video-ai/jobs/${jobId}/`;
  if (!recipeKey.startsWith(expectedPrefix) || !outputKey.startsWith(expectedPrefix)) {
    return c.json({ error: "Keys must be under video-ai/jobs/{jobId}/" }, 400);
  }

  const workerOrigins = (process.env.VIDEO_AI_WORKER_ORIGIN ?? "")
    .split(",")
    .map((s) => s.trim().replace(/\/$/, ""))
    .filter(Boolean);
  if (workerOrigins.length) {
    const suffix = `/video-ai/api/jobs/${jobId}/complete`;
    const allowed = workerOrigins.some((o) => completeUrl.startsWith(`${o}${suffix}`));
    if (!allowed) {
      return c.json({ error: "completeUrl does not match VIDEO_AI_WORKER_ORIGIN and job" }, 400);
    }
  }

  const notify = async (ok: boolean, error?: string) => {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (secret) headers["X-Video-AI-Key"] = secret;
    try {
      await fetch(completeUrl, {
        method: "POST",
        headers,
        body: JSON.stringify(ok ? { ok: true } : { ok: false, error: error ?? "failed" }),
      });
    } catch {
      /* best-effort */
    }
  };

  void (async () => {
    try {
      const { r2GetText, r2Put } = await import("./r2");
      const recipeJson = await r2GetText(recipeKey);
      let raw: unknown;
      try {
        raw = JSON.parse(recipeJson) as unknown;
      } catch {
        await notify(false, "Invalid recipe JSON in R2");
        return;
      }
      const parsed = VideoRecipeSchema.safeParse(raw);
      if (!parsed.success) {
        await notify(false, "Invalid recipe schema");
        return;
      }
      const { outputPath, workDir } = await renderRecipeToMp4(parsed.data);
      const buf = await readFile(outputPath);
      await rm(workDir, { recursive: true, force: true });
      await r2Put(outputKey, buf, "video/mp4");
      await notify(true);
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      await notify(false, message);
    }
  })();

  return c.json({ accepted: true, jobId }, 202);
});

const port = Number(process.env.PORT ?? process.env.VIDEO_AI_RENDER_PORT ?? "8788");
const hostname = process.env.VIDEO_AI_RENDER_HOST ?? "0.0.0.0";
console.info(`video-ai render listening on http://${hostname}:${port}`);
serve({ fetch: app.fetch, port, hostname });
