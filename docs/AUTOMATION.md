# Automation and Deployment

Run automation to continuously generate prompts, create videos, and grow registries (colors, sounds, narratives, interpretations) from primitives toward exhaustive, named coverage. No external models — the procedural engine and registry data only. Destination: a photoreal engine that uses those registries for prompt-controlled values.

---

## Scripts

| Script                    | Purpose                                                                 |
|---------------------------|-------------------------------------------------------------------------|
| `scripts/worker_start.py` | Docker dispatcher (`WORKER_START_SCRIPT`). |
| `scripts/automate_loop.py`| Self-feeding loop: exploit/explore, `grow_all_from_video`. Runs in Docker via `docker-compose.local.yml`. |
| `scripts/automate.py`     | Interval-based automation: runs with sleep between jobs. For local/scheduled runs. |
| `scripts/generate_bridge.py` | Process pending API jobs: generate → upload → learn. Also the `webjobs` Compose service. |
| `scripts/interpret_loop.py` | Interpretation / linguistics worker (no render). |
| `scripts/sound_loop.py`   | Pure sound discovery worker (no render). |
| `scripts/procedural_render_server.py` | HTTP `POST /render` for `engine=procedural`. |
| `scripts/learn_from_api.py`  | Fetch events/feedback from API, produce suggestions.                |
| `scripts/learn_report.py`   | Learning report from local JSONL.                                   |

---

## Self-Feeding Loop (automate_loop.py)

Runs 24/7 in the cloud. Each output triggers the next run. 70% exploit (good outcomes), 30% explore (new combos). State resets on restart.

### Local usage

```bash
python scripts/automate_loop.py
python scripts/automate_loop.py --api-base https://motion.productions
```

### Behavior

- **Exploit (70%):** Picks from prompts that produced "good" outcomes (consistent brightness, motion in range).
- **Explore (30%):** New keyword combinations from our data.
- **Duration scaling:** 6s → 10s → 15s → 20s+ as run count grows.
- **Restart = baseline:** State resets; progress is visible as the session improves from scratch.

---

## Interval-Based Automation (automate.py)

Runs with an interval between jobs. Good for local or scheduled runs.

```bash
python scripts/automate.py
python scripts/automate.py --once
python scripts/automate.py --scale-duration
python scripts/automate.py --duration 5 --interval 120
```

### Duration scaling

| Runs  | Duration        |
|-------|-----------------|
| 0–19  | Base (e.g. 6s)  |
| 20–49 | Base + 2s (up to 10s) |
| 50–99 | Base + 4s (up to 15s) |
| 100+  | Base + 6s (up to 20s) |

---

## Deploy loop workers (Docker)

Workers run as Docker containers via Docker Compose. Setup, profiles, and health checks: **[LOCAL_COMPUTE.md](LOCAL_COMPUTE.md)**.

### Prerequisites

- API deployed at motion.productions
- Docker Desktop (or Docker Engine + Compose v2)

### Docker Compose

The repo ships **`docker-compose.local.yml`** at the **repository root**. Each service defines one worker role, the same **`Dockerfile`**, and the env vars for that role.

```bash
cd motion.productions   # repo root
docker compose -f docker-compose.local.yml --profile free up -d --build
```

Full matrix and operational checklist: **[docs/DEPLOYMENT.md](DEPLOYMENT.md)** (Docker workers section).

Default **`CMD`** is `python scripts/worker_start.py` (**`WORKER_START_SCRIPT`** selects `automate_loop` vs `interpret_loop` vs `sound_loop` vs `generate_bridge` vs `procedural_render`).

**Video AI** (FFmpeg render for the Worker): the `video-ai-render` Compose service (`--profile video-ai`) - see **`video-ai/README.md`**.

### Local development

Run the scripts directly (for example `python scripts/automate_loop.py`) or use `docker-compose.local.yml`.

### Environment variables

| Variable   | Default                    | Purpose                    |
|------------|----------------------------|----------------------------|
| `API_BASE` | `https://motion.productions` | API root for jobs, upload |
| `LOOP_DELAY_SECONDS` | (from API) | Delay between runs when not overridden by API |
| `LOOP_EXPLOIT_RATIO_OVERRIDE` | (none) | If set (0–1), overrides webapp exploit ratio for this worker |

---

## Multi-Workflow (Parallel Workers)

You can run **multiple worker services** to speed up learning without compromising quality. Each worker shares the same KV/D1 (state, knowledge) and contributes discoveries.

### Option 1: Identical workers (2×–3× throughput)

Deploy 2–3 copies of the same loop service. They may occasionally pick the same prompt; duplicates still add to the knowledge base. No config changes.

### Option 2: Differentiated workflows

Use env overrides to run workers with different strategies:

| Worker | `LOOP_EXPLOIT_RATIO_OVERRIDE` | Purpose |
|--------|------------------------------|---------|
| Explorer | `0` | 100% explore — broad discovery |
| Balanced | (none, uses webapp) | 70% exploit / 30% explore |
| Exploiter | `1` | 100% exploit — refine known-good prompts |

Each worker writes to the same D1; the knowledge base grows from all strategies. Quality is preserved because discoveries and good prompts are shared.

### Setup (multiple workers)

Use the Compose services, which already set the per-role env vars:

1. **Balanced** - `docker compose -f docker-compose.local.yml --profile free up -d --build balanced`.
2. **Explorer** - `docker compose -f docker-compose.local.yml --profile free up -d --build explorer`.
3. **Exploiter** - `docker compose -f docker-compose.local.yml --profile loops-full up -d --build exploiter`.

Optional: interpretation, sound, webjobs, and procedural-render are the `interpret`, `sound`, `webjobs`, and `procedural-render` services. Env vars are already set in `docker-compose.local.yml`.

**Verify:** `docker compose -f docker-compose.local.yml logs -f balanced` (etc.) show `[1]`, `[2]`, ...; the motion.productions loop UI reflects combined activity.

---

## Knowledge Base

- **Local state:** `automate.py` may write session state under a local path when configured; cloud loop state lives in **KV** (`loop_state` / `loop_config`).
- **Cloud sync:** Fetches prompts from `GET /api/knowledge/prompts` to avoid duplicates; discoveries sync to D1.
- **Learning:** Each run logged to D1. Run `scripts/learn_from_api.py` periodically for suggestions.

---

## Verify

- Worker logs: `[1]`, `[2]`, … runs
- Visit motion.productions; new videos appear as jobs complete
