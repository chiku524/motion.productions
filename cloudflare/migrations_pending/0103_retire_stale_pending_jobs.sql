-- NOT APPLIED. Optional one-time cleanup. Read migrations_pending/README.md first.
--
-- Retires stale loop-created jobs that were never claimed, so they stop sitting at the low rowids of the pending set.
-- Non-destructive: rows are marked status='abandoned' (the Worker retention job may delete them later), nothing is deleted.
-- Web jobs (workflow_type NULL or 'web') are never touched. Only jobs older than 1 day are retired.
--
-- Write budget per run: each updated row = 1 table write + 2 index writes (idx_jobs_status delete + insert) = ~3 writes,
-- so 1500 rows ~ 4,500 writes (< 5,000; free tier = 100,000 writes/day).
-- Read budget per run: <= 1500 matching rows + the pending rows walked to find them (a few thousand; ~31k on the first run
-- if the backlog is that large and is mostly younger than a day). Run AFTER the 00:00 UTC (8 PM ET) quota reset.
--
-- Run repeatedly, one run per statement execution, until "changes": 0 (check meta.changes in the wrangler output):
--   npx wrangler d1 execute motion-productions-db --remote --file migrations_pending/0103_retire_stale_pending_jobs.sql
-- Not a migration: do not move it into migrations/.
UPDATE jobs
SET status = 'abandoned', updated_at = datetime('now')
WHERE rowid IN (
  SELECT rowid FROM jobs
  WHERE status = 'pending'
    AND workflow_type IS NOT NULL AND workflow_type <> 'web'
    AND created_at < datetime('now', '-1 day')
  ORDER BY rowid
  LIMIT 1500
);
