# 0103 stale-job retire: Docker service and cutover

`scripts/retire_stale_jobs.py` ports `C:\Users\chiku\d1-audit\run-0103-batch.ps1` into the motion-local stack as
the compose service `retire-0103` (profile `retire`). It is off by default.

## Guards (checked before every batch, as in the .ps1)
- At most 2 batches and 10,000 writes per UTC day (`knowledge/write_budget/0103-state.json`).
- Loops' projected UTC-day writes (shared ledger, capped at 50k) + 20k reserve + today's 0103 writes + 4.5k must be <= 95k.
  An unreadable ledger counts as the full 50k (fail closed).
- A D1 Time Travel bookmark is fetched and logged before each batch. No bookmark means no batch.
- A batch that changes 0 rows marks it done. After that, the service idles.
- Not ported: the `wrangler d1 info rows_written_24h` check. The REST API has no equivalent, and it reported 0 anyway.
- Runs at 00:30 and 12:30 UTC, the same times as the Windows tasks (8:30 PM and 8:30 AM ET).

## Needs (in .env, never printed)
- `CLOUDFLARE_ACCOUNT_ID`
- `D1_DATABASE_ID` (motion-productions-db)
- `CLOUDFLARE_D1_TOKEN`: an API token with **D1 Edit** only
- `RETIRE_0103_ENABLED=1`

## Cutover (after this branch is merged)
1. Copy the state so the daily counters carry over:
   `copy C:\Users\chiku\d1-audit\out\0103-state.json knowledge\write_budget\0103-state.json`
2. Disable the Windows tasks first, so the two never run on the same day:
   `schtasks /Change /TN motion-0103-retire /DISABLE` and `schtasks /Change /TN motion-0103-retire-2 /DISABLE`
3. Dry run: `docker compose -f docker-compose.local.yml -p motion-local --profile retire run --rm retire-0103 python scripts/retire_stale_jobs.py --dry-run`
4. Start it: `docker compose -f docker-compose.local.yml -p motion-local --profile retire up -d retire-0103`
5. Once the log says `backlog cleared`, stop the service and delete the Windows tasks.
