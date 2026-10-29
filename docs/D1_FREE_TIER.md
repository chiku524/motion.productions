# D1 free tier: keeping `motion-productions-db` under 500 MB

Free caps: 500 MB per database, 5 M rows read / day, 100 k rows written / day (reset 00:00 UTC).
When the file is full every write fails with `Exceeded maximum DB size`; the Worker now answers those with a degraded
HTTP 200 (`{"degraded":true,"error":"d1_db_full","recorded":false}`, header `X-Degraded: d1_db_full`) and the Python
client (`src/api_client.py`) pauses writes for `FREE_TIER_LIMIT_COOLDOWN_SECONDS` (default 900 s).

## What stops the regrowth (all in the Worker, no schema change, no cron)
| change | where | per-clip effect |
|---|---|---|
| `learned_blends` get a deterministic id (`bl_` + sha256(domain + normalized output)), written with `INSERT OR IGNORE` | `src/blendId.ts`, `discoveryWriter.ts` | a new blend costs 3 rows written (row + 2 index entries); a repeat costs **0**. Up to ~13 blends per clip => ~39 rows/clip trending to ~0 |
| `learning_runs` keep only `motion_level/mean_brightness/mean_contrast` + 7 scalar spec fields (`store_full:true` opts out) | `learningSlim.ts`, `routes/jobs.ts` | row shrinks from several KB (per-frame arrays) to ~150 bytes |
| daily opportunistic prune of `learning_runs`, `events`, `discovery_runs`, and `jobs` without an R2 object / children older than `RETENTION_DAYS` (3) | `retention.ts` | marker check costs 0 rows written; a due run is capped at `RETENTION_BATCH_ROWS` (500) x `RETENTION_MAX_BATCHES` (3) rows per table and `RETENTION_WRITE_BUDGET` (6000) rows written |
| DB-full guard | `limits.ts`, `index.ts` | no 5xx, no retry storm |

Retention knobs (Worker vars, all optional): `RETENTION_DAYS`, `RETENTION_BATCH_ROWS`, `RETENTION_MAX_BATCHES`,
`RETENTION_WRITE_BUDGET`, `RETENTION_CHECK_INTERVAL_SEC` (per-isolate throttle, default 1800), `RETENTION_DISABLED=1`.
A due run on the first write of the day adds up to ~14 D1 requests to that one POST (well under the 50 subrequest limit).
It creates a tiny `retention_marker` table lazily (`CREATE TABLE IF NOT EXISTS`), so no remote migration is needed.

## What this does NOT do
Deleting rows does not shrink a SQLite file by itself, and deletes cost writes (row + each index entry), so the existing
~1.4 GB cannot be pruned back under 500 MB within the 100 k writes/day cap. Reclaiming space means exporting the must-keep
tables and recreating the database/tables (needs explicit approval). `cloudflare/migrations_pending/` holds unapplied SQL.
## Shared daily write budget (client side, all containers)
Incident: the first live run of the 7-container fleet wrote ~5,058 rows in 9 minutes (~800 k/day, 8x the 100 k cap).
`interpret` alone wrote ~1,676 rows and `sound` 16-29 rows per iteration. The fix is a hard budget enforced where the writes
originate, plus buffers that make each write carry more information.

### Rows written per call (audit, from the Worker routes and migrations)
D1 counts a row per table row written **plus one per index entry** (PK/UNIQUE autoindexes included). INSERT = 1 + #indexes;
UPDATE of a non-indexed column = 1; an UPDATE of an indexed column rewrites that index entry. `src/knowledge/write_budget.py`
(`INSERT_ROWS`, `UPDATE_ROWS`, `estimate_rows`) encodes this; `tests/test_write_budget_calibration.py` derives the index
counts from `migrations/*.sql` (sqlite `PRAGMA index_list`) and fails if the table drifts. Measured against D1 (miniflare,
`cloudflare/test/writeBudget.test.mjs`): jobs 5, job complete 2, learning 4, **event 5** (was 4), interpretation 4, interpret
queue 4, interpret PATCH 3, linguistic new 5 / bump 1, coverage chunk 1, static_colors 7, blend 4 (+ ~1.7 reserved names x 2).

| endpoint (client writer) | rows written per call | notes |
|---|---|---|
| `POST /api/knowledge/discoveries` (explorer, balanced, sound, webjobs, ...) | per **new** item: `static_colors` 7 (+3 reserved name), `static_sound` 5, `learned_colors` 4 (+3), `learned_blends` 4 (+6: ~1.7 names reserved, 2 rows each), motion/lighting/profile 4, narrative 5; repeat key = 1 (`count = count + delta`); `+3` for `discovery_runs` when `job_id` is sent | batch dedupes by key; chunk <= `DISCOVERIES_MAX_ITEMS` (36) |
| `POST /api/linguistic-registry/batch` (interpret, loops) | new span 5, existing span **1** (single `db.batch` upsert, no SELECT) | `count` field sums coalesced bumps |
| `POST /api/linguistic-registry` (single) | new 5 / existing 1 + a SELECT | superseded by the batch route |
| `POST /api/interpretations/batch` (interpret) | 4 per new row (row + PK + `idx_status` + `idx_updated_at`) | |
| `POST /api/interpretations`, `POST /api/interpret/queue` | 4 | |
| `PATCH /api/interpret/:id` (interpret container, one per prompt) | 3 (measured; **was estimated as the unknown-path default and returned no `rows_written`**) | |
| `POST /api/jobs` | 5 (row + PK + 3 indexes) | |
| `POST /api/jobs/:id/complete` / `/upload` | 2 (measured) / 3 | |
| `POST /api/learning` | 4 | |
| `POST /api/coverage/color/chunks` (survey `COLOR_SYNC=1`) | 1 per **changed** chunk (0 for an unchanged merge); est. 2 | |
| `POST /api/events` | 5 (row + 4 indexes) | |
| any other write | 5 (`UNKNOWN_WRITE_ROWS`) | |
| `POST /api/loop/state`, GET anything | **0** D1 rows (KV / reads) | a cold GET may write 1 row (retention marker), existing behaviour |

`name_reserve` (PK + 1 unique index = 2 rows) is added for every novel generated name; the estimate folds it into the per-table
numbers. Estimates are worst case (all items new). **The real number comes from the Worker:** every write route
(`jobs`, `complete`, `upload`, `learning`, `events`, `feedback`, `interpret/queue`, `PATCH interpret/:id`, interpretations,
linguistic, discoveries, `name/take`, coverage chunks) returns D1's own `meta.rows_written` (`cloudflare/src/d1Meta.ts`), and the
discoveries / learning responses also include the **retention** rows they triggered (daily prune deletes cost index rows too:
up to 3 x 500 rows per table, `RETENTION_WRITE_BUDGET` 6000). `record_response()` books that figure instead of the estimate.

#### Why the ledger used to undercount (live run: D1 1,905 rows / 5 min vs ledger ~570)
1. Routes that wrote but returned no `rows_written` (`PATCH /api/interpret/:id` - the interpret container's main write -,
   `interpret/queue`, `learning`, `events`, `jobs`, ...) kept the client estimate; the unknown-path default (3) and `events` (4)
   were below the real 3-5.
2. `/api/coverage/color/chunks` reported the statement count, not D1's rows.
3. Worker-side retention (claims, deletes, marker updates) is written by the Worker inside someone else's request and was never
   reported; a due run can write ~1,000+ rows in one burst.
4. A retried POST (5xx / timeout) re-used its single reservation although the first attempt may have written rows; `api_post_binary`
   never settled.
5. `settle()` was a no-op without `actual`, so a Worker that did not report anything was silently trusted.

#### Fail-closed
A response without `rows_written` books the estimate **+25 %** and counts as *unreported*. `UNREPORTED_TRIP` (10) unreported answers
in a row mean the estimates are not trustworthy (old Worker, new unreported route): the ledger then **refuses every post except one
probe per 5 min** until a response reports `rows_written` again. `scripts/loop_metrics.py` prints the calibration line
(reported vs unreported posts, estimate/actual ratio) and a `LEDGER UNTRUSTED` warning.

### What the client does now
1. **Gate** (`src/api_client.py::api_request`, the single choke point for every container and endpoint): before any non-GET it
   `reserve()`s the estimated rows in the shared ledger. No allowance => `WriteBudgetSkipped` (HTTP 503 shape, never a retry,
   no network call). The loop keeps working locally.
2. **Ledger**: `ledger.json` + O_EXCL `ledger.lock` in `WRITE_BUDGET_DIR` (compose: `/app/knowledge/write_budget`, the shared bind
   mount). Per-container `used/posts/denied`, resets at 00:00 **UTC**. Fails closed if it cannot be read or locked.
3. **Split** of `D1_DAILY_WRITE_BUDGET` (default **50,000 real rows/day**, 50 % of the free limit; `0` disables): interpret 15 %,
   sound 10 %, explorer 30 %, balanced 30 %, everything else (webjobs, procedural-render, exploiter) a shared 5 % pool = 45,000
   allotted, 10 % unallotted reserve, and the 50 k between 50 k and 100 k absorbs retention, web users and any residual error. Override with
   `D1_BUDGET_WEIGHTS="explorer=30,balanced=30,..."` (percent).
4. **Priorities**: `high` = novel discoveries (may use the whole allowance); `low` = jobs, learning logs, interpretations,
   linguistic, events: capped at 50 % of the allowance and paced across the UTC day (15 % burst), so logs cannot starve
   discoveries. `webjobs` / `procedural-render` posts are always high (user-facing).
5. **Back-off**: Worker `X-Degraded` (`free_tier_limit`, `d1_db_full`), 429, or a D1 quota error body starts one shared
   back-off in the ledger for `Retry-After` (900 s) - every container stops posting, not just the one that saw it.
6. **Buffers** (`src/knowledge/write_buffers.py`, state per container in `WRITE_BUFFER_DIR`, atomic JSON, survives restarts):
   * `DiscoverySpool` - merges repeated items by identity and **sums `count_delta`** (Worker upserts `count = count + delta`),
     flushes in chunks of `DISCOVERIES_MAX_ITEMS`, **novel colour / sound / motion first**, then blends, then narrative;
     leftovers stay buffered when the budget or Worker says no. `DISCOVERY_FLUSH_INTERVAL_S`, `DISCOVERY_FLUSH_MAX_ITEMS`.
   * `LinguisticCoalescer` - `linguistic_registry` count bumps for the same (domain, span) are summed into one batched
     upsert per `LINGUISTIC_FLUSH_INTERVAL_S`; never-seen spans go first.
   * `InterpretationOutbox` - `interpret` only POSTs an interpretation whose prompt is unseen **and** whose instruction
     shape is novel (local hash check); everything else is kept in a local JSONL (`interpretations_local.jsonl`) and never
     re-generated. `INTERPRET_FLUSH_INTERVAL_S`, `INTERPRET_FLUSH_MAX_ITEMS`.
   * `sound`: only novel cells are posted, `DISCOVERIES_MAX_ITEMS=12` per POST, one flush per 10 min.
   * When a container's allowance is spent it keeps working locally and stops posting (`interpret`/`sound` idle
     `WRITE_BUDGET_SLEEP_WHEN_EXHAUSTED_S`, default 900 s in compose). After 00:00 UTC the buffers drain within the new day.
   * `WRITE_BUFFERS=0` restores the old unbuffered paths (the gate still applies).
7. **Local jobs**: if `/api/jobs` is denied the loop uses a local job id (`local-...`) and skips the job's complete/learning
   POSTs; the clip, novelty store and colour survey are unaffected.

### Trade-offs / risks
* `discovery_runs` (3 rows per clip) are only written when a flush carries a `job_id`; deferred flushes lose that row, so the
  discovery-rate metric in D1 undercounts while buffering. Use `scripts/loop_metrics.py` (local) for rates.
* Until the Worker deploy, estimates are worst case; the budget will under-use the true allowance rather than over-use.
* The ledger is per volume. Running the fleet from two different `./knowledge` directories gives two budgets - don't.
* **No Worker-side per-day counter.** A counter in D1 costs a write per request (it would eat the budget it protects) and KV
  has only 1,000 writes/day free, so none was added. The Worker only reports `rows_written` and honours the existing
  `free_tier_limit` / `d1_db_full` degraded responses.
* `exploiter` shares the 5 % `other` pool (opt-in profile); do not run it with the Core loops without raising that weight.

### Observing it
`python scripts/loop_metrics.py` prints, in addition to the clip metrics, a **D1 write budget** table: rows used today,
allowance, %, posts, denied rows and projected rows/day per container (including interpret and sound, which keep no clip
metrics), and the projected total across all containers. `python scripts/write_budget_dryrun.py` simulates 10 minutes and
a full UTC day of loop output for every container against a mock Worker (no network, virtual clock, ~2.5 min to run) and prints
baseline vs budgeted rows. The per-iteration work is a calibrated MODEL, not a measurement. Result with the compose defaults:
baseline demand ~346k rows/day (explorer 90k, balanced 93k, interpret 142k, sound 19k; crosses 100k at ~06:30 UTC), budgeted
~56k rows/day (explorer 21.0k, balanced 21.0k, interpret 5.0k, sound 7.0k, webjobs 1.9k, render 0.3k), 0 Worker rejections.
explorer, balanced and sound spend their whole allowance (surplus novel items stay in the local spool; the oldest lowest-priority
items are dropped when the spool is full), interpret stays under (low-priority pacing).
Tests: `tests/test_write_budget.py`, `tests/test_write_buffers.py`, `tests/test_compose_budget.py`,
`cloudflare/test/writeBudget.test.mjs`.

## Read-scan mitigations (5 M rows read / day)
Incident: `motion-productions-db` read ~55.7 B rows in one day. Cause: `POST /api/knowledge/name/take` called
`generateUniqueName`, which made up to 50 attempts x 4 name probes (`name_reserve`, `learned_blends`, `static_colors`,
`learned_colors`). The names come from a ~75-word vocabulary so collisions are constant, and `WHERE name = ?` on the three
big tables has no index = a full scan each time (~281 k rows for `learned_blends`). Code-only fix (no schema change, no new writes):

| path | before | after |
|---|---|---|
| `POST /api/knowledge/name/take`, `backfill-names`, `resolveUniqueBlendName` | up to ~200 table probes, 3 of them full scans | <= 3 batched `name_reserve` PK lookups (~17 rows each); `name_reserve` is the source of truth and is written on take/backfill |
| `GET /api/jobs` | unindexed `ORDER BY updated_at/created_at` sort per request, unauthenticated, uncached | snapshot cache (pending 15 s, completed 120 s, stale served on D1 limit), `ORDER BY rowid` (index walk, ~LIMIT rows), normalized cache key, 120 req/min/IP (429 + `Retry-After`, Cache API counter, no D1/KV writes) |
| `interpretations WHERE status='done'` (registries, browse, knowledge, loop) | sorted all done rows by `updated_at` | `ORDER BY rowid DESC LIMIT n` + 300 s cache (`readCache.recentDoneInterpretations`) |
| `static_colors / static_sound ORDER BY count DESC` (registries) | full scan per call | 300 s cache, stale on error |
| `learned_blends WHERE domain`, `jobs ... completed` in knowledge/loop | sorted by an unindexed column | `ORDER BY rowid DESC LIMIT n` over the status/domain index |

Trade-offs: legacy names that never reached `name_reserve` can be generated again (names are labels, ids are identity; when a
single word is taken the generator widens to 2-3 words). `rowid` order = insertion order, a close proxy for "recent".
Optional indexes are written but **not applied**: `cloudflare/migrations_pending/0101_optional_read_indexes.sql` (the DB is over its
500 MB cap, indexes are writes). Tests: `cloudflare/test/readScans.test.mjs`.

## Jobs-claim read burner (`GET /api/jobs?status=pending`) and poller audit
Incident (6 h window): `SELECT ... FROM jobs WHERE status='pending' AND (workflow_type IS NULL OR workflow_type='web') ORDER BY rowid LIMIT ?`
ran 135 times at ~31 k rows each = **4.19 M of ~4.4 M rows read**. Cause: loop-created jobs (`main`/`explorer`/`exploiter`/`cartoon`)
are never claimed, so they stay `pending` at the lowest rowids; retention only deleted completed/failed/error jobs. The `OR` filter
runs *after* the `idx_jobs_status` walk, so every cache miss read every pending loop job (index entry + table row).

### What changed (code only, no schema change, no write)
| layer | change |
|---|---|
| Worker `src/jobsClaim.ts` | `status='pending' AND rowid > ?` windows (100 rows, <= 20 per request) = a range seek on `idx_jobs_status`; the highest rowid proven to hold no claimable job is persisted as a **cursor** (isolate memory + Cache API, 6 h) and each junk row is read about once. Safe because status only moves pending -> completed/abandoned, `workflow_type` never changes and new rows get larger rowids |
| Worker caching | negative cache 60 s (proven empty), positive 5 s, incomplete scan 3 s; single-flight; **stale served on D1 error** with `degraded:true` and `poll_after_sec >= 300`; cache invalidated by `POST /api/jobs` for web/NULL jobs. Response adds `poll_after_sec` (+ `scan_complete`) |
| no double claim / starvation | `/upload` and `/complete` use `UPDATE ... WHERE id=? AND status='pending'` and check `meta.changes`; the scan is rowid-ordered (oldest web job first) and the cursor never passes an unseen claimable job |
| Client `src/poll_backoff.py`, `scripts/generate_bridge.py` | idle wait starts at **60 s** (was 20-30 s), doubles to 600 s with 0-25 % jitter, never shorter than `poll_after_sec` / `Retry-After` / the free-tier cooldown, resets when a job arrives; errors back off the same way; `APIError.retry_after` carries the header |
| `migrations_pending/0102`, `0103` | optional partial index and one-time batched retirement of stale loop jobs. **Not applied**, both cost writes; see that README |

Expected rows read per `GET /api/jobs?status=pending` (measured on local Miniflare, `cloudflare/test/jobsClaim.test.mjs`):
| case | before | after |
|---|---|---|
| cache hit | 0 | 0 (0 statements) |
| cache miss, steady state | ~31,000 | <= 200 (one window past the cursor); ~2 with `JOBS_PARTIAL_INDEX=1` |
| first miss with a cold cursor over N junk rows | ~31,000 | ~N once per colo/isolate per 6 h, <= 2,000 per request, cursor advances |
| per day, one idle bridge | ~1,440 x ~31 k = ~45 M | <= 1,440 misses/day (60 s poll, 60 s negative TTL; 144 once backed off to 600 s) x rows added since the cursor (typically < 20, hard cap 200) = ~3 k typical, 29 k at 20 rows/poll, 288 k only if the loops add >= 100 pending jobs per minute |

### Fixed-interval poller audit (estimates from code; D1 is quota-blocked so none could be measured)
Rows = D1 rows read per call that reaches D1 (a Worker cache hit reads 0). Flag = more than 100 k rows/day.
| poller | endpoint | interval | D1 rows per call (from code) | est. rows/day | flag |
|---|---|---|---|---|---|
| webjobs bridge (`generate_bridge.py`) | `GET /api/jobs?status=pending` | 60 -> 600 s back-off | <= 200, typically < 20 (was ~31 k) | ~3-30 k per bridge | no (was **yes**) |
| interpret loop (`interpret_loop.py`, compose delay 90 s, code default 10 s) | `GET /api/interpret/queue` | 90 s (960/day); 10 s outside compose (8,640/day) | **uncached**; `WHERE status='pending' ORDER BY CASE ... created_at` reads every pending interpretation (~2 per row) and sorts | 960 x 2N: > 100 k once pending N > ~52 (N unknown while D1 is blocked) | **fixed** - see "Final poller budget" below |
| main/explorer/exploiter loops (`automate_loop.py`, 15-30 s) | `GET /api/loop/config` | every run | 0 (KV) | 0 | no |
| same | `GET /api/registries/coverage` | every run | cached 1800 s (+ KV 6 h), single-flight; a miss runs whole-table aggregates (`missionStats`, ~20 `COUNT(*)`) | misses ~48/day/colo x full scans of the large registries (hundreds of k rows each) | **maybe**: bounded by cache, size of tables unknown; check after quota reset |
| sound loop (`sound_loop.py`, 75 s) | `GET /api/registries/coverage` | per cycle | same cache | same | maybe (shared with above) |
| mission targets (`mission_targets.py`) | `GET /api/registries/mission` | per run | `MISSION_STATS_SOFT_TTL_SEC` 2 h, stale on error | ~12 misses/day/colo of full scans | maybe |
| web app / dashboards | `GET /api/jobs?status=completed` | user driven | cached 120 s, `ORDER BY rowid DESC LIMIT n` | <= 720 misses x ~LIMIT | no |
| web app | `GET /api/loop/status` | user driven | uncached; a few `LIMIT 10` queries + coverage snapshot | ~30 rows/call | no |
| Prometheus scrape (none in repo) | `GET /api/metrics` | external | **uncached** `SELECT COUNT(*) FROM jobs WHERE status='completed'` (+ `LIMIT` lookups) = one row per completed job per scrape | scales with scrape rate x completed jobs | flag only if something scrapes it |

Nothing else in `src/` or `scripts/` polls on a fixed interval; the rest are per-run calls driven by job generation.

## Final poller budget (interpret queue + registry/metrics snapshots)
Branch `fix-interpret-queue-reads`. Code only: no schema change, no extra D1 write (Cache API / KV only, KV puts are gated by `kvPersistSec`).
Supersedes the "interpret loop" row above (**now fixed**) and the "maybe" rows for coverage, mission, sound loop and `/api/metrics`.

| change | detail |
|---|---|
| `GET /api/interpret/queue` (`src/interpretQueue.ts`) | `status='pending' AND rowid > ? ORDER BY rowid LIMIT <= 50` = index range seek (<= ~2 rows per item returned, one statement); rowid cursor `after`; negative cache 60 s, positive 5 s, stale served up to 1 h on a D1 error; `poll_after_sec` (0 with work, 120 empty, >= 300 degraded) and `Retry-After`. Web prompts first inside the window. POST enqueue / PATCH complete invalidate the local cache. PATCH is atomic (`UPDATE ... AND status='pending'`, `meta.changes` checked) so two workers can't both complete a row |
| Client `src/interpret_queue_poller.py`, `scripts/interpret_loop.py` | the queue is polled only when due: idle wait >= 120 s, doubling to 600 s, 0-25 % jitter, never below `poll_after_sec` / `Retry-After` / free-tier cooldown; new work resets it; retries of rows already attempted don't. `INTERPRET_DELAY_SECONDS` default 10 -> 90 (it only paces the other phases now); client GET caches 90 s -> 600 s |
| `GET /api/linguistic-registry` | was an uncached full table scan per call (interpret loop, automate loop, bridge, generator). Now a snapshot: soft 12 h, hard 7 d, KV copy refreshed every 6 h, stale on error |
| `/api/metrics` | run stats 15 min, `COUNT(*)` of completed jobs 6 h (separate snapshot), `Cache-Control: max-age=60` |
| `/api/registries/mission` | `SELECT DISTINCT aspect FROM narrative_entries` was uncached on every call: now a 6 h snapshot; mission stats soft TTL 2 h -> 6 h |
| `/api/registries/coverage` | soft 4 h (was 30 min), KV 2 h |
| true totals (registry browse) | soft 12 h (was 1 h). `COUNT(*)` of `learned_blends` (~280 k rows, >300 k rows per rebuild) is its own 7-day snapshot, so a totals rebuild or `?fresh=1` no longer rescans it |
| `/api/loop/progress` | 30 min, `last` clamped |

**Mission stats / `static_colors GROUP BY family` (1,331 rows) ran 36 times in an hour.** Memory -> Cache API -> KV already used a
stable key, but nothing stopped many isolates/colos missing at once and `GET /api/loop/progress` rebuilt on a miss. Now
(`cloudflare/src/snapshotCache.ts`): **fresh 6 h, stale-while-revalidate 24 h** (`MISSION_STATS_SWR_SEC`); inside the SWR window a
request is answered from the stale copy and ONE rebuild is started in the background (per-isolate `refreshing` set plus a
cross-isolate refresh lock `snaprefresh:<key>`, 120 s); the loop progress endpoint only *peeks* (never rebuilds inside SWR); every
rebuild logs `snapshot rebuild <key> reason=<miss|stale|force|...>` so the trigger of any future repeat is visible in
`wrangler tail`. No D1 scan runs on a loop request path while a copy younger than 30 h exists. `GROUP BY status, workflow_type` on
`jobs` (the 1.2 M-read query seen in insights) is **not in this repo** (git grep over src, cloudflare, scripts, .github, docs):
it comes from the D1 console/an external client and should be stopped there.

Measured on local Miniflare (`cloudflare/test/interpretQueue.test.mjs`, `pollerReads.test.mjs`): a queue miss over 1,200 pending rows reads <= ~60 rows (was ~2,400); 25 polls of an empty queue read 0 rows; 20 repeat calls of linguistic-registry, metrics, coverage, mission and progress run 0 statements; a metrics miss is <= 5 statements.

### Estimated rows read per day, all pollers (remote D1 was quota-blocked: estimates from code, Miniflare measurements and the row counts quoted above; unknown table sizes are marked)
| poller / endpoint | calls/day | rows per D1-reaching call | est. rows/day (worst realistic) |
|---|---|---|---|
| interpret queue (one loop) | 144-960 | empty ~0-1; with work <= ~40 (limit 20); before: 2N per call | <= 40 k with work on every poll; < 1 k typical (before: 960 x 2N, 960 k at N = 500) |
| webjobs bridge `GET /api/jobs?status=pending` | 144-1,440 | typically < 20, <= 200 | ~30 k |
| linguistic registry (L rows; ~1 row per span) | <= 2 rebuilds/day | L (unknown, grows with the interpret container; 20 k assumed) | ~40 k (before: up to ~1,000 calls/day x L) |
| coverage (mission stats + COUNTs) | <= 6 rebuilds/day | ~10 k assumed (excludes learned_blends) | ~60 k |
| mission (stats + distinct aspects) | <= 4 + 4 rebuilds/day | ~5 k + ~3 k assumed | ~32 k |
| true totals | <= 2 rebuilds/day | ~20 small COUNTs, assumed ~30 k total | ~60 k |
| learned_blends COUNT | 1 per 7 days | ~300 k | ~45 k |
| `/api/metrics` | 96 + 4 rebuilds/day | ~60 rows + completed jobs (assumed 5 k) | ~26 k |
| `/api/loop/progress`, `/api/loop/status`, `jobs?status=completed` | user driven | <= ~60 | < 10 k |
| **Total** | | | **~350 k/day (< 500 k target, 7 % of the 5 M free tier)** |

Rows marked "assumed" are the main uncertainty; re-measure after the quota resets (8 PM ET) via the D1 analytics dashboard. If the real linguistic or coverage tables are 5x larger the total is still < 1 M/day.
