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

---

## Future ideas

- **Batch discovery POST:** Reduce round-trips when syncing many discoveries.
- **Interpretation cache:** Skip re-interpreting identical prompts.
- **Adaptive delay:** Adjust LOOP_DELAY based on queue depth or error rate.

---

*Last updated: 2026-02-10*
