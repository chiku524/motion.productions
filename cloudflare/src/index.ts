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
import { handleR2Admin, sweepR2 } from "./r2Budget";
import { dbFullResponse, isDbFullError, isFreeTierLimitError, limitResponse } from "./limits";

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
        // D1/KV free-tier daily limit: GET -> 200 degraded, writes -> 503 + Retry-After (15 min), never a bare 5xx storm.
        // D1 file full ("Exceeded maximum DB size"): always a degraded 200, never a 5xx (checked before the daily-quota branch).
        if (isDbFullError(e)) return dbFullResponse(request.method, { details: String(e) });
        if (isFreeTierLimitError(e)) return limitResponse(request.method, { details: String(e) });
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

  /** Optional: only runs if a cron trigger is configured. None is by default (Workers Free cap of 5 cron triggers per account was hit, error 10072);
   the daily retention sweep piggy-backs on uploads (r2Budget.reserveUpload). No D1/KV usage. */
  async scheduled(_event: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    ctx.waitUntil(
      sweepR2(env, { reason: "cron" })
        .then((r) => console.log("r2 sweep", JSON.stringify(r)))
        .catch((e) => console.error("r2 sweep failed:", e)),
    );
  },
};

async function handleApi(request: Request, env: Env, path: string): Promise<Response | null> {
  const authFail = requireApiSecret(request, env);
  if (authFail) return authFail;

  const handlers = [
    handleR2Admin,
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
