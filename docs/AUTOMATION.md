# Automation and Deployment

Run automation to continuously generate prompts, create videos, and build a knowledge base. No external models — the procedural engine and keyword data only.

---

## Scripts

| Script                    | Purpose                                                                 |
|---------------------------|-------------------------------------------------------------------------|
| `scripts/automate_loop.py`| Self-feeding loop: 70% exploit, 30% explore, baseline on restart. For Railway/Render. |
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

## Deploy Loop to Railway / Render

### Prerequisites

- API deployed at motion.productions
- GitHub repo connected

### Railway

`railway.toml`, `Dockerfile`, and `Procfile` are in the repo. **Root Directory must be repo root** (not `cloudflare/`).

1. [railway.app](https://railway.app) → New Project → Deploy from GitHub
2. Add Worker service: Root Directory empty, Builder: Dockerfile
3. Start Command: `python scripts/automate_loop.py`
4. Env vars (optional): `API_BASE=https://motion.productions`

**Cost:** ~$5/mo (usage-based).

### Render

1. New → Background Worker → Connect GitHub
2. Build: `pip install -r requirements.txt`
3. Start: `python scripts/automate_loop.py`
4. Or use `render.yaml` (Blueprint)

**Cost:** Free tier available; paid ~$7/mo for always-on.

### Environment variables

| Variable   | Default                    | Purpose                    |
|------------|----------------------------|----------------------------|
| `API_BASE` | `https://motion.productions` | API root for jobs, upload |
| `LOOP_DELAY_SECONDS` | (from API) | Delay between runs when not overridden by API |
| `LOOP_EXPLOIT_RATIO_OVERRIDE` | (none) | If set (0–1), overrides webapp exploit ratio for this worker |

---

## Multi-Workflow (Parallel Workers)

You can run **multiple Railway services** to speed up learning without compromising quality. Each worker shares the same KV/D1 (state, knowledge) and contributes discoveries.

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

### Setup (Railway) — step-by-step

1. **Existing service** — Your current worker (e.g. `motion-loop`). No changes if you want it as "balanced" (uses webapp).
2. **Add Explorer** — New service from same repo: Root Directory: (repo root); Build: Dockerfile; Start: `python scripts/automate_loop.py`; Variables: `LOOP_EXPLOIT_RATIO_OVERRIDE=0`, `API_BASE=https://motion.productions`.
3. **Add Exploiter** — Another new service: same as above; Variables: `LOOP_EXPLOIT_RATIO_OVERRIDE=1`, `API_BASE=https://motion.productions`.

**Railway UI:** Dashboard → Your Project → **New** → **Empty Service** → Connect repo → Settings: Root Directory empty, Builder: Dockerfile, Start Command: `python scripts/automate_loop.py` → Variables: `API_BASE`, `LOOP_EXPLOIT_RATIO_OVERRIDE` (0 for Explorer, 1 for Exploiter) → Deploy.

**Verify:** All services show logs like `[1]`, `[2]`, …; webapp loop status reflects combined activity.

### Setup (Render)

Use `render.yaml` — it defines three workers (explorer, balanced, exploiter). Connect the repo as a Blueprint to deploy all at once.

---

## Knowledge Base

- **Local state:** `data/automation_state.json` (for automate.py)
- **Cloud sync:** Fetches prompts from `GET /api/knowledge/prompts` to avoid duplicates
- **Learning:** Each run logged to D1. Run `scripts/learn_from_api.py` periodically for suggestions

---

## Verify

- Worker logs: `[1]`, `[2]`, … runs
- Visit motion.productions; new videos appear as jobs complete
