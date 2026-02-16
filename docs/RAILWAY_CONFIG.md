# Railway config checklist — workflows on motion.productions

Use this to confirm **Explorer**, **Exploiter**, **Balanced**, and **Interpretation** are running. The three video workflows differ by **prompt choice** (explore / exploit / UI) and **extraction focus** (frame vs window): **2 workers** do per-frame (pure/static) extraction only; **1 worker** does per-window (blended) extraction only. Set **LOOP_EXTRACTION_FOCUS** on each service as below.

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

| Setting | Value |
|--------|--------|
| **Service name** | e.g. `motion-interpret` or `motion-interpretation` |
| **Root Directory** | (empty or repo root) |
| **Builder** | Dockerfile |
| **Start Command** | `python scripts/interpret_loop.py` |

**Environment variables:**

| Variable | Value |
|----------|--------|
| `API_BASE` | `https://motion.productions` |

**Optional:**

| Variable | Value |
|----------|--------|
| `INTERPRET_DELAY_SECONDS` | `10` (seconds between poll cycles) |

Effect: Fills the **interpretation registry** (D1 `interpretations` table) from queue items and from backfill (prompts from jobs that don’t yet have an interpretation). Stored values are used by the main pipeline via `interpretation_prompts` in knowledge for creation.

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
API_BASE=https://motion.productions
INTERPRET_DELAY_SECONDS=10
HEALTH_PORT=8080
```

---

## 7. Deploy interpret worker

See **`docs/DEPLOY_INTERPRET_WORKER.md`** for full step-by-step instructions.

Summary: Create a new Railway service in the same project, set **Start Command** to `python scripts/interpret_loop.py`, add `API_BASE`, and deploy. The `Procfile` includes `interpret:` for local/Procfile runs.

---

## 8. Verify

1. **Railway dashboard** — Each service shows **Active** and recent logs (e.g. `[1]`, `[2]`, … for loop; `interpreted:` / `backfill:` for interpretation).
2. **motion.productions** — In **Recent videos** and **Recent activity** you should see new runs with **Explore** and **Exploit** badges (for jobs created after the workflow_type deploy).
3. **API** — `GET https://motion.productions/api/jobs?status=completed&limit=5` — each job should include `workflow_type` when set. `GET /api/knowledge/for-creation` returns `interpretation_prompts` when the interpretation worker has stored results.

---

## 9. Reference

- Env source of truth: `config/workflows.yaml`
- Loop behavior: `docs/INTENDED_LOOP.md`, `docs/AUTOMATION.md`
- Deploy (Cloudflare + DB): `docs/DEPLOY_CLOUDFLARE.md`
