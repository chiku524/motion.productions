# Railway config checklist — both workflows on motion.productions

Use this to confirm **Explorer** (discovery) and **Exploiter** (interpretation) are both running and posting to the same site. Both outputs appear in the **Recent videos** library and **Recent activity** on [motion.productions](https://motion.productions), with badges so you can tell which workflow produced each run.

---

## 1. Project layout

- **One Railway project** with **two services** (or three if you also run Balanced).
- **Same repo** for all: root = repo root (not `cloudflare/`).
- **Same build**: Dockerfile.
- **Same start command**: `python scripts/automate_loop.py`.

Only **environment variables** differ per service.

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

## 5. Quick reference (copy-paste)

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

---

## 6. Verify

1. **Railway dashboard** — Both services show **Active** and recent logs (e.g. `[1]`, `[2]`, …).
2. **motion.productions** — Open the site; in **Recent videos** and **Recent activity** you should see new runs with **Explore** and **Exploit** badges (for jobs created after the workflow_type deploy).
3. **API** — `GET https://motion.productions/api/jobs?status=completed&limit=5` — each job should include `workflow_type` when set.

---

## 7. Reference

- Env source of truth: `config/workflows.yaml`
- Loop behavior: `docs/INTENDED_LOOP.md`, `docs/AUTOMATION.md`
- Deploy (Cloudflare + DB): `docs/DEPLOY_CLOUDFLARE.md`
