-- Learning runs: one row per generation logged for learning (prompt, spec, analysis)
-- Powers "learn through user experience" — aggregated for palette/keyword tuning
CREATE TABLE IF NOT EXISTS learning_runs (
  id TEXT PRIMARY KEY,
  job_id TEXT,
  prompt TEXT NOT NULL,
  spec_json TEXT NOT NULL,
  analysis_json TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (job_id) REFERENCES jobs(id)
);

CREATE INDEX IF NOT EXISTS idx_learning_runs_job_id ON learning_runs(job_id);
CREATE INDEX IF NOT EXISTS idx_learning_runs_created_at ON learning_runs(created_at);
