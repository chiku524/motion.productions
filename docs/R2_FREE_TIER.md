# Cloudflare Free-tier budget (D1, KV, R2)

Everything here must fit the **Free** plan. Daily limits reset at **00:00 UTC** (8 PM ET / 7 PM EST).

| Service | Free limit | Where we spend it | Guard |
|---|---|---|---|
| D1 reads | 5M rows/day | registry reads, snapshot rebuilds | snapshot cache (soft TTL 15 min - 4 h), no scans on hot paths, no per-post invalidation |
| D1 writes | 100k rows/day | discoveries upserts (+ one row per index) | one batched upsert per POST, in-request dedupe, ~91-145 rows written per clip |
| KV writes | **1,000/day** (1 write/s/key) | durable stale copies, loop state, counts blob | `kvGate`, >= 30 min between persists, ~100-300/day expected |
| KV reads | 100k/day | cold-isolate snapshot fallback only | memory -> Cache API -> KV |
| R2 storage | 10 GB-month | `jobs/{id}/video.mp4`, video-ai recipes | upload cap, 8 GB budget, 7-day retention |
| R2 Class A | 1M/month | video put (+1 usage counter put), sweep list (1 per 1,000 objects) | loop clips not uploaded; list only from cron/admin/emergency |
| R2 Class B | 10M/month | usage counter get (memoised 60 s), downloads | no `head`/`list` on status paths |

## Phase 0 read/write reduction (Worker)

* **Snapshot cache** (`src/snapshotCache.ts`): isolate memory -> Cache API -> KV (rarely written). Single-flight rebuild,
  soft/hard TTL, rate-limited `?fresh=1`, stale-on-failure with `degraded: true`.
* **Discoveries writer** (`src/discoveryWriter.ts`): one table-driven `INSERT ... ON CONFLICT DO UPDATE ... RETURNING count`
  batch per POST; items deduped inside the request; names checked against the PK-indexed `name_reserve`.
  Max items per POST = `DISCOVERIES_MAX_ITEMS` (Worker default 40, clamp 3-80); the Python client sends 36.
* **No per-post cache invalidation** (`browseCache.invalidateRegistryReadCaches` is a no-op unless `{force:true}`).
* **KV write throttles** (`src/kvGate.ts`): loop state saved at most every 30 min per key; registry counts persisted at most every 30 min.
* **Graceful degradation** (`src/limits.ts`): a D1/KV limit error becomes `200 {degraded:true,error:"free_tier_limit",retry_after_ms:900000}`
  for GET/HEAD and `503` + `Retry-After: 900` for writes. The Python client does not retry these and pauses writes for
  `FREE_TIER_LIMIT_COOLDOWN_SECONDS` (default 900).

Measured on a local Miniflare Worker (`node scripts/measure-d1.mjs`, ~6.6k seeded rows), per clip:

| | before | after |
|---|---|---|
| POSTs per clip | 8 | 2 |
| D1 statements | 217-261 | 41-51 |
| D1 requests | 218-262 | 7-8 |
| rows read | 297k-377k | 64-110 |
| rows written | 91-149 | 91-145 |
| KV put/delete/get | 17/32/25 | 0/0/0 |

**Remaining ceiling:** rows written (~91-145/clip) is dominated by the real count upserts and their indexes, so the 100k/day
write cap allows roughly **700-1,000 clips/day**. Next step: aggregate known-key count bumps client-side (one `count += n` row per key per N clips).

## R2

Loop clips are deleted after discovery, so loops call `POST /api/jobs/{id}/complete` (marks the job done with
`r2_key = "skipped:no-upload"`, no R2 op). Set `LOOP_UPLOAD_VIDEOS=1` to upload them anyway (web jobs always upload).
At ~3 MB per clip, 5,760 clips/day would be ~17 GB/day, so uploading loop clips can never fit the free tier.

Worker env (all optional, wrangler `vars`):

| Var | Default | Meaning |
|---|---|---|
| `R2_MAX_UPLOAD_BYTES` | 25 MB | larger uploads -> `413` (checked from `Content-Length` before reading the body) |
| `R2_BUDGET_BYTES` | 8,000,000,000 | uploads that would exceed it -> one emergency sweep, then `507` |
| `R2_RETENTION_DAYS` | 7 | objects older than this are deleted by the sweep |

Usage is tracked in one object, `_meta/usage.json` (no list on the upload path). A daily cron (`17 9 * * *` UTC) and
`POST /api/admin/r2/sweep` list the bucket (1 Class A per 1,000 objects, max 60 pages), delete expired objects, then evict
oldest-first to 80% of the budget, and re-measure usage. `GET /api/admin/r2/usage` shows usage, config and headroom.
Emergency sweeps are limited to one per 10 minutes. Video-ai recipe bodies are capped at 512 KB.
Deletes are free; the sweep itself costs a handful of Class A ops per day.

## Tests

`cd cloudflare && npm test` (Miniflare harness in `test/helpers/harness.mjs`: `phase0`, `r2Limits`, `snapshotCache`) and
`pytest tests/test_free_tier_limits.py`.