# Video AI (side project)

Prompt-driven **recipe JSON** → **MP4** pipeline, kept separate from the main `motion.productions` Cloudflare app so it can mature and merge later.

## Architecture

| Piece | Role |
|--------|------|
| **Cloudflare Worker** (`src/worker`) | HTTP API: `POST /api/plan` (LLM or deterministic fallback), optional `POST /api/render` proxy, static UI from `public/`. |
| **Shared schema + planner** (`src/schema`, `src/planner`) | Zod-validated `VideoRecipe`, OpenAI JSON planner, offline fallback when no API key. |
| **Node render service** (`src/render`) | FFmpeg: solid-color scenes, optional captions, optional **OpenAI TTS narration** + **HTTPS background music** URL, concat, AAC mux. |

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

## Deploy render service (Fly.io or Railway)

The **render** app is the Docker image in this folder (`Dockerfile`): Node + FFmpeg + `POST /render`. It must be reachable over **HTTPS** so the motion.productions Worker can set `VIDEO_AI_RENDER_URL` to its **origin only** (no path), e.g. `https://motion-video-ai-render.fly.dev`.

**Env vars on the host**

| Variable | Required | Notes |
|----------|----------|--------|
| `VIDEO_AI_RENDER_SECRET` | Recommended | Same value as Worker secret `VIDEO_AI_RENDER_SECRET`; Worker sends it as header `X-Video-AI-Key`. |
| `OPENAI_API_KEY` | For TTS only | Set on the **render** host if recipes use `meta.audio.narration` (OpenAI `tts-1`). Never commit keys. |
| `PORT` | Auto | Fly.io and Railway inject this; the server reads `PORT` first. |
| `VIDEO_AI_FONT` | Optional | Path to a `.ttf` inside the container if `drawtext` cannot find a font. |

### Audio in the recipe (`meta.audio`)

- **`narration`**: `{ "text": "...", "voice": "alloy" }` (optional voice from OpenAI TTS set). Requires **`OPENAI_API_KEY`** on Railway (or local `npm run render`).
- **`backgroundMusicUrl`**: public **`https://`** URL to an audio file (mp3/aac/wav). Looped and mixed under narration if both are set (`backgroundMusicVolume` 0–1, default ~0.22).
- Omit `meta.audio` for a silent AAC bed (previous behavior).

**After deploy**

```bash
cd cloudflare
printf '%s' 'https://YOUR-RENDER-HOST' | npx wrangler secret put VIDEO_AI_RENDER_URL
```

Use **HTTPS** URL with **no trailing slash**.

### Railway (step-by-step)

Railway often **ignores “Dockerfile” in the UI** and runs **Railpack** instead (especially if a `railpack.json` exists — this repo **does not** ship one). Use **Method A** first; if the build log still starts with `Railpack`, use **Method B**.

#### Method A — Root Directory `video-ai`

1. **New service** → GitHub repo **`motion.productions`** (dedicated service; not the Python worker).

2. **Settings** → **Root Directory** → **`video-ai`** (exactly; no leading `/`).

3. **Settings** → **Build**:
   - Set builder to **Dockerfile** if the UI offers it.
   - **Dockerfile path:** `Dockerfile` (default).

4. **Variables** → **`VIDEO_AI_RENDER_SECRET`** (match Cloudflare).

5. **Networking** → **Generate Domain**.

6. **Deploy** and open **Build logs**. You want **`FROM node:22-bookworm-slim`** (Docker). If you see **`Railpack`** at the top, use **Method B**.

7. **Settings → Deploy → Custom Start Command:** leave **empty** (use Dockerfile / `railway.toml`) or set exactly  
   `node node_modules/tsx/dist/cli.mjs src/render/server.ts`.  
   If deploy logs show `> npm run start` / `npm error signal SIGTERM`, Railway is still running **`npm start`** as PID 1 — fix the start command or switch to **Dockerfile** builder (Method A/B).

#### Method B — Repo root + `Dockerfile.video-ai` (when Railpack keeps winning)

Some projects hit a Railway quirk: the UI flips back to **Railpack** even after choosing Dockerfile. Build from the **monorepo root** and point at the alternate Dockerfile (same image as `video-ai/Dockerfile`, FFmpeg included).

1. Same **new** Video AI service as above.

2. **Settings** → **Root Directory** → **clear it** (empty) so the root is the **repository root** (`motion.productions`), **not** `video-ai`.

3. **Settings** → **Build**:
   - Builder: **Dockerfile**
   - **Dockerfile path:** `Dockerfile.video-ai`  
     (file lives at the **repo root**, next to the Python `Dockerfile`.)

4. Do **not** rely on a root `railway.json` for this service if it would conflict with other services; the dashboard **Dockerfile path** is enough.

5. **Variables** / **Networking** / **Wrangler** same as Method A.

6. Build logs should show Docker steps and **`apt-get install ffmpeg`**.

7. Verify: `curl -sS https://YOUR-DOMAIN/health`

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
