/**
 * Motion Productions — Cloudflare Worker API
 * Uses: D1 (jobs), R2 (video files), KV (optional cache/config)
 */

import { requireApiSecret } from "./auth";
import { corsHeaders, json } from "./http";
import type { Env } from "./env";
import { handleVideoAiApi } from "./videoAiApi";
import { handleInterpretationRoutes } from "./routes/interpretation";
import { handleJobsRoutes } from "./routes/jobs";
import { handleKnowledgeRoutes } from "./routes/knowledge";
import { handleLoopRoutes } from "./routes/loop";
import { handleRegistriesRoutes } from "./routes/registries";

export type { Env };

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    if (request.method === "OPTIONS") return new Response(null, { headers: corsHeaders });

    const url = new URL(request.url);
    const path = url.pathname;

    if (path === "/health" || path === "/api/health") {
      return json({ ok: true, service: "motion-productions" });
    }

    if (path === "/security.txt" || path === "/.well-known/security.txt") {
      const securityTxt = [
        "Contact: mailto:security@motion.productions",
        "Expires: 2026-12-31T23:59:59.000Z",
        "Preferred-Languages: en",
        "Canonical: https://motion.productions/.well-known/security.txt",
      ].join("\n");
      return new Response(securityTxt, {
        headers: {
          "Content-Type": "text/plain; charset=utf-8",
          "Cache-Control": "max-age=86400",
        },
      });
    }

    if (path === "/video-ai") {
      return Response.redirect(new URL("/video-ai/", request.url).toString(), 302);
    }

    const videoAiResponse = await handleVideoAiApi(request, env, path, ctx);
    if (videoAiResponse) return videoAiResponse;

    if (path.startsWith("/api/")) {
      try {
        const apiResponse = await handleApi(request, env, path);
        if (apiResponse) return apiResponse;
      } catch (e) {
        console.error("handleApi threw:", e);
        return new Response(
          JSON.stringify({ error: "Service temporarily unavailable", details: String(e) }),
          {
            status: 503,
            headers: {
              "Content-Type": "application/json",
              ...corsHeaders,
              "Retry-After": "3",
            },
          },
        );
      }
    }

    return env.ASSETS.fetch(request);
  },
};

async function handleApi(request: Request, env: Env, path: string): Promise<Response | null> {
  const authFail = requireApiSecret(request, env);
  if (authFail) return authFail;

  const handlers = [
    handleJobsRoutes,
    handleLoopRoutes,
    handleInterpretationRoutes,
    handleKnowledgeRoutes,
    handleRegistriesRoutes,
  ];
  for (const handler of handlers) {
    const res = await handler(request, env, path);
    if (res) return res;
  }
  return json({ error: "Not found" }, 404);
}
