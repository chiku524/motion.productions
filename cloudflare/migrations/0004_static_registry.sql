-- Static registry: one frame = one instance (color, sound per frame)
-- Clean separation from learned_* (dynamic / whole-video). Use for per-frame discoveries.

-- Static colors: per-frame color entries (dominant RGB + derived values)
CREATE TABLE IF NOT EXISTS static_colors (
  id TEXT PRIMARY KEY,
  color_key TEXT NOT NULL UNIQUE,
  r REAL NOT NULL,
  g REAL NOT NULL,
  b REAL NOT NULL,
  brightness REAL,
  contrast REAL,
  saturation REAL,
  hue REAL,
  color_variance REAL,
  count INTEGER NOT NULL DEFAULT 1,
  sources_json TEXT,
  name TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_static_colors_key ON static_colors(color_key);
CREATE INDEX IF NOT EXISTS idx_static_colors_created_at ON static_colors(created_at);

-- Static sound: per-frame/sample sound entries (amplitude, tone, timbre)
-- Placeholder until per-frame audio extraction is implemented
CREATE TABLE IF NOT EXISTS static_sound (
  id TEXT PRIMARY KEY,
  sound_key TEXT NOT NULL UNIQUE,
  amplitude REAL,
  weight REAL,
  tone TEXT,
  timbre TEXT,
  count INTEGER NOT NULL DEFAULT 1,
  sources_json TEXT,
  name TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_static_sound_key ON static_sound(sound_key);
CREATE INDEX IF NOT EXISTS idx_static_sound_created_at ON static_sound(created_at);
