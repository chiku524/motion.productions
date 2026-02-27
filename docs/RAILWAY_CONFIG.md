# Railway config checklist — workflows on motion.productions

Use this to confirm **Explorer**, **Exploiter**, **Balanced**, **Interpretation**, and **Sound** are running. The start command is **unified in railway.toml** as `python scripts/railway_start.py`; which script actually runs is controlled per service by the env var **RAILWAY_START_SCRIPT** (see below). The three video workflows differ by **prompt choice** (explore / exploit / UI) and **extraction focus** (frame vs window): **2 workers** do per-frame (pure/static) extraction only; **1 worker** does per-window (blended) extraction only. Set **LOOP_EXTRACTION_FOCUS** on each service as below.

---

## 1. Project layout

- **One Railway project** with **three or four services** (Explorer, Exploiter, Balanced, optional Interpretation).
- **Same repo** for all: root = repo root (not `cloudflare/`).
- **Same build**: Dockerfile.
- **Start command**:
  - Explorer / Exploiter / Balanced: `python scripts/automate_loop.py`
  - Interpretation (no create/render): `python scripts/interpret_loop.py`

Only **environment variables** and **start command** differ per service.

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

The start command is taken from **railway.toml** (`python scripts/railway_start.py`). Do **not** override Start Command in the dashboard. Set **RAILWAY_START_SCRIPT=interpret_loop** so the dispatcher runs `interpret_loop.py`.

| Setting | Value |
|--------|--------|
| **Service name** | e.g. `motion-interpret` or `motion-interpretation` |
| **Root Directory** | (empty or repo root) |
| **Builder** | Dockerfile |
| **Start Command** | (from railway.toml — do not override) |

**Environment variables:**

| Variable | Value |
|----------|--------|
| `RAILWAY_START_SCRIPT` | `interpret_loop` |
| `API_BASE` | `https://motion.productions` |

**Optional:**

| Variable | Value |
|----------|--------|
| `INTERPRET_DELAY_SECONDS` | `10` (seconds between poll cycles) |

Effect: Fills the **interpretation registry** (D1 `interpretations` table) from queue items and from backfill (prompts from jobs that don’t yet have an interpretation). Stored values are used by the main pipeline via `interpretation_prompts` in knowledge for creation.

---

## 5.5 Service 5 — Sound (pure sound discovery only; no create/render)

This worker **does not create or render videos**. It runs **sound_loop.py**: each cycle it fetches knowledge (for-creation), picks mood/tempo/presence (from learned_audio or keyword origins), generates procedural audio to a WAV, extracts per-instant sound with `read_audio_segments_only()`, grows the **static_sound** mesh with `grow_static_sound_from_audio_segments()`, and POSTs novel discoveries to `/api/knowledge/discoveries`. This keeps the **pure (static) sound registry** growing so video-creation workflows can use a wider variety of discovered sounds via `GET /api/knowledge/for-creation` → `static_sound`.

The start command is taken from **railway.toml** (`python scripts/railway_start.py`). Do **not** override Start Command in the dashboard. Set **RAILWAY_START_SCRIPT=sound_loop** so the dispatcher runs `sound_loop.py`.

| Setting | Value |
|--------|--------|
| **Service name** | e.g. `motion-sound` or `motion-sound-loop` |
| **Root Directory** | (empty or repo root) |
| **Builder** | Dockerfile |
| **Start Command** | (from railway.toml — do not override) |

**Environment variables:**

| Variable | Value |
|----------|--------|
| `RAILWAY_START_SCRIPT` | `sound_loop` |
| `API_BASE` | `https://motion.productions` |

**Optional:**

| Variable | Value |
|----------|--------|
| `SOUND_LOOP_DELAY_SECONDS` | `15` (seconds between cycles) |
| `SOUND_LOOP_DURATION_SECONDS` | `2.5` (audio duration per cycle) |
| `HEALTH_PORT` | `8080` (for Railway health checks; 0 = disabled) |

Effect: Grows the **static_sound** registry (per-instant pure sounds). Main loop and frame-focused workers use `static_sound` from for-creation in builder (pure_sounds, mood/tone refinement) and prompt_gen (mood/audio modifiers).

---

## 6. Quick reference (copy-paste)

**Explorer (frame-focused, 100% explore)**

```env
API_BASE=https://motion.productions
LOOP_EXTRACTION_FOCUS=frame
LOOP_EXPLOIT_RATIO_OVERRIDE=0
LOOP_WORKFLOW_TYPE=explorer
```

**Exploiter (frame-focused, 100% exploit)**

```env
API_BASE=https://motion.productions
LOOP_EXTRACTION_FOCUS=frame
LOOP_EXPLOIT_RATIO_OVERRIDE=1
LOOP_WORKFLOW_TYPE=exploiter
```

**Balanced (window-focused, UI-controlled)**

```env
API_BASE=https://motion.productions
LOOP_EXTRACTION_FOCUS=window
# Do not set LOOP_EXPLOIT_RATIO_OVERRIDE — uses webapp Loop controls
LOOP_WORKFLOW_TYPE=main
```

**Interpretation (no create/render)**

```env
RAILWAY_START_SCRIPT=interpret_loop
API_BASE=https://motion.productions
INTERPRET_DELAY_SECONDS=10
HEALTH_PORT=8080
```

**Sound (no create/render)**

```env
RAILWAY_START_SCRIPT=sound_loop
API_BASE=https://motion.productions
SOUND_LOOP_DELAY_SECONDS=15
SOUND_LOOP_DURATION_SECONDS=2.5
HEALTH_PORT=8080
```

---

## 7. Deploy interpret and sound workers

### 7.1 Interpretation worker (step-by-step)

**Prerequisites:** A Railway project with at least one existing service (Explorer, Exploiter, or Balanced); `API_BASE` pointing to your motion.productions instance.

1. **Create a new service** — Railway Dashboard → your project → **+ New** → **Empty Service**; name it (e.g. `motion-interpret`).
2. **Link the same repo** — Same repository as main loop; **Root Directory** empty; **Builder:** Dockerfile. Start command comes from **railway.toml** (do not override).
3. **Environment variables:** `RAILWAY_START_SCRIPT` = `interpret_loop`; `API_BASE` = `https://motion.productions`; optional: `INTERPRET_DELAY_SECONDS=10`, `HEALTH_PORT=8080`
4. **Deploy** — Worker runs `railway_start.py` → `interpret_loop.py`; polls the interpretation queue every 10 seconds.

**Verify:** Logs show `Interpretation worker started (no create/render)` and `interpreted:` / `backfill:` messages. `GET https://motion.productions/api/knowledge/for-creation` returns `interpretation_prompts` when the worker has stored results.

**One-time backfill (empty registry):** `python scripts/backfill_interpretations.py --api-base https://motion.productions --limit 100`

**Local/Procfile:** `interpret: python scripts/interpret_loop.py` then `py -m procfile start` or `foreman start`.

**Linguistic registry:** Run D1 migrations so `linguistic_registry` table exists (`python scripts/run_d1_migrations.py`). **Backfill gibberish names:** `python scripts/backfill_registry_names.py --dry-run` then `python scripts/backfill_registry_names.py --api-base https://motion.productions`.

### 7.2 Sound worker (step-by-step)

**What it does:** Pure (static) sound discovery only — no video. Each cycle: fetch knowledge → generate procedural audio to WAV → extract per-instant sound → grow `static_sound` mesh → POST novel discoveries. Creation workflows then use a wider variety of sounds via for-creation.

**Start command:** Defined in **railway.toml** as `python scripts/railway_start.py`. Do not set a custom Start Command in the service; set **RAILWAY_START_SCRIPT=sound_loop** so the dispatcher runs `sound_loop.py`.

1. **Create a new service** — Same Railway project; **Root Directory** empty; **Builder:** Dockerfile.
2. **Environment variables:** `RAILWAY_START_SCRIPT` = `sound_loop`; `API_BASE` = `https://motion.productions`; optional: `SOUND_LOOP_DELAY_SECONDS=15`, `SOUND_LOOP_DURATION_SECONDS=2.5`, `HEALTH_PORT=8080`
3. **Deploy** — Service runs `railway_start.py` → `sound_loop.py`; each cycle grows static_sound and syncs to API.

**Verify:** Logs show `Sound-only worker started (no create/render)`, `[N] sound discovery: +M` when new sounds are added. API check: `curl -s "https://motion.productions/api/knowledge/for-creation" | jq '.static_sound | length'` (should be > 0 after the worker has run). Integration is automatic: for-creation returns `static_sound`; builder and prompt_gen use it.

**Troubleshooting:** No discoveries → check `API_BASE` and network; per-instant extraction may yield no novel keys. `static_sound` empty in for-creation → ensure Sound service has run a few cycles and POST discoveries succeeds. Videos same audio feel → confirm loop workers use `api_base` and builder/prompt_gen are current.

---

## 8. Verify

1. **Railway dashboard** — Each service shows **Active** and recent logs (e.g. `[1]`, `[2]`, … for loop; `interpreted:` / `backfill:` for interpretation).
2. **motion.productions** — In **Recent videos** and **Recent activity** you should see new runs with **Explore** and **Exploit** badges (for jobs created after the workflow_type deploy).
3. **API** — `GET https://motion.productions/api/jobs?status=completed&limit=5` — each job should include `workflow_type` when set. `GET /api/knowledge/for-creation` returns `interpretation_prompts` when the interpretation worker has stored results.

### 8.1 Verify extraction focus (frame vs window)

**Important:** The environment variable is **`LOOP_EXTRACTION_FOCUS`** (not `LCXP_EXTRACTION_FOCUS`). The code reads only `LOOP_EXTRACTION_FOCUS`.

#### 1. Environment variable configuration

In your hosting environment (e.g. Railway), confirm for each service:

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
2. **D1 overload:** D1 is single-threaded per DB. With 6 Railway workers + webapp, concurrent requests queue; when overloaded, D1 returns errors.
3. **Read timeouts:** `GET /api/knowledge/for-creation` runs 15+ sequential D1 queries. Client timeout is 45s.

**What to do:**

- **Cloudflare Workers Paid ($5/mo):** Increases D1 to 1,000 queries/request. Recommended for production. See §8.4.
- **Reduce load:** Run fewer Railway services or increase loop delay if on Free plan.
- **Cloudflare logs:** Dashboard → Workers → Logs to see actual D1 errors.

### 8.4 Optimized setup (Railway Pro + Workers Paid)

For the most efficient workflow and fastest registry completion:

| Component | Cost | What to do |
|-----------|------|------------|
| **Cloudflare Workers Paid** | ~$5/mo + usage | Upgrade at [dash.cloudflare.com](https://dash.cloudflare.com) → Workers & Pages → Workers Paid. Unlocks 1,000 D1 queries/request (vs 50 on Free). Essential for stability. |
| **Railway Pro** | $20/mo base | [railway.app](https://railway.app) → Pro plan. Higher limits, priority support. Run 6 workers: Explorer, Exploiter, Balanced, Balanced-2, Interpretation, Sound. Balanced-2 doubles dynamic/narrative throughput. |
| **Buffer** | ~$5 | Covers D1/KV overages, usage spikes. |

**Add 6th worker (Balanced-2):**

1. Create a new Railway service; same repo, Dockerfile.
2. **Env vars:** `API_BASE`, `LOOP_EXTRACTION_FOCUS=window`, `LOOP_WORKFLOW_TYPE=main` (same as Balanced). Do **not** set `LOOP_EXPLOIT_RATIO_OVERRIDE`.
3. Both Balanced workers read exploit ratio from the UI and run per-window extraction. 2× Balanced = 2× dynamic/narrative discovery rate.

**Alternative:** Add 2nd Explorer for 2× static (color/sound) throughput instead of Balanced-2. Choose based on which registry (static vs dynamic) you want to grow faster.

**Batch limits (Workers Paid):** Discoveries 150/request, linguistic 100/request, interpretations 50/request. Fewer HTTP round-trips = more efficient.

### 8.5 D1 stability & cost-saving (avoid wasted Railway compute)

D1 is single-threaded and has a CPU time limit per operation. With 6 workers, too many concurrent requests cause `D1_ERROR: D1 DB exceeded its CPU time limit`. Failed requests waste Railway compute (retries) and lost discoveries (video work not persisted).

**Enforced minimums (in code):**

- **Pace (delay between runs):** Min 3 seconds. Webapp and API enforce this. With 6 workers, lower delays = more D1 overload.
- **Batch size:** 150 discoveries/request (reduced from 200 for stability).

**If errors persist:**

1. **Increase Pace:** Set 5–10s in the webapp loop controls. Fewer requests/min = more stable.
2. **Run 4 workers:** Disable Balanced-2 and Sound temporarily. Explorer, Exploiter, Balanced, Interpretation still give strong coverage. Re-enable when D1 errors drop.
3. **Check Cloudflare logs:** Workers → Logs to see which endpoints fail most (for-creation, discoveries, loop/progress).

---

## 9. Reference

- Env source of truth: `config/workflows.yaml`
- Loop behavior: `docs/INTENDED_LOOP.md`, `docs/AUTOMATION.md`
- Deploy (Cloudflare + DB): `docs/DEPLOY_CLOUDFLARE.md`
