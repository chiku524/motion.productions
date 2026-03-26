# Video AI (side project)

Prompt-driven **recipe JSON** → **MP4** pipeline, kept separate from the main `motion.productions` Cloudflare app so it can mature and merge later.

## Architecture

| Piece | Role |
|--------|------|
| **Cloudflare Worker** (`src/worker`) | HTTP API: `POST /api/plan` (LLM or deterministic fallback), optional `POST /api/render` proxy, static UI from `public/`. |
| **Shared schema + planner** (`src/schema`, `src/planner`) | Zod-validated `VideoRecipe`, OpenAI JSON planner, offline fallback when no API key. |
| **Node render service** (`src/render`) | FFmpeg: solid-color scenes, optional captions (with simple fade-in from motion keyframes), concat, silent video + AAC bed. |

**Why split Worker vs Node?** Workers are the right place for auth, planning, and orchestration. FFmpeg needs a long CPU-bound process and is run locally (or on a VM/container) via the render service.

## Prerequisites

- Node 20+
- [FFmpeg](https://ffmpeg.org/) on `PATH` (`ffmpeg -version`)

## Quick start (local)

Two terminals from this directory (`video-ai/`):

```bash
npm install
npm run render
```

```bash
npm run dev:worker
```

Open the URL Wrangler prints (often `http://127.0.0.1:8787`). Use **Plan** then **Render MP4**.

- Without `OPENAI_API_KEY`, planning uses the deterministic **fallback** (still produces a valid recipe).
- If the Worker is not given `VIDEO_AI_RENDER_URL`, the UI falls back to `http://127.0.0.1:8788/render` (same machine).

### OpenAI (optional)

```bash
npx wrangler secret put OPENAI_API_KEY
```

Or for local dev only, use a `.dev.vars` file (gitignored) in `video-ai/`:

```
OPENAI_API_KEY=sk-...
```

Optional vars: `OPENAI_MODEL` (default `gpt-4o-mini`), `VIDEO_AI_RENDER_URL`, `VIDEO_AI_RENDER_SECRET` (must match render server env).

### Render service security (optional)

```bash
set VIDEO_AI_RENDER_SECRET=your-secret   # Windows cmd
export VIDEO_AI_RENDER_SECRET=your-secret
```

Match the Worker secret `VIDEO_AI_RENDER_SECRET` when proxying `/api/render`.

### Font path (optional)

Override caption font:

```bash
set VIDEO_AI_FONT=C:\Windows\Fonts\arial.ttf
```

## API

- `POST /api/plan` — body `{ "prompt": "...", "targetDurationSec"?: number, "maxDurationSec"?: number }` → `{ recipe, source }`.
- `POST /api/render` — body `{ "recipe": { ... } }` → `video/mp4` when `VIDEO_AI_RENDER_URL` is set; otherwise use the Node server directly: `POST http://127.0.0.1:8788/render`.
- Render server: `GET /health`, `POST /render` (same body).

## On motion.productions

The main site exposes this lab at **[https://motion.productions/video-ai/](https://motion.productions/video-ai/)** (header link: “Video AI lab”). APIs live at `POST /video-ai/api/plan` and `POST /video-ai/api/render` on the same Worker. Configure `OPENAI_API_KEY` and optional `VIDEO_AI_RENDER_URL` / `VIDEO_AI_RENDER_SECRET` on that deployment for full behavior.

## Merge path into `motion.productions`

1. Move `src/schema` + `src/planner` into a shared package or `cloudflare/src` and keep a single `VideoRecipe` source of truth.
2. Expose planning behind your existing Worker auth/routes; store recipes and job IDs in D1/R2 as you do today.
3. Run FFmpeg on **dedicated compute** (container, VM, or third-party encode API) triggered from **Queues/Workflows**, not inside a short-lived Worker invocation.
4. Replace the demo UI with your product shell when ready.

## Limits (current MVP)

- Visuals are **solid fills** + **caption**; no images, TTS, or stock footage yet.
- Long videos are **possible** but encode time and disk scale linearly; add segmentation + stitch for production.
- Some FFmpeg builds differ on `drawtext` `alpha`; if render fails, upgrade FFmpeg or open an issue with the stderr snippet.
