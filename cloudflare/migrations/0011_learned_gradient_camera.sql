-- Per-window extracted gradient and camera (dynamic registry in D1)
CREATE TABLE IF NOT EXISTS learned_gradient (
  id TEXT PRIMARY KEY,
  profile_key TEXT NOT NULL UNIQUE,
  gradient_type TEXT NOT NULL,
  strength REAL,
  count INTEGER NOT NULL DEFAULT 1,
  sources_json TEXT,
  name TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_learned_gradient_key ON learned_gradient(profile_key);

CREATE TABLE IF NOT EXISTS learned_camera (
  id TEXT PRIMARY KEY,
  profile_key TEXT NOT NULL UNIQUE,
  motion_type TEXT NOT NULL,
  speed TEXT,
  count INTEGER NOT NULL DEFAULT 1,
  sources_json TEXT,
  name TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_learned_camera_key ON learned_camera(profile_key);
