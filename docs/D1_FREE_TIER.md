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
UPDATE of a non-indexed column = 1. `src/knowledge/write_budget.py` (`INSERT_ROWS`, `UPDATE_ROWS`, `estimate_rows`) encodes this.

| endpoint (client writer) | rows written per call | notes |
|---|---|---|
| `POST /api/knowledge/discoveries` (explorer, balanced, sound, webjobs, ...) | per **new** item: `static_colors` 8, `static_sound` 5, `learned_colors` 5, `learned_blends` 6 (row + 2 idx + `name_reserve` 2... blend repeat = 0), motion/lighting/profile 4, narrative 5; repeat key = 1 (`count = count + delta`); `+3` for `discovery_runs` when `job_id` is sent | batch dedupes by key; chunk <= `DISCOVERIES_MAX_ITEMS` (36) |
| `POST /api/linguistic-registry/batch` (interpret, loops) | new span 5, existing span **1** (single `db.batch` upsert, no SELECT) | `count` field sums coalesced bumps |
| `POST /api/linguistic-registry` (single) | new 5 / existing 1 + a SELECT | superseded by the batch route |
| `POST /api/interpretations/batch` (interpret) | 4 per new row (row + PK + `idx_status` + `idx_updated_at`) | |
| `POST /api/interpretations` , `PATCH /api/interpretations/:id` | 4 / 5 (status + `updated_at` indexed) | |
| `POST /api/jobs` | 5 (row + PK + 3 indexes) | |
| `POST /api/jobs/:id/complete`, `/upload` | 3 (status index delete+insert) | |
| `POST /api/learning` | 4 | |
| `POST /api/coverage/color` (survey `COLOR_SYNC=1`) | 4 per chunk, <= 32 chunks | |
| `POST /api/events` | 4 | |
| `POST /api/loop/state`, GET anything | **0** D1 rows (KV / reads) | a cold GET may write 1 row (retention marker), existing behaviour |

`name_reserve` (PK + 1 unique index = 2 rows) is added for every novel generated name; the estimate folds it into the per-table
numbers. Estimates are worst case (all items new). A Worker that reports `rows_written` in its JSON response (added in this
branch, additive) lets the client `settle()` the charge to the true figure; **until the Worker is deployed the worst-case
estimate stands**, which only makes the client more conservative.

### What the client does now
1. **Gate** (`src/api_client.py::api_request`, the single choke point for every container and endpoint): before any non-GET it
   `reserve()`s the estimated rows in the shared ledger. No allowance => `WriteBudgetSkipped` (HTTP 503 shape, never a retry,
   no network call). The loop keeps working locally.
2. **Ledger**: `ledger.json` + O_EXCL `ledger.lock` in `WRITE_BUDGET_DIR` (compose: `/app/knowledge/write_budget`, the shared bind
   mount). Per-container `used/posts/denied`, resets at 00:00 **UTC**. Fails closed if it cannot be read or locked.
3. **Split** of `D1_DAILY_WRITE_BUDGET` (default **70,000**; `0` disables): interpret 15 %, sound 10 %, explorer 30 %,
   balanced 30 %, everything else (webjobs, procedural-render, exploiter) a shared 5 % pool = 63,000 allotted, 10 % unallotted
   reserve, and the 30 k between 70 k and 100 k absorbs estimate error, web users and retention. Override with
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
metrics), and the projected total across all containers. `python scripts/write_budget_dryrun.py` simulates 10 minutes of
loop output for every container against a mock Worker (no network) and prints the projected rows/day under the budget.
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
