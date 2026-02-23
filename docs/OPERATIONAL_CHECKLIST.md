# Operational checklist — post–Manus AI report

Use this after code changes to ensure deploy, workers, and data quality are correct.

---

## 1. Deploy the Cloudflare Worker (learned_lighting/composition/etc. merge)

The Worker code in `cloudflare/src/index.ts` already merges **learned_lighting**, **learned_composition**, **learned_graphics**, **learned_temporal**, **learned_technical** into GET /api/registries. You need this deployed so exports and UI show those categories.

**Steps:**

1. **If you just pushed to `main`**  
   GitHub Actions runs automatically. Go to **GitHub → Actions** and confirm the **Deploy to Cloudflare** workflow completed successfully.

2. **If you need to redeploy without a new push**  
   - **GitHub** → repo → **Actions** → **Deploy to Cloudflare** → **Run workflow** (branch: `main`) → **Run workflow**.  
   - Wait for the job to finish; the Worker at `https://motion.productions` will serve the new code.

3. **Optional local deploy** (from repo root):  
   `cd cloudflare && npm run deploy`  
   (Requires `npx wrangler login` and env; usually use Actions.)

**Verify:** After deploy, GET `https://motion.productions/api/registries` and check that `dynamic.lighting`, `dynamic.composition`, etc. are present (they may still be empty until the Balanced worker posts data).

---

## 2. Set LOOP_EXTRACTION_FOCUS=window on the Balanced worker (Railway)

So the Balanced worker does **per-window** extraction only (dynamic + narrative), and logs **Growth [window]**.

**Steps:**

1. Open **Railway** → your project → the **Balanced** service (e.g. `motion-balanced` or `motion-loop`).
2. Go to **Variables** (or **Settings** → **Environment**).
3. Ensure:
   - **`LOOP_EXTRACTION_FOCUS`** = **`window`** (exact name; not `LCXP_EXTRACTION_FOCUS`).
   - **`API_BASE`** = `https://motion.productions`.
4. If you add or change the variable, **Redeploy** the service so the new env is used.

**Verify:** In the Balanced service logs you should see **Growth [window]** (not `Growth [frame]` or `Growth [all]`). See **RAILWAY_CONFIG.md** §8 and **PRECISION_VERIFICATION_CHECKLIST.md** §1.

---

## 3. Run backfill_registry_names.py (fix numeric names)

Fixes non-semantic names (e.g. `Slate5441`) in colors_from_blends and other tables. Run to completion; re-run if it times out.

**Command (no dry-run):**

```bash
python scripts/backfill_registry_names.py --api-base https://motion.productions --timeout 300
```

- **`--timeout 300`** gives 5 minutes per request (default is 120); use if you hit timeouts.
- To process only one large table: **`--table learned_blends`** (then run again without `--table` for the rest).

**Verify:** Re-export registries or GET /api/registries and confirm `colors_from_blends` (and other domains) no longer show numeric-suffix names.

---

## 4. Re-run color_sweep.py when the API is stable

Increases static color coverage by registering a grid of RGB cells. Run when the API is reachable so discoveries are POSTed.

**Command:**

```bash
python scripts/color_sweep.py --api-base https://motion.productions --steps 5 --limit 150
```

- Optional: **`--steps 6`** for finer grid; **`--limit 200`** for more cells. Use **`--dry-run`** to preview without POSTing.

**Verify:** GET /api/registries/coverage and check **static_colors_coverage_pct** (or export and inspect static_colors count).

---

## 5. Confirm sound_loop is deployed and POSTing (static_sound)

So the **pure (static) sound** registry grows from real audio.

**Steps:**

1. **Railway** — Ensure a **fifth service** runs **sound_loop**. The start command is set in **railway.toml** (`python scripts/railway_start.py`); do **not** override Start Command in the dashboard. Set env so the dispatcher runs the sound script:
   - **`RAILWAY_START_SCRIPT`** = **`sound_loop`**
   - **`API_BASE`** = `https://motion.productions` (optional: `SOUND_LOOP_DELAY_SECONDS=15`, `SOUND_LOOP_DURATION_SECONDS=2.5`, `HEALTH_PORT=8080`).
   - See **RAILWAY_CONFIG.md** §5.5 and §7.2.

2. **Verify deployment:**  
   Logs should show **Sound-only worker started (no create/render)** and lines like **`[N] sound discovery: +M`** when new sounds are added.

3. **Verify POST and registry:**  
   - After a few cycles: `curl -s "https://motion.productions/api/knowledge/for-creation" | jq '.static_sound | length'`  
   - Should be **> 0** once the Sound worker has run and POSTed discoveries.

**Troubleshooting:** No discoveries → check `API_BASE` and network. Empty `static_sound` in for-creation → ensure Sound service ran several cycles and POST /api/knowledge/discoveries succeeds. See **PRECISION_VERIFICATION_CHECKLIST.md** §5.

---

## Quick reference

| Task | Where | Command / action |
|------|--------|-------------------|
| Deploy Worker | GitHub Actions | Actions → Deploy to Cloudflare → Run workflow |
| Balanced = window | Railway → Balanced service | Set `LOOP_EXTRACTION_FOCUS=window`, redeploy |
| Backfill names | Local/CI | `python scripts/backfill_registry_names.py --api-base https://motion.productions --timeout 300` |
| Color sweep | Local/CI | `python scripts/color_sweep.py --api-base https://motion.productions` |
| Sound worker | Railway | 5th service: `python scripts/sound_loop.py`, `API_BASE` set; verify logs and for-creation |
