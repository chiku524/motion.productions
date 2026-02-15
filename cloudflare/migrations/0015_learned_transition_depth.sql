-- Per-window extracted transition and depth (dynamic registry in D1)
-- Aligns Worker discoveries handler with Python post_dynamic_discoveries (transition, depth).

CREATE TABLE IF NOT EXISTS learned_transition (
  id TEXT PRIMARY KEY,
  profile_key TEXT NOT NULL UNIQUE,
  type TEXT NOT NULL,
  duration_seconds REAL,
  count INTEGER NOT NULL DEFAULT 1,
  sources_json TEXT,
  name TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_learned_transition_key ON learned_transition(profile_key);

CREATE TABLE IF NOT EXISTS learned_depth (
  id TEXT PRIMARY KEY,
  profile_key TEXT NOT NULL UNIQUE,
  parallax_strength REAL,
  layer_count INTEGER,
  count INTEGER NOT NULL DEFAULT 1,
  sources_json TEXT,
  name TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_learned_depth_key ON learned_depth(profile_key);
