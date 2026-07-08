# Video AI (side project)

Prompt-driven **recipe JSON** → **MP4** pipeline, kept separate from the main `motion.productions` Cloudflare app so it can mature and merge later.

## Engines

| `meta.engine` | Path | Notes |
|---------------|------|--------|
| `recipe` (default) | Worker → `VIDEO_AI_RENDER_URL` (Node + FFmpeg) | Solid-color scenes, captions, optional TTS/music |
| `procedural` | Worker → `PROCEDURAL_RENDER_URL` (Python `generate_full_video`) | Full procedural engine; set `meta.prompt`; sync `/video-ai/api/render` only |

Long-term consolidation: keep one recipe schema; route `engine` to the appropriate render host. The procedural path reuses the main learning-loop renderer rather than embedding Python in Node.

## Architecture

| Piece | Role |
|--------|------|
| **Cloudflare Worker** (`src/worker` + main `cloudflare/src/videoAiApi.ts`) | HTTP API: `POST /video-ai/api/plan`, `POST /video-ai/api/render` (recipe or procedural proxy), optional async jobs for recipe engine |
| **Shared schema + planner** (`src/schema`, `src/planner`) | Zod-validated `VideoRecipe` (`meta.engine`, `meta.prompt`), OpenAI JSON planner, offline fallback |
| **Node render service** (`src/render`) | FFmpeg: solid-color scenes, optional captions, optional **OpenAI TTS narration** + **HTTPS background music** URL |
| **Procedural render** (`scripts/procedural_render_server.py`, `fly.procedural-render.toml`) | `POST /render` → MP4 via Python procedural pipeline |

**Why split Worker vs Node/Python?** Workers are the right place for auth, planning, and orchestration. FFmpeg and procedural generation need long CPU-bound processes on Fly.

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

## Deploy render service (Fly.io primary)

The **render** app is the Docker image in this folder (`Dockerfile`): Node + FFmpeg + `POST /render`. It must be reachable over **HTTPS** so the motion.productions Worker can set `VIDEO_AI_RENDER_URL` to its **origin only** (no path), e.g. `https://motion-productions.fly.dev`.

**Env vars on the host**

| Variable | Required | Notes |
|----------|----------|--------|
| `VIDEO_AI_RENDER_SECRET` | Recommended | Same value as Worker secret `VIDEO_AI_RENDER_SECRET`; Worker sends it as header `X-Video-AI-Key`. |
| `OPENAI_API_KEY` | For TTS only | Set on the **render** host if recipes use `meta.audio.narration` (OpenAI `tts-1`). Never commit keys. |
| `PORT` | Auto | Fly sets this to match `fly.toml` `internal_port`; other hosts may inject `PORT` too. The server reads `PORT` first. |
| `VIDEO_AI_FONT` | Optional | Path to a `.ttf` inside the container if `drawtext` cannot find a font. |

### Audio in the recipe (`meta.audio`)

- **`narration`**: `{ "text": "...", "voice": "alloy" }` (optional voice from OpenAI TTS set). Requires **`OPENAI_API_KEY`** on the render host (or local `npm run render`).
- **`backgroundMusicUrl`**: public **`https://`** URL to an audio file (mp3/aac/wav). Looped and mixed under narration if both are set (`backgroundMusicVolume` 0–1, default ~0.22).
- Omit `meta.audio` for a silent AAC bed (previous behavior).

**After deploy**

```bash
cd cloudflare
printf '%s' 'https://YOUR-RENDER-HOST' | npx wrangler secret put VIDEO_AI_RENDER_URL
```

Use **HTTPS** URL with **no trailing slash**.

### Other Docker hosts (monorepo root)

To build from the repository root (same image as `video-ai/Dockerfile`), use **`Dockerfile.video-ai`** at the repo root as the Dockerfile path and set **`VIDEO_AI_RENDER_SECRET`** (and optional **`OPENAI_API_KEY`**) on the service. Verify: `curl -sS https://YOUR-HOST/health`.

### Fly.io

1. Install the [Fly CLI](https://fly.io/docs/hands-on/install-flyctl/) and run `fly auth login`.
2. The repo ships **`video-ai/fly.toml`** for app **`motion-productions`** (HTTP service on **8080**, health **`GET /health`**). From the **`video-ai`** directory (Docker build context must be this folder):

   ```bash
   cd video-ai
   fly deploy
   ```

   If you created the Fly app in the dashboard with a **different** name, either rename the app in Fly or set `app = "your-name"` in `fly.toml` before deploying.

   New app from CLI (only if you do not already have one):

   ```bash
   cd video-ai
   fly launch --no-deploy --copy-config
   fly deploy
   ```

3. **Secrets** (match Cloudflare Worker `VIDEO_AI_RENDER_SECRET`):

   ```bash
   cd video-ai
   fly secrets set VIDEO_AI_RENDER_SECRET=your-secret-here
   ```

4. After deploy, the default URL is **`https://motion-productions.fly.dev`** (or `https://<app>.fly.dev` if you changed `app`). Fly sets **`PORT`** to match `internal_port` (8080).
5. Set Worker `VIDEO_AI_RENDER_URL` to that HTTPS origin (no trailing slash).

**Health check:** `GET https://YOUR-HOST/health` should return `{ "ok": true, "service": "video-ai-render" }`.

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
