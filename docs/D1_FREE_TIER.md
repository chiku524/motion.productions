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
