-- Async Video AI render jobs: recipe + MP4 live in R2 (prefix video-ai/jobs/); state in D1.
CREATE TABLE IF NOT EXISTS video_ai_jobs (
  id TEXT PRIMARY KEY,
  status TEXT NOT NULL,
  recipe_key TEXT NOT NULL,
  output_key TEXT NOT NULL,
  error TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_video_ai_jobs_status ON video_ai_jobs(status);
CREATE INDEX IF NOT EXISTS idx_video_ai_jobs_created ON video_ai_jobs(created_at);
