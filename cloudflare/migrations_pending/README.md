# Pending D1 migrations - NOT APPLIED

Nothing in this folder has been run against the remote `motion-productions-db`, and it is deliberately **outside**
`cloudflare/migrations/` so `wrangler d1 migrations apply`, `npm run db:migrate`, CI and the test harness never pick it up.
The Worker code works without any of it.

| file | what | effect | risk |
|---|---|---|---|
| `0100_drop_redundant_indexes.sql` | drops 19 indexes that duplicate a UNIQUE constraint's auto-index (or are a prefix of another index) | saves 1 index write + its storage per insert/delete on those tables (e.g. 2 -> 1 index rows per registry insert) | none for correctness: SQLite already uses the UNIQUE auto-index for the same lookups; `DROP INDEX` is cheap but is still a schema write, run it when D1 writes are available |

To apply (only after Nico approves): `cd cloudflare; npx wrangler d1 execute motion-productions-db --remote --file migrations_pending/0100_drop_redundant_indexes.sql`
and move the file into `migrations/` with the next free number (so migration history stays consistent).

## Not included on purpose
* `learned_blends` has no index on `name`, yet `naming.ts` / `registries.ts` run `WHERE name = ?` against it. On a table this big
  that is a full scan per lookup (read-quota burner). An index would cost storage; decide after measuring (see `docs/D1_FREE_TIER.md`).
* Dropping / recreating tables to reclaim space (free route: deletes cost writes, 1 GB of deletes is impractical). Unapproved.