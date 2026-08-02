# Backlog and enhancements

Merged from **ENHANCEMENTS_AND_OPTIMIZATIONS** (seven steps) and **WORKFLOW_IMPROVEMENTS_BACKLOG** (implemented items and future ideas).

---

## Part I — Seven enhancement steps (status)

| Step | Goal | Status |
|------|------|--------|
| **1** | All API calls validated; retries, logging, no silent swallow | ✅ Done — api_client, automate_loop, lookup, remote_sync |
| **2** | Every MP4 has audio; mandatory _add_audio; failures surfaced | ✅ Done — pipeline, sound.py |
| **3 & 4** | Origin-based blending (prompt → primitives; creation/renderer use blended values) | ✅ Done — interpretation, builder, renderer |
| **5** | Extraction captures exact transformed value (RGB, motion, etc.); registry stores exact | ✅ Done |
| **6** | Growth: random selection (secure_choice); extract, record, name blends | ✅ Done — random_utils, pick_prompt, builder |
| **7** | Record all new values; English-like name algorithm | ✅ Done — blend_names, registry |

---

## Part II — Workflow improvements (implemented)

| # | Item | Implementation |
|---|------|----------------|
| 1 | Batch interpretation backfill | POST /api/interpretations/batch; interpret_loop fetches 50, batch POSTs |
| 2 | Discovery rate feedback | _get_discovery_adjusted_exploit_ratio() caps exploit when discovery_rate_pct < 10% |
| 3 | Health endpoints | --health-port, Worker /health, /api/health, start_health_server() |
| 4 | KV rate-limit | State save max_retries=5; api_request retries 429 with backoff |
| 5 | Queue prioritization | ORDER BY source = 'web' first in GET /api/interpret/queue |
| 6 | Prompt deduplication | _is_near_duplicate() in prompt_gen; skip >80% word overlap with avoid |
| 7 | Structured logging | log_structured(); automate_loop logs phase, run, job_id, prompt_preview |
| 8 | Graceful shutdown | setup_graceful_shutdown(); request_shutdown() in loop |
| 9 | Metrics export | GET /api/metrics (Prometheus: total_runs, precision_pct, discovery_rate_pct) |
| 10 | Exploit variety | Exclude recent_prompts when exploiting |
| 11 | Repetition cap | repetition_score in progress; cap exploit when > 0.35 |
| 12 | Exploiter discovery cap | Cap exploit at 0.80/0.90 when discovery_rate low |
| 13 | Interpretation learning loop | Diverse prompts, linguistic mappings, linguistic_registry growth |

---

## Part III — Future ideas

- **Batch discovery POST:** Reduce round-trips when syncing many discoveries.
- **Interpretation cache:** Skip re-interpreting identical prompts.
- **Adaptive delay:** Adjust LOOP_DELAY based on queue depth or error rate.

---

## Part IV — Registry scan findings (reference)

| Finding | Fix |
|---------|-----|
| Interpretation registry empty | Run `scripts/backfill_interpretations.py --api-base https://motion.productions` |
| Jobs missing discovery | Worker records discovery_runs when job_id present; ensure D1 migration 0013 |
| Repeated good_prompt | Exploit path avoids recent_prompts (implemented) |
| Non-semantic blend names | Fixed: semantic names before sync; backfill_registry_names.py |
| High counts / repetition | repetition_score; Exploiter discovery cap (implemented) |
| Missing learning | job_id in POST /api/learning; retries in automate_loop |

See **PRECISION_VERIFICATION_CHECKLIST.md** and **REGISTRY_AND_WORKFLOW_IMPROVEMENTS.md** for ongoing verification.

---

## Part V — Aug 2, 2026 audit fixes

Applied from the Aug 2 mission-progress audit (canvas `mission-progress-audit`):

| Finding | Fix | Result |
|---------|-----|--------|
| `/api/registries` totals were `array.length` of a `LIMIT`-bound sample, silently capping at the request limit | Added `getTrueRegistryTotals()` (`cloudflare/src/db.ts`): real `COUNT(*)` via primary DB, KV-cached 10 min; wired into all `/api/registries` totals (static, dynamic, narrative, interpretation, linguistic) | Deployed. Exposed a **major stale-cache bug**: the KV `registries:counts` cache said `static_colors = 28,624`; a fresh `COUNT(*)` shows the real number is **525**. The cache had drifted after a color dedup/reconcile pass deleted rows without decrementing the KV counter (`bumpRegistryCounts` only increments). KV cache has been self-healed by the `?fresh=1` call. **Color grid coverage is ~1.9% (525/27,951), not 100%** — correct the prior audit's "biggest win" claim. |
| Narrative `themes` origin list mixed in settings/color words (`neon`, `night`, `fire`, `ocean`, `forest`, `warm_sunset`, `mono`, `urban`) | Removed from `NARRATIVE_ORIGINS["themes"]` in `src/knowledge/origins.py`; removed the `spec.palette_name`/`palette_hints` → themes fallback in `src/knowledge/narrative_registry.py`; dropped `"urban"` from the runtime `theme_keywords` prompt scan (already owned by settings) | Regenerated `cloudflare/src/registryConstants.generated.ts` (themes origin size 25 → 17). Stops new bleed; historical bad rows (magenta/fire/warm_sunset already in D1) remain since there is no narrative-entry delete endpoint — add one if a retroactive cleanup is wanted. |
| `generate.py --learn` audited as using legacy `grow_from_analysis` | Re-checked: already fixed in `dbff14d` (before this audit) — uses `grow_all_from_video` + `grow_narrative_from_spec`. Corrected `ALGORITHMS_AND_FUNCTIONS_AUDIT.md`, which was stale. | No code change needed. |
| 485 gibberish/numeric-suffix names (`/api/registries/health`) | Ran `scripts/backfill_registry_names.py` against production repeatedly (small `--limit 10` batches — see cascade note below); also found and fixed an off-by-one (`LENGTH(name) > 9` vs. `isGibberishName`'s actual `> 8` cutoff) in the three backfill WHERE clauses in `registries.ts` | Reduced from 485 → 312. Residual ~312 is a real gap between the exhaustive `isGibberishName` scan in `/api/registries/health` (first 500 rows, no WHERE filter) and the backfill endpoint's WHERE-prefiltered candidate set on very large tables (`learned_blends` alone has 150k+ rows); needs a follow-up pass, ideally after making `cascadeNameUpdate` cheaper (see below). |
| `exploiter` / `video-ai-render` not running locally | Re-checked `docker-compose.local.yml` + `docs/LOCAL_COMPUTE.md`: both are **intentionally opt-in** (`loops-full` / `video-ai` profiles) to protect the D1 free-tier CPU budget and because `video-ai-render` needs `OPENAI_API_KEY`. Not a bug. Documented in `AGENTS.md` so future audits don't re-flag it. | No change needed. |
| 14 untracked scratch `*.log` / `cov*.json` files at repo root | Deleted; added `/*.log` and `/cov*.json` to `.gitignore` | Clean working tree. |

**New follow-up discovered while fixing the above:** `cascadeNameUpdate()` (`cloudflare/src/naming.ts`) runs 21 sequential `UPDATE ... WHERE col LIKE ?` statements per renamed row, across tables that now hold 100k+ rows (`learning_runs`, `interpretations`, `jobs`, `learned_blends`). At `--limit 100` this reliably exceeded a 120s client timeout (and likely Cloudflare's own execution limit) on tables with many renames pending. Backfill only works reliably now at small batch sizes (`--limit 10`). Consider: making the cascade a KV-queued background job, skipping cascade for tables where the renamed value is very unlikely to appear in `sources_json`/prompts, or batching the 21 `LIKE` updates into fewer statements.
