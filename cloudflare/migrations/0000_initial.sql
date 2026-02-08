-- Jobs: one row per generation (prompt, status, optional R2 key for completed video)
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  prompt TEXT NOT NULL,
  duration_seconds REAL,
  status TEXT NOT NULL DEFAULT 'pending',
  r2_key TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at);
