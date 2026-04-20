# Automation and Deployment

Run automation to continuously generate prompts, create videos, and build a knowledge base. No external models — the procedural engine and keyword data only.

---

## Scripts

| Script                    | Purpose                                                                 |
|---------------------------|-------------------------------------------------------------------------|
| `scripts/automate_loop.py`| Self-feeding loop: 70% exploit, 30% explore, baseline on restart. Runs on **Fly.io** via `fly.loop-*.toml`. |
| `scripts/automate.py`     | Interval-based automation: runs with sleep between jobs. For local/scheduled runs. |
| `scripts/generate_bridge.py` | Process pending API jobs: generate → upload → learn.                 |
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

## Deploy loop workers (Fly.io)

### Prerequisites

- API deployed at motion.productions
- [Fly CLI](https://fly.io/docs/hands-on/install-flyctl/) (`fly auth login`)

### Fly.io

The repo ships **`fly.loop-explorer.toml`**, **`fly.loop-exploiter.toml`**, **`fly.loop-balanced.toml`**, and optional **`fly.loop-interpret.toml`** / **`fly.loop-sound.toml`** at the **repository root**. Each file defines one Fly app, the same **`Dockerfile`**, and the env vars for that role.

```bash
cd motion.productions   # repo root
fly apps create motion-loop-explorer    # once per app name
fly deploy --config fly.loop-explorer.toml
```

Repeat with the other config files as needed. Full matrix and operational checklist: **[docs/DEPLOYMENT.md](DEPLOYMENT.md)** (Fly.io section).

Default **`CMD`** is `python scripts/worker_start.py` (**`WORKER_START_SCRIPT`** selects `automate_loop` vs `interpret_loop` vs `sound_loop`).

**Video AI** (FFmpeg render for the Worker): deploy from **`video-ai/`** with **`video-ai/fly.toml`** — see **`video-ai/README.md`**.

### Local / Procfile

`Procfile` lists example processes; use `foreman` or run scripts directly for development.

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

### Setup (multiple workers) on Fly

1. **Balanced** — `fly apps create motion-loop-balanced` then `fly deploy --config fly.loop-balanced.toml`.
2. **Explorer** — `fly apps create motion-loop-explorer` then `fly deploy --config fly.loop-explorer.toml`.
3. **Exploiter** — `fly apps create motion-loop-exploiter` then `fly deploy --config fly.loop-exploiter.toml`.

Optional: interpretation and sound use **`fly.loop-interpret.toml`** and **`fly.loop-sound.toml`**. Env vars are already set in each file; change **`primary_region`** if you do not want `iad`.

**Verify:** `fly logs -a motion-loop-balanced` (etc.) show `[1]`, `[2]`, …; the motion.productions loop UI reflects combined activity.

---

## Knowledge Base

- **Local state:** `data/automation_state.json` (for automate.py)
- **Cloud sync:** Fetches prompts from `GET /api/knowledge/prompts` to avoid duplicates
- **Learning:** Each run logged to D1. Run `scripts/learn_from_api.py` periodically for suggestions

---

## Verify

- Worker logs: `[1]`, `[2]`, … runs
- Visit motion.productions; new videos appear as jobs complete
