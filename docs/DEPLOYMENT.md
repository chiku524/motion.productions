# Deployment

This document covers the **Cloudflare Worker** (API, D1, R2, KV) and **Fly.io** background loop workers (Explorer, Exploiter, Balanced, Interpretation, Sound).

## Cloudflare Worker (motion.productions)


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
- **KV** — Cached learning stats (`learning:stats`, 60s TTL) and **loop config/state** (`loop_config`, `loop_state`) for the webapp and background workers. **Optimization:** We do not use KV *delete* operations (free tier limit: 1000/day). Cache is invalidated by TTL only; GET recomputes when stale.
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

### 3. Enable D1 Read Replication (recommended for multiple workers)

For production with several background workers hitting D1 concurrently, enable **Read Replication** to spread read load across replicas and reduce CPU time limit errors:

1. Go to **Cloudflare Dashboard** → **Workers & Pages** → **D1** → **motion-productions-db**
2. Open **Settings** → **Read Replication**
3. Click **Enable**

The Worker uses the D1 Sessions API (`withSession("first-unconstrained")`) so reads can be served by replicas; writes always go to the primary. If Read Replication is not enabled, the Worker falls back to the primary with no change in behavior.

### 4. Apply D1 migrations

Migrations apply **all** pending migration files (current and any added in the future). From the **project root**:

```bash
# Remote (production) — uses retries and backoff on D1 CPU limit (7429)
python scripts/run_d1_migrations.py

# Local (development)
python scripts/run_d1_migrations.py --local
```

The script retries up to 5 times with exponential backoff (30s → 45s → …) if D1 returns "exceeded its CPU time limit" (code 7429). Heavy migrations (e.g. multiple `ALTER TABLE` in one file) are split into one-statement files under `cloudflare/migrations/` to stay under the per-query CPU limit.

**If a single migration still hits the CPU limit** (e.g. one `ALTER TABLE` on a very large table like `static_colors`), run migrations **one at a time** with a long pause between each so D1 can recover:

```bash
python scripts/run_d1_migrations.py --one-by-one --remote --start-after 0011_learned_gradient_camera.sql
```

This applies each pending migration file via `wrangler d1 execute --file`, records it in `d1_migrations`, then waits 120 seconds (configurable with `--delay N`) before the next.

**If even one ALTER still fails with 7429**, the table is too large for D1’s per-query CPU budget. You can:

1. **Shrink the table, then migrate** – Delete old rows in small batches so the ALTER runs under the limit. Use `python scripts/trim_static_colors_for_migration.py --remote --dry-run` to see the current row count, then run without `--dry-run` with e.g. `--keep 50000` to keep the newest 50k rows (deletes in batches). If deletes hit the CPU limit, try `--batch-size 1000`. Then re-run the one-by-one migration.
2. **Apply the ALTER in the Cloudflare D1 dashboard** – In **D1 → your database → Console**, run the single statement from the failing migration file (e.g. `ALTER TABLE static_colors ADD COLUMN depth_breakdown_json TEXT;`). If it succeeds, mark the migration applied: `INSERT INTO d1_migrations (name) VALUES ('0012_1_static_colors_depth.sql');` Then continue with the rest via the script or dashboard.

If the script reports "No applied migrations found" and tries to run from `0000_initial.sql`, it will abort to avoid re-running the initial migration on an existing DB. Use `--start-after 0011_learned_gradient_camera.sql` to run only 0012_1 and later (the depth/strength migrations), or `--allow-initial` only if the DB is truly empty.

**`wrangler d1 migrations apply` fails immediately with 7429** — Wrangler still has to reconcile pending migrations; the first pending file may be a heavy `ALTER` on `static_colors`. You can **apply specific small migrations only** (e.g. temporal/technical depth columns) without running the full queue:

```bash
python scripts/run_d1_migrations.py --one-by-one --remote --only 0018_learned_temporal_depth.sql,0019_learned_technical_depth.sql --delay 60
```

If recording fails with **`UNIQUE constraint failed: d1_migrations.name`**, the migration name is already in `d1_migrations` (e.g. an earlier failed `ALTER` was still recorded). Re-run with `--only` for the **remaining** files only. The migration script uses **`INSERT OR IGNORE`** and re-checks `d1_migrations` so duplicate inserts are treated as success.

**7429 on a no-op `SELECT 1` migration** — On very large remote databases, Wrangler can hit D1 CPU **7429** even for **`SELECT 1`** (`d1 execute --file` or `--command`). For migrations that are **only** comments + `SELECT 1` (e.g. **0018** / **0019**), `scripts/run_d1_migrations.py` **skips remote execute** and only **`INSERT`s into `d1_migrations`** (schema for those is **Worker-managed**). For local D1, it still runs `SELECT 1` via `--command`. If **`INSERT` into `d1_migrations` also fails with 7429**, add the row in the **D1 dashboard** SQL console, then continue.

Resolve the blocking pending migrations separately (trim `static_colors`, D1 dashboard, or one-by-one from `--start-after 0011_...`). After that, `npx wrangler d1 migrations apply motion-productions-db --remote` may succeed again.

**Note:** D1's SQLite does not support `ADD COLUMN IF NOT EXISTS`. Migrations use plain `ADD COLUMN`. If a migration fails with **"duplicate column name"**, that column was already added (e.g. by a previous partial run). You can mark that migration as applied by inserting its name into the `d1_migrations` table via the D1 dashboard or `wrangler d1 execute ... --remote`, then re-run the migration script.

Migrations **`0018_learned_temporal_depth.sql`** and **`0019_learned_technical_depth.sql`** are **no-op** `SELECT 1` files (ordering + marking applied). **`learned_dynamic_meta`** and its indexes are created at **runtime in the Worker** (`ensureLearnedDynamicMetaTable` in `cloudflare/src/index.ts`) because remote migration **import** can still hit D1 CPU limit **7429** on very large databases even for `CREATE TABLE`. Temporal/technical **depth_breakdown** is stored in `learned_dynamic_meta` (`aspect` = `temporal` | `technical`, `profile_key`, `depth_breakdown_json`). The Worker reads/writes that table; `learned_temporal` / `learned_technical` rows stay unchanged. **Deploy the Worker** after pulling this change so production creates the table on first use.

Or run Wrangler directly from the **`cloudflare/`** directory:

```bash
cd cloudflare
npx wrangler d1 migrations apply motion-productions-db --remote
npx wrangler d1 migrations apply motion-productions-db --local   # for local D1
```

### 5. Deploy the Worker

**Important:** Wrangler config lives in **`cloudflare/wrangler.jsonc`**. Running `wrangler deploy` from the **repo root** fails with *Missing entry-point*. Always deploy from `cloudflare/`:

```bash
cd cloudflare
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

## Security (Cloudflare Dashboard)

### Critical — Managed Rules (WAF)

**Risk:** No WAF protection against SQLi, XSS, and known CVEs.

**Fix:** Cloudflare Dashboard → zone **motion.productions** → **Security** → **WAF** → enable **Cloudflare Managed Ruleset** (OWASP Core Ruleset, SQLi, XSS). Optionally enable **Cloudflare OWASP Core Ruleset** if listed.

### Moderate — Block AI Bots

**Security** → **Bots** → turn **Block AI bots** On to block known AI crawlers (GPTBot, ClaudeBot, etc.).

### Moderate — Bot settings from previous plan

**Security** → **Bots** — If you changed plans, turn off any options marked "from previous plan" or no longer supported. Re-test the site after changes.

### Security.txt

The Worker serves `/.well-known/security.txt` and `/security.txt` with `mailto:security@motion.productions` and expiry 2026-12-31. Edit `cloudflare/src/index.ts` (search for `security.txt`) to change.

---

## Fly.io background workers (loop services)


Use this to confirm **Explorer**, **Exploiter**, **Balanced**, **Interpretation**, and **Sound** are running. The Docker image default CMD is `python scripts/worker_start.py`; which script actually runs is controlled per service by the env var **WORKER_START_SCRIPT** (see below). The three video workflows differ by **prompt choice** (explore / exploit / UI) and **extraction focus** (frame vs window): **2 workers** do per-frame (pure/static) extraction only; **1 worker** does per-window (blended) extraction only. Set **LOOP_EXTRACTION_FOCUS** on each service as below.

---

## 1. Project layout (Fly.io)

Production setup uses **[Fly Machines](https://fly.io/docs/machines/)** with **one Fly app per worker role** so each machine gets the right **environment** (explore vs exploit vs window, etc.). All apps build the same **`Dockerfile`** at the **repository root**.

| Fly config (repo root) | Fly `app` name | Role |
|------------------------|----------------|------|
| `fly.loop-explorer.toml` | `motion-loop-explorer` | Explorer (frame, 100% explore) |
| `fly.loop-exploiter.toml` | `motion-loop-exploiter` | Exploiter (frame, 100% exploit) |
| `fly.loop-balanced.toml` | `motion-loop-balanced` | Balanced (window, UI ratio) |
| `fly.loop-interpret.toml` | `motion-loop-interpret` | Interpretation worker only |
| `fly.loop-sound.toml` | `motion-loop-sound` | Sound discovery worker only |

**Video AI FFmpeg render** (separate stack) lives under `video-ai/` with **`video-ai/fly.toml`** (e.g. app `motion-productions`) — see `video-ai/README.md`.

### Deploy / update a loop worker

From the **repository root**, with [Fly CLI](https://fly.io/docs/hands-on/install-flyctl/) installed:

```bash
fly auth login
# First time only (repeat per app name):
fly apps create motion-loop-explorer

fly deploy --config fly.loop-explorer.toml
# …repeat for balanced, exploiter, interpret, sound as needed
```

Each toml sets **`HEALTH_PORT=8080`** so the minimal HTTP health server in the loop process answers Fly **`http_service`** checks on `/`.

**Default container command:** `python scripts/worker_start.py` (from the `Dockerfile`). Video loops leave **`WORKER_START_SCRIPT`** unset so it runs **`automate_loop`**. Interpretation and sound set **`WORKER_START_SCRIPT`** in the toml.

**Same repo** for all: root = repo root (not `cloudflare/`). Only **environment variables** (and optional Fly scaling) differ per app.

**Reconfiguration summary:** Add **LOOP_EXTRACTION_FOCUS** to each of the 3 video services. No new secrets; only env vars below.

| Service    | LOOP_EXTRACTION_FOCUS | LOOP_EXPLOIT_RATIO_OVERRIDE | LOOP_WORKFLOW_TYPE | What it does |
|------------|------------------------|-----------------------------|--------------------|--------------|
| **Explorer**  | `frame` | `0` | `explorer` | Per-frame extraction only (static registry); 100% explore; authentic names. |
| **Exploiter** | `frame` | `1` | `exploiter` | Per-frame extraction only (static registry); 100% exploit; authentic names. |
| **Balanced**  | `window` | (do not set) | `main` (optional) | Per-window extraction only (dynamic + narrative + whole-video blends); ratio from UI. |

**Interpretation** (no video): no LOOP_EXTRACTION_FOCUS; uses `interpret_loop.py` and `API_BASE` only.

---

## 2. Service 1 — Explorer (frame-focused, 100% explore)

| Setting | Value |
|--------|--------|
| **Service name** | e.g. `motion-explorer` or `motion-loop-explorer` |
| **Root Directory** | (empty or repo root) |
| **Builder** | Dockerfile |
| **Start Command** | `python scripts/automate_loop.py` |

**Environment variables (required):**

| Variable | Value |
|----------|--------|
| `API_BASE` | `https://motion.productions` |
| `LOOP_EXTRACTION_FOCUS` | `frame` |
| `LOOP_EXPLOIT_RATIO_OVERRIDE` | `0` |

**Optional (for badge):**

| Variable | Value |
|----------|--------|
| `LOOP_WORKFLOW_TYPE` | `explorer` |

Effect: **Per-frame extraction only** (pure/static registry); 100% **explore** prompts. New values get authentic names. Videos show **Explore** on the site.

---

## 3. Service 2 — Exploiter (frame-focused, 100% exploit)

| Setting | Value |
|--------|--------|
| **Service name** | e.g. `motion-exploiter` or `motion-loop-exploiter` |
| **Root Directory** | (empty or repo root) |
| **Builder** | Dockerfile |
| **Start Command** | `python scripts/automate_loop.py` |

**Environment variables (required):**

| Variable | Value |
|----------|--------|
| `API_BASE` | `https://motion.productions` |
| `LOOP_EXTRACTION_FOCUS` | `frame` |
| `LOOP_EXPLOIT_RATIO_OVERRIDE` | `1` |

**Optional (for badge):**

| Variable | Value |
|----------|--------|
| `LOOP_WORKFLOW_TYPE` | `exploiter` |

Effect: **Per-frame extraction only** (pure/static registry); 100% **exploit** (known-good prompts). New values get authentic names. Videos show **Exploit** on the site.

---

## 4. Optional — Service 3: Balanced (UI-controlled exploit vs explore)

This is the **middle** workflow: exploit/explore ratio, delay, and duration come from the **Loop controls** on the motion.productions UI (saved to KV, read via `GET /api/loop/config`). So your slider and “Apply settings” directly control this worker.

| Setting | Value |
|--------|--------|
| **Service name** | e.g. `motion-balanced` or `motion-loop` |
| **Root Directory** | (empty or repo root) |
| **Builder** | Dockerfile |
| **Start Command** | `python scripts/automate_loop.py` |

**Environment variables (required):**

| Variable | Value |
|----------|--------|
| `API_BASE` | `https://motion.productions` |
| `LOOP_EXTRACTION_FOCUS` | `window` |

Do **not** set `LOOP_EXPLOIT_RATIO_OVERRIDE` (ratio comes from webapp). Optional: `LOOP_WORKFLOW_TYPE=main` for the **main** badge on the site.

Effect: **Per-window extraction only** (dynamic + narrative + learned_colors, learned_motion, learned_blends). Prompt choice from UI.

---

## 5. Service 4 — Interpretation (user-prompt interpretation only; no create/render)

This worker **does not create or render videos**. It polls the interpretation queue, interprets prompts with `interpret_user_prompt()`, and stores (prompt, instruction) in D1. The main loop’s `GET /api/knowledge/for-creation` returns these as `interpretation_prompts`; `pick_prompt()` sometimes chooses from them so creation has more user-like prompts to work with.

The start command is taken from **Dockerfile CMD** (`python scripts/worker_start.py`). Do **not** override Start Command in the dashboard. Set **WORKER_START_SCRIPT=interpret_loop** so the dispatcher runs `interpret_loop.py`.

| Setting | Value |
|--------|--------|
| **Service name** | e.g. `motion-interpret` or `motion-interpretation` |
| **Root Directory** | (empty or repo root) |
| **Builder** | Dockerfile |
| **Start Command** | (from Dockerfile — do not override) |

**Environment variables:**

| Variable | Value |
|----------|--------|
| `WORKER_START_SCRIPT` | `interpret_loop` |
| `API_BASE` | `https://motion.productions` |

**Optional:**

| Variable | Value |
|----------|--------|
| `INTERPRET_DELAY_SECONDS` | `10` (seconds between poll cycles) |

Effect: Fills the **interpretation registry** (D1 `interpretations` table) from queue items and from backfill (prompts from jobs that don’t yet have an interpretation). Stored values are used by the main pipeline via `interpretation_prompts` in knowledge for creation.

---

## 5.5 Service 5 — Sound (pure sound discovery only; no create/render)

This worker **does not create or render videos**. It runs **sound_loop.py**: each cycle it fetches knowledge (for-creation), picks mood/tempo/presence (from learned_audio or keyword origins), generates procedural audio to a WAV, extracts per-instant sound with `read_audio_segments_only()`, grows the **static_sound** mesh with `grow_static_sound_from_audio_segments()`, and POSTs novel discoveries to `/api/knowledge/discoveries`. This keeps the **pure (static) sound registry** growing so video-creation workflows can use a wider variety of discovered sounds via `GET /api/knowledge/for-creation` → `static_sound`.

The start command is taken from **Dockerfile CMD** (`python scripts/worker_start.py`). Do **not** override Start Command in the dashboard. Set **WORKER_START_SCRIPT=sound_loop** so the dispatcher runs `sound_loop.py`.

| Setting | Value |
|--------|--------|
| **Service name** | e.g. `motion-sound` or `motion-sound-loop` |
| **Root Directory** | (empty or repo root) |
| **Builder** | Dockerfile |
| **Start Command** | (from Dockerfile — do not override) |

**Environment variables:**

| Variable | Value |
|----------|--------|
| `WORKER_START_SCRIPT` | `sound_loop` |
| `API_BASE` | `https://motion.productions` |

**Optional:**

| Variable | Value |
|----------|--------|
| `SOUND_LOOP_DELAY_SECONDS` | `15` (seconds between cycles) |
| `SOUND_LOOP_DURATION_SECONDS` | `2.5` (audio duration per cycle) |
| `HEALTH_PORT` | `8080` (for HTTP health checks from the host; 0 = disabled) |

Effect: Grows the **static_sound** registry (per-instant pure sounds). Main loop and frame-focused workers use `static_sound` from for-creation in builder (pure_sounds, mood/tone refinement) and prompt_gen (mood/audio modifiers).

---

## 6. Quick reference (copy-paste)

**Explorer (frame-focused, 100% explore)**

```env
API_BASE=https://motion.productions
LOOP_EXTRACTION_FOCUS=frame
LOOP_EXPLOIT_RATIO_OVERRIDE=0
LOOP_WORKFLOW_TYPE=explorer
LOOP_WORKER_OFFSET_SECONDS=0
```

**Exploiter (frame-focused, 100% exploit)**

```env
API_BASE=https://motion.productions
LOOP_EXTRACTION_FOCUS=frame
LOOP_EXPLOIT_RATIO_OVERRIDE=1
LOOP_WORKFLOW_TYPE=exploiter
LOOP_WORKER_OFFSET_SECONDS=5
```

**Balanced (window-focused, UI-controlled)**

```env
API_BASE=https://motion.productions
LOOP_EXTRACTION_FOCUS=window
LOOP_WORKER_OFFSET_SECONDS=10
# Do not set LOOP_EXPLOIT_RATIO_OVERRIDE — uses webapp Loop controls
LOOP_WORKFLOW_TYPE=main
```

**Interpretation (no create/render)**

```env
WORKER_START_SCRIPT=interpret_loop
API_BASE=https://motion.productions
INTERPRET_DELAY_SECONDS=10
HEALTH_PORT=8080
```

**Sound (no create/render)**

```env
WORKER_START_SCRIPT=sound_loop
API_BASE=https://motion.productions
SOUND_LOOP_DELAY_SECONDS=15
SOUND_LOOP_DURATION_SECONDS=2.5
HEALTH_PORT=8080
```

---

## 7. Deploy interpret and sound workers

### 7.1 Interpretation worker (step-by-step)

**Prerequisites:** At least one video loop service (Explorer, Exploiter, or Balanced) running; `API_BASE` pointing to your motion.productions instance.

**Fly.io (recommended):** From repo root, `fly apps create motion-loop-interpret` (once), then `fly deploy --config fly.loop-interpret.toml`. Env vars are already in that file.

**Other Docker hosts:**

1. **Create a new worker service** from this repo; name it (e.g. `motion-interpret`).
2. **Root Directory** empty; **Builder:** Dockerfile. Do not override the image **CMD** (use `worker_start.py`).
3. **Environment variables:** `WORKER_START_SCRIPT` = `interpret_loop`; `API_BASE` = `https://motion.productions`; optional: `INTERPRET_DELAY_SECONDS=10`, `HEALTH_PORT=8080`
4. **Deploy** — Worker runs `worker_start.py` → `interpret_loop.py`; polls the interpretation queue every 10 seconds.

**Verify:** Logs show `Interpretation worker started (no create/render)` and `interpreted:` / `backfill:` messages. `GET https://motion.productions/api/knowledge/for-creation` returns `interpretation_prompts` when the worker has stored results.

**One-time backfill (empty registry):** `python scripts/backfill_interpretations.py --api-base https://motion.productions --limit 100`

**Local/Procfile:** `interpret: python scripts/interpret_loop.py` then `py -m procfile start` or `foreman start`.

**Linguistic registry:** Run D1 migrations so `linguistic_registry` table exists (`python scripts/run_d1_migrations.py`). **Backfill gibberish names:** `python scripts/backfill_registry_names.py --dry-run` then `python scripts/backfill_registry_names.py --api-base https://motion.productions`.

### 7.2 Sound worker (step-by-step)

**What it does:** Pure (static) sound discovery only — no video. Each cycle: fetch knowledge → generate procedural audio to WAV → extract per-instant sound → grow `static_sound` mesh → POST novel discoveries. Creation workflows then use a wider variety of sounds via for-creation.

**Fly.io (recommended):** `fly apps create motion-loop-sound` (once), then `fly deploy --config fly.loop-sound.toml`.

**Other Docker hosts:** **Dockerfile CMD** is `python scripts/worker_start.py`. Set **WORKER_START_SCRIPT=sound_loop** (plus `API_BASE`, optional sound delays, `HEALTH_PORT`).

1. **Create a new worker service** — Same project; **Root Directory** empty; **Builder:** Dockerfile.
2. **Environment variables:** `WORKER_START_SCRIPT` = `sound_loop`; `API_BASE` = `https://motion.productions`; optional: `SOUND_LOOP_DELAY_SECONDS=15`, `SOUND_LOOP_DURATION_SECONDS=2.5`, `HEALTH_PORT=8080`
3. **Deploy** — Service runs `worker_start.py` → `sound_loop.py`; each cycle grows static_sound and syncs to API.

**Verify:** Logs show `Sound-only worker started (no create/render)`, `[N] sound discovery: +M` when new sounds are added. API check: `curl -s "https://motion.productions/api/knowledge/for-creation" | jq '.static_sound | length'` (should be > 0 after the worker has run). Integration is automatic: for-creation returns `static_sound`; builder and prompt_gen use it.

**Troubleshooting:** No discoveries → check `API_BASE` and network; per-instant extraction may yield no novel keys. `static_sound` empty in for-creation → ensure Sound service has run a few cycles and POST discoveries succeeds. Videos same audio feel → confirm loop workers use `api_base` and builder/prompt_gen are current.

---

## 8. Verify

1. **Fly / host logs** — `fly logs -a motion-loop-explorer` (etc.); each app should show recent logs (e.g. `[1]`, `[2]`, … for loop; `interpreted:` / `backfill:` for interpretation).
2. **motion.productions** — In **Recent videos** and **Recent activity** you should see new runs with **Explore** and **Exploit** badges (for jobs created after the workflow_type deploy).
3. **API** — `GET https://motion.productions/api/jobs?status=completed&limit=5` — each job should include `workflow_type` when set. `GET /api/knowledge/for-creation` returns `interpretation_prompts` when the interpretation worker has stored results.

### 8.1 Verify extraction focus (frame vs window)

**Important:** The environment variable is **`LOOP_EXTRACTION_FOCUS`** (not `LCXP_EXTRACTION_FOCUS`). The code reads only `LOOP_EXTRACTION_FOCUS`.

#### 1. Environment variable configuration

In your hosting environment, confirm for each service:

| Service    | Variable (exact name)     | Value     |
|-----------|---------------------------|-----------|
| **Explorer**  | `LOOP_EXTRACTION_FOCUS` | `frame`   |
| **Exploiter** | `LOOP_EXTRACTION_FOCUS` | `frame`   |
| **Balanced**  | `LOOP_EXTRACTION_FOCUS` | `window`  |

- **Interpretation** does not use this variable (no video; no extraction).
- If the variable is **unset** or invalid, the loop uses **`all`** (both frame and window extraction).

#### 2. Runtime logs

After redeploying with the correct variables, check each service’s logs:

- **Explorer / Exploiter:** Look for **`Growth [frame]`** when new static discoveries are added (e.g. `Growth [frame]: total=… static=…`).
- **Balanced:** Look for **`Growth [window]`** when new dynamic/narrative discoveries are added.
- If you see **`Growth [all]`**, extraction focus is not set or is wrong for that service (or the variable name is misspelt, e.g. `LCXP_EXTRACTION_FOCUS`).

#### 3. Registry output

Confirm what each workflow is allowed to post:

- **Frame-focused (Explorer, Exploiter):** Post **only static discoveries** — per-frame **colors** (static_colors) and per-frame **sounds** (static_sound). They do **not** post dynamic (motion, gradient, camera, etc.) or narrative (themes, plots, settings, etc.).
- **Window-focused (Balanced):** Post **only dynamic and narrative discoveries** — motion, gradients, cameras, lighting, composition, themes, plots, settings, etc., plus whole-video aggregates (learned_colors, learned_motion, learned_blends). It does **not** post per-frame static colors/sounds from that run (temporal-blend static colors may still be synced if the window path produced them).

Periodically export and review your registry JSON (e.g. `motion-registries-*.json`) to see which discovery types are growing and that frame workers are not adding dynamic/narrative and the window worker is not adding static-only runs.

### 8.2 Logs to expect (video loop)

After each successful upload, you should see (when the latest code is deployed):

- **`  [interpretation] posting...`** then **`  [interpretation] recorded`** — interpretation stored for this prompt. If you see **`[interpretation] failed`**, the POST to `/api/interpretations` failed (e.g. 429/503); it will have been retried up to 5 times.
- **`Growth [frame]`** or **`Growth [window]`** or **`Growth [all]`** when extraction added discoveries.
- **`✓ good`** or **`✓`** when the run completes.

If **`[interpretation]`** lines never appear, confirm the running image includes the latest `automate_loop.py` (redeploy if needed).

### 8.3 429 / 503 / 500 from the API

If logs show **429 Too Many Requests**, **503 Service Unavailable**, or **500 Internal Server Error** (e.g. on `POST /api/knowledge/discoveries`, `GET /api/knowledge/for-creation`, `GET /api/learning/stats`), the Cloudflare Worker or D1 is overloaded or hitting limits.

**Likely causes:**

1. **D1 query limit (50/Worker invocation on Free plan):** Workers Paid raises this to 1,000/request. The codebase uses larger batch limits (200 discoveries, 100 linguistic, 50 interpretations) optimized for Workers Paid.
2. **D1 overload:** D1 is single-threaded per DB. With many workers + webapp, concurrent requests queue; when overloaded, D1 returns errors.
3. **Read timeouts:** `GET /api/knowledge/for-creation` runs 15+ sequential D1 queries. Client timeout is 45s.

**What to do:**

- **Cloudflare Workers Paid ($5/mo):** Increases D1 to 1,000 queries/request. Recommended for production. See §8.4.
- **Reduce load:** Run fewer worker services or increase loop delay if limits are tight.
- **Cloudflare logs:** Dashboard → Workers → Logs to see actual D1 errors.

### 8.4 Optimized setup (extra workers + Workers Paid)

For the most efficient workflow and fastest registry completion:

| Component | Cost | What to do |
|-----------|------|------------|
| **Cloudflare Workers Paid** | ~$5/mo + usage | Upgrade at [dash.cloudflare.com](https://dash.cloudflare.com) → Workers & Pages → Workers Paid. Unlocks 1,000 D1 queries/request (vs 50 on Free). Essential for stability. |
| **More worker capacity** | Varies by host | Scale your container host so you can run 6 workers: Explorer, Exploiter, Balanced, Balanced-2, Interpretation, Sound. A second Balanced doubles dynamic/narrative throughput. |
| **Buffer** | ~$5 | Covers D1/KV overages, usage spikes. |

**Add 6th worker (Balanced-2):**

1. Create a new worker service from the same repo and Dockerfile.
2. **Env vars:** `API_BASE`, `LOOP_EXTRACTION_FOCUS=window`, `LOOP_WORKFLOW_TYPE=main` (same as Balanced). Do **not** set `LOOP_EXPLOIT_RATIO_OVERRIDE`.
3. Both Balanced workers read exploit ratio from the UI and run per-window extraction. 2× Balanced = 2× dynamic/narrative discovery rate.

**Alternative:** Add 2nd Explorer for 2× static (color/sound) throughput instead of Balanced-2. Choose based on which registry (static vs dynamic) you want to grow faster.

**Batch limits (Workers Paid):** Discoveries 50/request (reduced for D1 CPU stability), linguistic 100/request, interpretations 50/request. Fewer HTTP round-trips = more efficient. KV TTLs: learning/stats 120s, for-creation 180s, loop/progress 120s, backfill-prompts 120s.

### 8.5 D1 stability & cost-saving (avoid wasted worker compute)

D1 is single-threaded and has a CPU time limit per operation. With 6 workers, too many concurrent requests cause `D1_ERROR: D1 DB exceeded its CPU time limit`. Failed requests waste container CPU (retries) and lost discoveries (video work not persisted).

**Enforced minimums (in code):**

- **Pace (delay between runs):** Min 3 seconds. Webapp and API enforce this. With 6 workers, lower delays = more D1 overload.
- **Batch size:** 100 discoveries/request (reduced for D1 CPU stability).

**Workflow improvements (continuous progress):**

- **LOOP_WORKER_OFFSET_SECONDS:** Per-worker startup stagger (e.g. Explorer=0, Exploiter=5, Balanced=10). Prevents all workers from hitting D1 at once. Set per service in the host’s environment.
- **D1-aware retry:** On `D1_ERROR` or CPU time limit, the API client uses longer backoff (10s, 15s, 20s…) before retry instead of 2s, giving D1 time to reset.
- **Extended jitter:** 0–8s jitter on D1-heavy endpoints (knowledge/for-creation, discoveries, learning/stats) spreads concurrent requests.
- **Discovery recording retry:** If discovery run recording fails with 5xx, the loop retries once after 12s so progress is still recorded.

**D1 Read Replication (recommended):** Enable in Cloudflare Dashboard → **D1** → your database → **Settings** → **Read Replication** → Enable. The Worker uses the Sessions API (`withSession("first-unconstrained")`) to spread reads across replicas; writes still go to the primary. This reduces CPU load on the primary and helps avoid the CPU time limit.

**If errors persist:**

1. **Enable Read Replication** (above) if not already on.
2. **Set LOOP_WORKER_OFFSET_SECONDS** per service (Explorer=0, Exploiter=5, Balanced=10, Balanced-2=15) to stagger startup.
3. **Increase Pace:** Set 5–10s in the webapp loop controls. Fewer requests/min = more stable.
4. **Run 4 workers:** Disable Balanced-2 and Sound temporarily. Explorer, Exploiter, Balanced, Interpretation still give strong coverage. Re-enable when D1 errors drop.
5. **Check Cloudflare logs:** Workers → Logs to see which endpoints fail most (for-creation, discoveries, loop/progress).

---

## 9. Reference

- Env source of truth: `config/workflows.yaml`
- Loop behavior: `docs/INTENDED_LOOP.md`, `docs/AUTOMATION.md`
- Deploy (Cloudflare + DB): `docs/DEPLOYMENT.md (Cloudflare Worker section)`

---

## 10. Post-deploy operational checklist

Use after code changes to ensure deploy, workers, and data quality are correct.

### 10.1 Deploy the Cloudflare Worker

The Worker merges **learned_lighting**, **learned_composition**, **learned_graphics**, **learned_temporal**, **learned_technical** into GET /api/registries. (1) Confirm GitHub Actions deploy completed. (2) Optional manual: `cd cloudflare && npm run deploy`.

### 10.2 Set LOOP_EXTRACTION_FOCUS=window on Balanced worker

Balanced worker → set variables: **`LOOP_EXTRACTION_FOCUS`** = **`window`**, **`API_BASE`** = `https://motion.productions`. Redeploy. Verify logs show **Growth [window]**.

### 10.3 Run backfill_registry_names.py (fix numeric names)

```bash
python scripts/backfill_registry_names.py --api-base https://motion.productions --timeout 300
```

Use `--table learned_blends` for one large table. Verify: re-export registries and confirm no numeric-suffix names.

### 10.4 Run color_sweep.py when API is stable

```bash
python scripts/color_sweep.py --api-base https://motion.productions --steps 5 --limit 150
```

Verify: GET /api/registries/coverage and check **static_colors_coverage_pct**.

### 10.5 Confirm sound_loop deployed and POSTing

Sound worker (5th service) with **`WORKER_START_SCRIPT`** = **`sound_loop`**, **`API_BASE`** set. Verify logs show `Sound-only worker started` and `[N] sound discovery: +M`. API check: `curl -s "https://motion.productions/api/knowledge/for-creation" | jq '.static_sound | length'` (should be > 0).

### 10.6 Run registry export analysis

```bash
python scripts/registry_export_analysis.py
```

Or with specific files: `python scripts/registry_export_analysis.py "json registry exports/motion-registries-2026-02-21.json"`. Review tone leakage, depth coverage, loop_progress.

### Quick reference

| Task | Action |
|------|--------|
| Deploy Worker | GitHub Actions → Deploy to Cloudflare |
| Balanced = window | Set `LOOP_EXTRACTION_FOCUS=window`, redeploy |
| Backfill names | `python scripts/backfill_registry_names.py --api-base https://motion.productions --timeout 300` |
| Color sweep | `python scripts/color_sweep.py --api-base https://motion.productions` |
| Sound worker | 5th service, `WORKER_START_SCRIPT=sound_loop` |
| Registry analysis | `python scripts/registry_export_analysis.py` |
