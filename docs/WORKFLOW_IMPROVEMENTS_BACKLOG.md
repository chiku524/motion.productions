# Workflow Improvements Backlog

Potential enhancements for better loop performance, reliability, and output quality.

---

## Implemented (2026-02-10)

| # | Item | Implementation |
|---|------|----------------|
| 1 | Batch interpretation backfill | `POST /api/interpretations/batch`; interpret_loop fetches 50, interprets, batch POSTs |
| 2 | Discovery rate feedback | `_get_discovery_adjusted_exploit_ratio()` caps exploit at 0.4 when discovery_rate_pct < 10% |
| 3 | Health endpoints | `--health-port` / `HEALTH_PORT`; Worker `/health`, `/api/health`; `src/workflow_utils.start_health_server()` |
| 4 | KV rate-limit | State save uses `max_retries=5`; api_request already retries 429 with backoff |
| 5 | Queue prioritization | `ORDER BY CASE WHEN source = 'web' THEN 0 ELSE 1 END` in GET /api/interpret/queue |
| 6 | Prompt deduplication | `_is_near_duplicate()` in prompt_gen; skip if >80% word overlap with avoid set |
| 7 | Structured logging | `log_structured()` in workflow_utils; automate_loop logs phase, run, job_id, prompt_preview |
| 8 | Graceful shutdown | `setup_graceful_shutdown()`; SIGTERM/SIGINT set flag; loop checks `request_shutdown()` |
| 9 | Metrics export | `GET /api/metrics` returns Prometheus text format (total_runs, precision_pct, discovery_rate_pct) |
| 10 | Exploit variety | When exploiting, exclude prompts in `recent_prompts` so loop prefers different good prompts. |

---

## Future ideas

- **Batch discovery POST:** Reduce round-trips when syncing many discoveries.
- **Interpretation cache:** Skip re-interpreting identical prompts.
- **Adaptive delay:** Adjust LOOP_DELAY based on queue depth or error rate.

---

---

## Registry scan findings (2026-02-12)

From `motion-registries-2026-02-12.json`:

| Finding | Fix |
|---------|-----|
| **Interpretation registry empty** | Run `py scripts/backfill_interpretations.py --api-base https://motion.productions`. Ensures interpret worker is deployed and polling. |
| **9/20 jobs missing discovery** | Worker now records `discovery_runs` when `job_id` present (even if 0 novel discoveries). Ensures D1 migration 0013 applied. |
| **"gradual in symmetric silence" repeated 5x** | Exploit path can pick same good_prompt repeatedly. Consider: when exploiting, also avoid prompts in last N recent for variety. |
| **Blend names like "lixakafereka", "ralocadutoca"** | ✅ Fixed: Python assigns semantic names for all discoveries before sync; Worker uses semantic word invention (mirrors blend_names); RGB→semantic hints (slate, ember, etc.). |
| **Precision 80%, target 95%** | 1 job missing learning. Check POST /api/learning success; ensure job_id is in payload. |
| **Discovery rate 55%** | Will improve with discovery_runs fix; backfill interpretations so `interpretation_prompts` feeds creation. |

---

*Last updated: 2026-02-12*
