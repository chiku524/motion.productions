# Exact colour survey (stage 3)

Implements Phase 1 of `docs/EXHAUSTIVE_REGISTRY_PLAN.md`: record every exact 8-bit colour cell
(`color.L2.a20`, id = `(r<<16)|(g<<8)|b`, 16,777,216 cells) for later use in video generation.

## What exists

| Piece | File |
|---|---|
| 2 MiB-per-plane bitset store (observed / verified / declared), merge-safe across containers, seeded Feistel permutation, per-container stride queue | `src/knowledge/color_cells.py` |
| Tile layout and extraction (interior pixels only, margin 4 px) | `src/knowledge/color_tiles.py` |
| Survey clips, codec tolerance measurement, loop step, CLI | `src/knowledge/color_survey.py` |
| Free-tier sync client (change-detected, budgeted, backoff) | `src/knowledge/color_sync.py` |
| Worker endpoints | `cloudflare/src/routes/coverage.ts`, `cloudflare/src/colorCells.ts` |
| Table SQL (NOT applied) | `cloudflare/migrations_pending/0101_color_coverage_chunks.sql` |
| Targeting queue for the colour axis | `src/knowledge/mission_targets.py` (`LOOP_COLOR_QUEUE`) |
| Lookup for video generation | `src/knowledge/registry_lookup.py` |
| Report | `python -m src.knowledge.tier_report [--remote API_BASE]` |

## Decisions

### Survey clips skip the novelty gate and are never published
A survey clip is a grid of flat colour tiles. The content-novelty gate exists to stop the library filling with
near-duplicate creative clips; survey clips are the opposite (deliberately uniform instruments, not content), so
the gate would reject nearly all of them. They therefore:

- do not run the novelty gate and are not added to the novelty store,
- create no `/api/jobs` row and no `/api/learning` post,
- are never uploaded or published (R2 untouched),
- are deleted after decoding (only bits and a tiny ledger/attempt file survive),
- write nothing to D1 themselves. Only the bounded coverage sync below does, and only when enabled.

Creative clips are unchanged and still pass the gate.

### Codec: lossless for verification
Round-trip tolerance was measured by encoding known tile colours and decoding the clip:

| Profile | Encoder | Max error per channel | Mean | Exact tiles |
|---|---|---|---|---|
| `lossless` (default) | libx264rgb `-crf 0 -g 1` | **0** | 0 | 100% |
| `production` | libx264 quality 8, yuv420p | **4** (per channel 3/3/4) | 1.24 | 1.1% |

Consequences: through the production profile a decoded colour is only within +/-4 of the target, so an exact
claim is impossible. Survey clips use the lossless profile (tolerance 0). If `libx264rgb` is unavailable they fall
back to the production profile with tolerance 4. Tier semantics:

- the flat tile's decoded median is **exactly** the target: `verified` (the tolerance of a profile only decides
  whether a tile counts as flat; it is never accepted as "exact". Before 2026-10-28 a lossy fallback marked every target
  within +/-4 as verified, which claimed colours that were never decoded),
- decoded colour differs from the target: the decoded colour is marked `observed` (it really appeared), the target is not
  covered. On the lossless profile the target gets an attempt; on a lossy profile it does not (the codec, not the cell, is
  the reason, so nothing is quarantined),
- a target that fails 3 times on the lossless profile is quarantined (declared, skipped by the queue).

Only `verified` and `observed` count as coverage; `declared` never does.

### Work queue
`ColorWorkQueue` walks a seeded 6-round Feistel permutation of the 24-bit space. Worker `w` of `n` owns
positions `p % n == w`, so containers are disjoint without any shared state and without any D1 read. Identity
comes from `CONTAINER_INDEX` / `CONTAINER_COUNT`, else a hostname hash modulo `COLOR_WORKER_COUNT` (default 8; hash
collisions are harmless but may repeat work). Compose sets explorer = 0 and balanced = 1 of `COLOR_CONTAINER_COUNT`
(default 2). If you add a surveying container, raise the count for all of them together (changing the count
re-partitions positions; already-covered cells are simply skipped).

The colour axis of creative prompts uses the same queue when `LOOP_COLOR_QUEUE=1` (the family of the next
unseen cell in the stride). Without it, or if the queue fails, the previous weighted-random sampling is used.

## Audit of the "44 % after 74 clips" report (2026-10-28)
The 7.40 M / 16.78 M (44.1 %) figure is **correct**: the 74 clips of the live run are only that iteration's counter
(`summary["clips"]`). The store is cumulative: `knowledge/color_cells/ledger.jsonl` holds 1,208 survey clips from 2026-10-27
20:28 onwards (80 + 1,036 + 48 in the first three hours, then 44 on 10-28), each 6,144 distinct targets, 1,208 x 6,144 =
7,421,952 = the verified popcount (44.24 %), observed = 0, every clip lossless with max error 0. A clip takes ~0.22 s (24 frames of
512 x 512 libx264rgb), so a worker finishes ~1,000 clips an hour and the whole space needs ~2,731 clips (~10 CPU-minutes).
Checked: bits are set only by `record_outcome` from decoded tile medians (no neighbour/tolerance marking, no whole-batch marking,
`bits_set` uniques ids before OR; planes load zero-initialised; OR-merge and Worker counts are popcounts of the merged
planes, not summed deltas). What *was* wrong: (1) the lossy fallback verified colours that were not decoded exactly
(fixed, tests in `tests/test_color_survey.py`), (2) the loop log printed this iteration's clip count next to the cumulative
percentage, which read as "74 clips = 44 %" (the log now also prints `total_clips`, read from `totals.json`).

## Free-tier sync budget
Never one row per colour. The whole space is 32 chunks of 64 KiB per plane, so the table has at most 32 rows.

- At most **32 rows** per sync (`COLOR_SYNC_MAX_CHUNKS`), at most 8 chunks per request, so at most 4 requests.
- Due every 1 h (`COLOR_SYNC_INTERVAL_S`), or after 2000 survey clips (`COLOR_SYNC_EVERY_CLIPS`) with a 5 min
  minimum gap. Unchanged chunks (sha1 digest) are not sent. Containers share `sync_state.json` and a lock.
- Worst case: 32 row writes per sync, 24 syncs/day = 768 row writes/day, against 100k/day on D1 free. In
  practice far fewer (only changed chunks; the Worker skips writing an unchanged merge).
- Worker CPU: a request is capped at 8 chunks, zlib payloads, word-wise `Uint32` OR-merge.
- Backoff: 6 h when the table is missing, 24 h on a version mismatch, and the existing free-tier cooldown on
  limit/db-full responses. `COLOR_SYNC=0` disables. Compose ships with `COLOR_SYNC=0`.
- If the table is absent the Worker answers `table_missing` (no 500) and every GET degrades to empty counts.

## Enabling sync (needs Nico's approval, not done here)
1. Free space on `motion-productions-db` (it is over its size cap, so writes are blocked).
2. Apply `cloudflare/migrations_pending/0101_color_coverage_chunks.sql` (move it into `migrations/` as part of the
   normal migration flow).
3. Deploy the Worker, then start containers with `COLOR_SYNC=1`.

## Known limitations
- The Worker merge is read-OR-write, not a SQL-atomic OR; two racing syncs can lose an update. Mitigated by the
  shared sync lock, a full resend every 24 h, and the local store being the source of truth.
- D1 BLOB read-back (`number[]` vs `ArrayBuffer`) is handled defensively but was only tested on local Miniflare.
- No opacity plane yet (RGB only). Creative clips do not yet record exact colours opportunistically.
- Coverage is local per machine until synced; the bitsets live in the mounted `knowledge/` volume (git-ignored).

## Using the registry from video generation
```python
from src.knowledge.registry_lookup import RegistryLookup
reg = RegistryLookup.from_store()          # live local bitsets, no network
reg.tier("#ff8800")                        # 'verified' | 'observed' | 'declared' | 'none'
reg.is_recorded((255, 136, 0))             # observed or verified
reg.palette_coverage(frame_rgb)            # share of a frame's distinct colours that are recorded
reg.export_snapshot("registry.mpcs")       # compact checksummed snapshot for other machines
RegistryLookup.from_snapshot("registry.mpcs")
```
Remote: `GET /api/coverage/color/cell?id=N | rgb=r,g,b | hex=ff8800 | ids=a,b,c` (at most 64, cacheable 5 min) and
`GET /api/coverage/color[?chunks=1]` for counts. CLI: `python -m src.knowledge.registry_lookup "#ff8800" --export out.mpcs`.