# Multi-Workflow Setup on Railway

Run multiple loop workers in parallel for faster learning. Each worker shares the same KV/D1; quality is preserved.

---

## Quick Setup

1. **Existing service** — Your current worker (e.g. `motion-loop`). No changes if you want it as "balanced" (uses webapp).

2. **Add Explorer** — New service from same repo:
   - Root Directory: (repo root)
   - Build: Dockerfile
   - Start: `python scripts/automate_loop.py`
   - Variables: `LOOP_EXPLOIT_RATIO_OVERRIDE=0`, `API_BASE=https://motion.productions`

3. **Add Exploiter** — Another new service:
   - Same as above
   - Variables: `LOOP_EXPLOIT_RATIO_OVERRIDE=1`, `API_BASE=https://motion.productions`

---

## Environment Variables per Worker

| Service  | `LOOP_EXPLOIT_RATIO_OVERRIDE` | Behavior        |
|----------|-------------------------------|-----------------|
| Explorer | `0`                           | 100% explore    |
| Balanced | (not set)                     | Uses webapp     |
| Exploiter| `1`                           | 100% exploit    |

---

## Steps (Railway UI)

1. Railway Dashboard → Your Project
2. **New** → **Empty Service**
3. **Connect repo** (same repo as existing worker)
4. **Settings**:
   - Root Directory: leave empty (repo root)
   - Builder: Dockerfile
   - Start Command: `python scripts/automate_loop.py`
5. **Variables** → Add:
   - `API_BASE` = `https://motion.productions`
   - `LOOP_EXPLOIT_RATIO_OVERRIDE` = `0` (Explorer) or `1` (Exploiter)
6. **Deploy**

Repeat for each workflow you want.

---

## Verify

- All services show logs like `[1]`, `[2]`, …
- Webapp loop status reflects combined activity
- Recent videos grow faster with multiple workers
