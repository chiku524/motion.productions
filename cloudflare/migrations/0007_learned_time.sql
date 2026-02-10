-- Per-window time (duration, rate) — dynamic registry in D1
CREATE TABLE IF NOT EXISTS learned_time (
  id TEXT PRIMARY KEY,
  profile_key TEXT NOT NULL UNIQUE,
  duration REAL NOT NULL,
  fps REAL NOT NULL,
  count INTEGER NOT NULL DEFAULT 1,
  sources_json TEXT,
  name TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_learned_time_key ON learned_time(profile_key);
