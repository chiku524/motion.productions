# Railway config checklist — workflows on motion.productions

Use this to confirm **Explorer**, **Exploiter**, and optionally **Balanced** and **Interpretation** are running. Explorer/Exploiter/Balanced output appears in **Recent videos** and **Recent activity** on [motion.productions](https://motion.productions). The **Interpretation** worker does not create videos; it only interprets user prompts and stores them in D1 so the main pipeline has more prompts to work with.

---

## 1. Project layout

- **One Railway project** with **two to four services** (Explorer, Exploiter, optional Balanced, optional Interpretation).
- **Same repo** for all: root = repo root (not `cloudflare/`).
- **Same build**: Dockerfile.
- **Start command**:
  - Explorer / Exploiter / Balanced: `python scripts/automate_loop.py`
  - Interpretation (no create/render): `python scripts/interpret_loop.py`

Only **environment variables** and **start command** differ per service.

---

## 2. Service 1 — Explorer (discovery / growth focus)

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
| `LOOP_EXPLOIT_RATIO_OVERRIDE` | `0` |

**Optional (for explicit badge):**

| Variable | Value |
|----------|--------|
| `LOOP_WORKFLOW_TYPE` | `explorer` |

Effect: 100% **explore** — always picks new procedural prompts; maximizes discovery and registry growth. Videos show **Explore** on the site.

---

## 3. Service 2 — Exploiter (interpretation / refinement focus)

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
| `LOOP_EXPLOIT_RATIO_OVERRIDE` | `1` |

**Optional (for explicit badge):**

| Variable | Value |
|----------|--------|
| `LOOP_WORKFLOW_TYPE` | `exploiter` |

Effect: 100% **exploit** — reuses known-good prompts; refines interpretation and creation. Videos show **Exploit** on the site.

---

## 4. Optional — Service 3: Balanced (UI-controlled exploit vs explore)

This is the **middle** workflow: exploit/explore ratio, delay, and duration come from the **Loop controls** on the motion.productions UI (saved to KV, read via `GET /api/loop/config`). So your slider and “Apply settings” directly control this worker.

| Setting | Value |
|--------|--------|
| **Service name** | e.g. `motion-balanced` or `motion-loop` |
| **Root Directory** | (empty or repo root) |
| **Builder** | Dockerfile |
| **Start Command** | `python scripts/automate_loop.py` |

**Environment variables:**

| Variable | Value |
|----------|--------|
| `API_BASE` | `https://motion.productions` |

Do **not** set `LOOP_EXPLOIT_RATIO_OVERRIDE`. Optionally set `LOOP_WORKFLOW_TYPE=main` for the **main** badge on the site.

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

**Explorer**

```env
API_BASE=https://motion.productions
LOOP_EXPLOIT_RATIO_OVERRIDE=0
LOOP_WORKFLOW_TYPE=explorer
```

**Exploiter**

```env
API_BASE=https://motion.productions
LOOP_EXPLOIT_RATIO_OVERRIDE=1
LOOP_WORKFLOW_TYPE=exploiter
```

**Balanced (UI-controlled)**

```env
API_BASE=https://motion.productions
# Do not set LOOP_EXPLOIT_RATIO_OVERRIDE — uses webapp Loop controls
LOOP_WORKFLOW_TYPE=main
```

**Interpretation (no create/render)**

```env
API_BASE=https://motion.productions
INTERPRET_DELAY_SECONDS=10
```

---

## 7. Verify

1. **Railway dashboard** — Each service shows **Active** and recent logs (e.g. `[1]`, `[2]`, … for loop; `interpreted:` / `backfill:` for interpretation).
2. **motion.productions** — In **Recent videos** and **Recent activity** you should see new runs with **Explore** and **Exploit** badges (for jobs created after the workflow_type deploy).
3. **API** — `GET https://motion.productions/api/jobs?status=completed&limit=5` — each job should include `workflow_type` when set. `GET /api/knowledge/for-creation` returns `interpretation_prompts` when the interpretation worker has stored results.

---

## 8. Reference

- Env source of truth: `config/workflows.yaml`
- Loop behavior: `docs/INTENDED_LOOP.md`, `docs/AUTOMATION.md`
- Deploy (Cloudflare + DB): `docs/DEPLOY_CLOUDFLARE.md`
