# Workflow Improvements Backlog

Potential enhancements for better loop performance, reliability, and output quality.

---

## High impact

### 1. Batch interpretation backfill

**Current:** `interpret_loop.py` backfills prompts from jobs table one-by-one.  
**Improvement:** Batch fetch N jobs without interpretation, interpret in parallel (or sequentially with connection pooling), then batch-insert. Reduces API round-trips.

### 2. Discovery rate feedback to exploit ratio

**Current:** Exploit ratio (70/30) is fixed or UI-controlled.  
**Improvement:** When `discovery_rate_pct` drops (e.g. < 10%), auto-increase explore ratio temporarily so the loop discovers more before saturating.

### 3. Health/readiness endpoints

**Current:** Railway workers run until crash; no liveness check.  
**Improvement:** Add a minimal HTTP health endpoint (if loop exposes one) or use Railway's process health. Enables faster restarts and better observability.

---

## Medium impact

### 4. KV rate-limit awareness

**Current:** State saved every N runs; 1 write/sec per KV key.  
**Improvement:** If POST /api/loop/state returns 429, back off and retry with exponential delay instead of logging and continuing.

### 5. Interpretation queue prioritization

**Current:** Queue processed FIFO.  
**Improvement:** Prioritize prompts from recent jobs or from user-submitted queue over old backfill items when both exist.

### 6. Procedural prompt deduplication

**Current:** `avoid` set prevents repeats within recent prompts, but exploration can still produce near-duplicates.  
**Improvement:** Semantic or keyword-based dedup (e.g. skip if prompt shares >80% words with recent) to reduce redundant exploration.

---

## Lower priority

### 7. Structured logging for diagnostics

**Current:** Logs are free-form.  
**Improvement:** JSON or structured log format (job_id, workflow_type, phase, duration) for easier parsing in Railway logs / external monitoring.

### 8. Graceful shutdown

**Current:** Loop exits on SIGTERM mid-run.  
**Improvement:** Catch SIGTERM, finish current run if possible, then exit. Avoids partial state.

### 9. Metrics export

**Current:** Discovery rate, precision in API/UI.  
**Improvement:** Prometheus-compatible `/metrics` or periodic stats push for dashboards.

---

*Last updated: 2026-02-10*
