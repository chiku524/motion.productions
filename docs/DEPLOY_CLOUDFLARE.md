# Deploying to Cloudflare (motion.productions)

This project includes a **Cloudflare Worker** that uses **KV**, **D1**, and **R2** so you can run the API and storage on your domain **motion.productions** and manage everything from the terminal with Wrangler.

## GitHub → Deploy on push

Every push to `main` triggers an automatic deployment via GitHub Actions. To enable this:

1. Add these **repository secrets** in GitHub: **Settings → Secrets and variables → Actions**
   - `CLOUDFLARE_API_TOKEN` — Create at [Cloudflare API Tokens](https://dash.cloudflare.com/profile/api-tokens). Use **Edit Cloudflare Workers** template, or create a custom token with: **Account** → Cloudflare Workers Scripts Read & Write, Account Settings Read; **Workers R2 Storage** → Object Read & Write; **Workers KV Storage** → Edit; **D1** → Edit. Zone permissions are not required for deploy.
   - `CLOUDFLARE_ACCOUNT_ID` — `10374f367672f4d19db430601db0926b`

2. Push to `main`. The workflow runs `wrangler d1 migrations apply` then `wrangler deploy`.

You can also trigger a deploy manually from **Actions → Deploy to Cloudflare → Run workflow**.

> **Security:** Never commit API tokens. Store them only in GitHub Secrets. If a token was ever shared or exposed, rotate it in the Cloudflare dashboard and update the secret.

## What gets deployed

- **Worker** — Serves the API and app at `https://motion.productions`.
- **D1** — SQL database:
  - `jobs` — prompt, status, R2 key (video storage reference).
  - `learning_runs` — logged runs for learning (prompt, spec, analysis).
  - **Static registry (per frame):** `static_colors`, `static_sound` — per-frame color and sound discoveries.
  - **Dynamic registry (per window / whole-video):** `learned_blends`, `learned_colors`, `learned_motion`, `learned_lighting`, `learned_composition`, `learned_graphics`, `learned_temporal`, `learned_technical` — discoveries from the intended loop.
  - **Narrative registry:** `narrative_entries` — themes, plots, settings, genre, mood, scene_type (film aspects).
  - `name_reserve` — used names for uniqueness.
- **R2** — Bucket for stored video files (`jobs/{id}/video.mp4`).
- **KV** — Cached learning stats (`learning:stats`, 60s TTL) and **loop config/state** (`loop_config`, `loop_state`) for the webapp and Railway workers. **Optimization:** We do not use KV *delete* operations (free tier limit: 1000/day). Cache is invalidated by TTL only; GET recomputes when stale.
  - **KV daily limit:** Cloudflare free tier has a daily read/write limit for KV. If you receive an email that the KV worker reached its daily limit, **loop config save** (e.g. Exploit/Explore percentage, Apply settings) will fail until the limit resets. Reduce write frequency (e.g. fewer loop state saves, or upgrade plan) if you hit this often.

## Prerequisites

1. **Node.js** (v18+) and npm.
2. **Cloudflare account** with the zone **motion.productions** added (you purchased the domain via Cloudflare, so the zone should already be there).
3. **Wrangler CLI** — installed via the project’s `package.json` in `cloudflare/`.

## One-time setup (terminal)

### 1. Log in to Cloudflare

From the project root:

```bash
cd cloudflare
npm install
npx wrangler login
```

A browser window will open; complete the login so Wrangler can use your account.

### 2. Create D1 database (if not using auto-provisioning)

If you use **Wrangler 4.45+**, you can skip this and let the first deploy create the database (see step 4). Otherwise, create the database and add its ID to the config:

```bash
npx wrangler d1 create motion-productions-db
```

Copy the **database_id** from the output and add it to `cloudflare/wrangler.jsonc` inside the `d1_databases` entry:

```jsonc
"d1_databases": [
  { "binding": "DB", "database_name": "motion-productions-db", "database_id": "<paste-id-here>" }
],
```

### 3. Apply D1 migrations

Migrations apply **all** pending migration files (current and any added in the future). From the **project root**:

```bash
# Remote (production)
python scripts/run_d1_migrations.py
# or: bash scripts/run_d1_migrations.sh

# Local (development)
python scripts/run_d1_migrations.py --local
# or: bash scripts/run_d1_migrations.sh --local
```

Or run Wrangler directly from the **`cloudflare/`** directory:

```bash
cd cloudflare
npx wrangler d1 migrations apply motion-productions-db --remote
npx wrangler d1 migrations apply motion-productions-db --local   # for local D1
```

### 4. Deploy the Worker

From `cloudflare/`:

```bash
npx wrangler deploy
```

- On first deploy with **Wrangler 4.45+**, KV, R2, and (if configured without `database_id`) D1 can be **auto-provisioned**; the command will create the resources and link them to the Worker.
- If you see errors about **routes** (e.g. zone not found), ensure the domain **motion.productions** is added to your Cloudflare account and the zone is active. You can temporarily comment out the `routes` block in `wrangler.jsonc` and rely on `workers_dev: true` to get a `*.workers.dev` URL for testing.

After a successful deploy you’ll see:

- **Worker URL** (e.g. `https://motion-productions.<account>.workers.dev`).
- If routes are configured: **https://motion.productions** will serve the same Worker.

## Custom domain (motion.productions)

1. In **Cloudflare Dashboard** → **Websites** → **motion.productions** → **Workers Routes** (or **Workers & Pages** → your Worker → **Settings** → **Domains & Routes**), add a route so that `motion.productions/*` is handled by the Worker **motion-productions**.
2. If you used the `routes` block in `wrangler.jsonc` with `zone_name: "motion.productions"`, Wrangler may have already created the route on deploy; confirm in the dashboard.

## Web app

The Worker serves the app UI at **https://motion.productions** — prompt input, job creation, status polling, and video playback when complete.

## API endpoints

- **GET /health** — Health check.
- **POST /api/jobs** — Create a job. Body: `{ "prompt": "your prompt", "duration_seconds": 6 }`. Returns `{ "id", "prompt", "status": "pending" }`.
- **GET /api/jobs?status=pending** — List pending jobs (for the generator bridge).
- **POST /api/learning** — Log a run for learning (D1). Body: `{ job_id?, prompt, spec, analysis }`.
- **POST /api/knowledge/discoveries** — Record discoveries to D1 (colors, blends with primitive depths, motion, lighting, etc.). Called by generate_bridge/automate_loop when `--learn` is used.
- **GET /api/knowledge/for-creation** — Fetch learned colors and motion for the next loop iteration. Used by creation to refine parameters from cloud-stored discoveries.
- **POST /api/knowledge/name/take** — Reserve a unique name for a discovery.
- **GET /api/knowledge/colors?key=...** — Check if color key exists.
- **GET /api/learning/runs** — List learning runs (optional `?limit=100`).
- **GET /api/learning/stats** — Aggregated stats (by palette, by keyword). Cached in KV.
- **POST /api/events** — Log user interaction. Body: `{ event_type, job_id?, payload? }`. Types: `prompt_submitted`, `job_completed`, `video_played`, `video_abandoned`, `download_clicked`, `error`, `feedback`.
- **GET /api/events** — List events (optional `?limit=500`, `?type=prompt_submitted`).
- **POST /api/jobs/:id/feedback** — Rate video. Body: `{ rating: 1|2 }` (1=thumbs down, 2=thumbs up).
- **GET /api/feedback** — List feedback with prompts (for learning pipeline).
- **GET /api/knowledge/prompts** — Distinct prompts from jobs (for automation to avoid duplicates).
- **GET /api/jobs/:id** — Get job status and, if completed, `download_url`.
- **POST /api/jobs/:id/upload** — Upload video (raw body or `multipart/form-data` with field `file`). Marks job as completed and stores the file in R2.
- **GET /api/jobs/:id/download** — Stream the video from R2.

## Workflow: web app + generator bridge

1. **Web app:** Users visit https://motion.productions, enter a prompt and duration, click Generate. A job is created (status: `pending`).

2. **Generator bridge:** Run the bridge script locally (or on a server with Python + FFmpeg) to process pending jobs:
   ```bash
   python scripts/generate_bridge.py
   # Or: python scripts/generate_bridge.py --once   # one job then exit
   # Or: python scripts/generate_bridge.py --learn  # log for learning
   ```
   The bridge fetches pending jobs from **GET /api/jobs?status=pending**, runs the procedural pipeline, and uploads via **POST /api/jobs/:id/upload**.

3. **Polling:** The web app polls **GET /api/jobs/:id**. When status is `completed`, it shows the video and download link.

### Manual workflow (CLI)

1. Create a job via API (or the web app).
2. Run `python scripts/generate.py "Sunset over the ocean" --duration 5 --output output/out.mp4`.
3. Upload: `curl -X POST "https://motion.productions/api/jobs/<JOB_ID>/upload" -F "file=@output/out.mp4"`.

## Useful commands (from `cloudflare/`)

| Command | Purpose |
|--------|--------|
| `npm run dev` | Local Worker dev server (with D1/R2/KV local or remote). |
| `npm run deploy` | Deploy Worker (and provision resources if using auto-provision). |
| `npm run db:migrate` | Apply D1 migrations to **remote** DB. |
| `npm run db:migrate:local` | Apply D1 migrations to **local** DB. |
| `npx wrangler d1 execute motion-productions-db --remote --command "SELECT * FROM jobs LIMIT 5"` | Run a quick SQL check. |
| `npx wrangler r2 bucket list` | List R2 buckets (after at least one deploy). |

## Learning through user experience

The app uses D1 and KV for learning:

1. **D1 `learning_runs`** — When `scripts/generate_bridge.py --learn` runs, it POSTs `{ prompt, spec, analysis }` to `/api/learning`. Each run is stored for aggregation.
2. **KV `learning:stats`** — Aggregated stats (by palette, by keyword) are cached with a 5‑min TTL. `GET /api/learning/stats` returns them; cache is invalidated when a new run is logged.
3. **R2** — Video files remain in R2; the learning pipeline uses analysis (color, motion, etc.) derived from the generated video before upload.

## Troubleshooting

- **“Zone not found” / route errors** — Ensure **motion.productions** is added as a site in Cloudflare and the zone is active. Deploy without `routes` first (comment them out) and use the `workers.dev` URL.
- **D1 “database not found”** — Run `npx wrangler d1 migrations apply motion-productions-db --remote` after the first deploy. If you created the DB manually, ensure `database_id` in `wrangler.jsonc` matches.
- **R2 404 on download** — Confirm the job status is `completed` and that upload was successful (check Worker logs or R2 in the dashboard).
