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

See **PRECISION_VERIFICATION_CHECKLIST.md** and **REGISTRY_REVIEW_AND_IMPROVEMENT_PLAN.md** for ongoing verification.
