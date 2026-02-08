-- User interaction events: every meaningful action for learning
CREATE TABLE IF NOT EXISTS events (
  id TEXT PRIMARY KEY,
  event_type TEXT NOT NULL,
  job_id TEXT,
  payload_json TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (job_id) REFERENCES jobs(id)
);

CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_job_id ON events(job_id);
CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at);

-- Feedback: explicit ratings on completed videos
CREATE TABLE IF NOT EXISTS feedback (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL UNIQUE,
  rating INTEGER NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (job_id) REFERENCES jobs(id)
);

CREATE INDEX IF NOT EXISTS idx_feedback_job_id ON feedback(job_id);
CREATE INDEX IF NOT EXISTS idx_feedback_rating ON feedback(rating);
