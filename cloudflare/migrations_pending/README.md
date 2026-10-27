# Pending D1 migrations - NOT APPLIED

Nothing in this folder has been run against the remote `motion-productions-db`, and it is deliberately **outside**
`cloudflare/migrations/` so `wrangler d1 migrations apply`, `npm run db:migrate`, CI and the test harness never pick it up.
The Worker code works without any of it.

| file | what | effect | risk |
|---|---|---|---|
| `0100_drop_redundant_indexes.sql` | drops 19 indexes that duplicate a UNIQUE constraint's auto-index (or are a prefix of another index) | saves 1 index write + its storage per insert/delete on those tables (e.g. 2 -> 1 index rows per registry insert) | none for correctness: SQLite already uses the UNIQUE auto-index for the same lookups; `DROP INDEX` is cheap but is still a schema write, run it when D1 writes are available |

To apply (only after Nico approves): `cd cloudflare; npx wrangler d1 execute motion-productions-db --remote --file migrations_pending/0100_drop_redundant_indexes.sql` (same for `0101_color_coverage_chunks.sql`)
and move the file into `migrations/` with the next free number (so migration history stays consistent).

## Not included on purpose
* `learned_blends` has no index on `name`, yet `naming.ts` / `registries.ts` run `WHERE name = ?` against it. On a table this big
  that is a full scan per lookup (read-quota burner). An index would cost storage; decide after measuring (see `docs/D1_FREE_TIER.md`).
* Dropping / recreating tables to reclaim space (free route: deletes cost writes, 1 GB of deletes is impractical). Unapproved.
## Sound v2 needs no migration
Sound v2 (`sound.L1`, 6,144 cells) is stored as ordinary `s2.AA-B-F-K-Z` rows in the existing `static_sound` table: the cell id (`sound.L1#NNNNN`) goes in `name`, and the evidence tier in `depth_breakdown_json.tier`. There is no new table or column, and no extra statement per upsert. v1 reads add `sound_key NOT LIKE 's2.%'`, which is evaluated on rows the existing scans already touch. If a dedicated `tier` column is ever wanted, draft it here first; it is not required.