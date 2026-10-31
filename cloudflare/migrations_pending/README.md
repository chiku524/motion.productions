# Pending D1 migrations - NOT APPLIED

**`0100_drop_redundant_indexes.sql` was applied on 2026-10-31 and moved to `migrations/0024_drop_redundant_indexes.sql`** (idempotent `DROP INDEX IF EXISTS`). Nothing else in this folder has been run against the remote `motion-productions-db`, and it is deliberately **outside**
`cloudflare/migrations/` so `wrangler d1 migrations apply`, `npm run db:migrate`, CI and the test harness never pick it up.
The Worker code works without any of it.

| file | what | effect | risk |
|---|---|---|---|
| `0100_drop_redundant_indexes.sql` | drops 19 indexes that duplicate a UNIQUE constraint's auto-index (or are a prefix of another index) | saves 1 index write + its storage per insert/delete on those tables (e.g. 2 -> 1 index rows per registry insert) | none for correctness: SQLite already uses the UNIQUE auto-index for the same lookups; `DROP INDEX` is cheap but is still a schema write, run it when D1 writes are available |
| `0101_optional_read_indexes.sql` | optional `learned_blends(name)` and `interpretations(status, updated_at)` indexes | only useful if code goes back to name / updated_at lookups; the Worker now uses `name_reserve` (PK) and `ORDER BY rowid` | writes + storage on a DB that is over its cap: **do not apply** until space is reclaimed |
| `0102_pending_web_partial_index.sql` | partial index `idx_jobs_pending_web ON jobs(status) WHERE status='pending' AND (workflow_type IS NULL OR workflow_type='web')` | lets the claim query read ~LIMIT entries instead of walking every pending loop job; then set `JOBS_PARTIAL_INDEX=1` | **not needed** (the Worker's cursor scan already cuts reads >99%). Costs writes (1 per existing pending web job + 1 extra index write per later web-job insert/update/delete). Used **only** if the query's WHERE matches the index's WHERE exactly; `ON jobs(rowid) WHERE ...` is invalid SQLite |
| `0103_retire_stale_pending_jobs.sql` | one-time batched `UPDATE`: loop jobs (`workflow_type` not NULL/'web') pending > 1 day -> `status='abandoned'` | shrinks the pending set so even a cold cursor walk is cheap | **costs writes**: ~3 per row, 1,500 rows/run ~ 4.5k writes (repeat until `changes: 0`). Non-destructive (no DELETE), but run only after Nico approves and after the 8 PM ET quota reset |

To apply (only after Nico approves): `cd cloudflare; npx wrangler d1 execute motion-productions-db --remote --file migrations_pending/0100_drop_redundant_indexes.sql` (same for `0101_color_coverage_chunks.sql`)
and move the file into `migrations/` with the next free number (so migration history stays consistent).

## Not included on purpose
* `learned_blends` has no index on `name`. The Worker no longer probes it by name (it uses `name_reserve`, see `docs/D1_FREE_TIER.md`), so no index is needed.
* Dropping / recreating tables to reclaim space (free route: deletes cost writes, 1 GB of deletes is impractical). Unapproved.

## Sound v2 needs no migration
Sound v2 (`sound.L1`, 6,144 cells) is stored as ordinary `s2.AA-B-F-K-Z` rows in the existing `static_sound` table: the cell id (`sound.L1#NNNNN`) goes in `name`, and the evidence tier in `depth_breakdown_json.tier`. There is no new table or column, and no extra statement per upsert. v1 reads add `sound_key NOT LIKE 's2.%'`, which is evaluated on rows the existing scans already touch. If a dedicated `tier` column is ever wanted, draft it here first; it is not required.
