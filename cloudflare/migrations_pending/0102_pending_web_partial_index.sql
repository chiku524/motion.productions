-- NOT APPLIED. Optional. Read migrations_pending/README.md first.
--
-- Partial index for the "claimable pending web job" query (cloudflare/src/jobsClaim.ts PARTIAL_INDEX_SQL).
-- It indexes ONLY pending web/NULL jobs, so the poll reads ~LIMIT index entries regardless of how many loop jobs are pending.
--
-- !! SQLite uses a partial index ONLY when the query's WHERE implies the index's WHERE term-for-term. The query must contain
-- !! exactly:  status = 'pending' AND (workflow_type IS NULL OR workflow_type = 'web')
-- !! Any other shape (IN ('web'), COALESCE(...), a different literal) silently falls back to idx_jobs_status and the full walk.
-- !! (The first idea, `ON jobs(rowid) WHERE ...`, is invalid: SQLite rejects rowid as an indexed column. Index `status` instead;
-- !! the rowid is appended to every index entry automatically, so `ORDER BY rowid` still comes out of the index in order.)
--
-- Cost: one write per existing pending web/NULL job (a handful of rows) + one extra index write per later web job insert,
-- status change or delete. Cheap in rows, but it IS a schema write: run it only when D1 writes are available, and
-- only then set the Worker var JOBS_PARTIAL_INDEX=1 (until then the Worker uses the cursor-windowed scan and needs no index).
CREATE INDEX IF NOT EXISTS idx_jobs_pending_web
  ON jobs(status)
  WHERE status = 'pending' AND (workflow_type IS NULL OR workflow_type = 'web');
