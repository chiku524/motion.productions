-- Learned knowledge: blends, colors, motion, lighting, etc. — persisted to D1
-- Powers the intended loop: discoveries documented and recorded securely

-- Blends: every recorded blend with name and primitive_depths
CREATE TABLE IF NOT EXISTS learned_blends (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  domain TEXT NOT NULL,
  inputs_json TEXT NOT NULL,
  output_json TEXT NOT NULL,
  primitive_depths_json TEXT,
  source_prompt TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_learned_blends_domain ON learned_blends(domain);
CREATE INDEX IF NOT EXISTS idx_learned_blends_created_at ON learned_blends(created_at);

-- Colors: key -> r,g,b, count, name
CREATE TABLE IF NOT EXISTS learned_colors (
  id TEXT PRIMARY KEY,
  color_key TEXT NOT NULL UNIQUE,
  r REAL NOT NULL,
  g REAL NOT NULL,
  b REAL NOT NULL,
  count INTEGER NOT NULL DEFAULT 1,
  sources_json TEXT,
  name TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_learned_colors_key ON learned_colors(color_key);

-- Motion profiles
CREATE TABLE IF NOT EXISTS learned_motion (
  id TEXT PRIMARY KEY,
  profile_key TEXT NOT NULL UNIQUE,
  motion_level REAL NOT NULL,
  motion_std REAL NOT NULL,
  motion_trend TEXT NOT NULL,
  count INTEGER NOT NULL DEFAULT 1,
  sources_json TEXT,
  name TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_learned_motion_key ON learned_motion(profile_key);

-- Lighting profiles
CREATE TABLE IF NOT EXISTS learned_lighting (
  id TEXT PRIMARY KEY,
  profile_key TEXT NOT NULL UNIQUE,
  brightness REAL NOT NULL,
  contrast REAL NOT NULL,
  saturation REAL NOT NULL,
  count INTEGER NOT NULL DEFAULT 1,
  sources_json TEXT,
  name TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_learned_lighting_key ON learned_lighting(profile_key);

-- Composition profiles
CREATE TABLE IF NOT EXISTS learned_composition (
  id TEXT PRIMARY KEY,
  profile_key TEXT NOT NULL UNIQUE,
  center_x REAL NOT NULL,
  center_y REAL NOT NULL,
  luminance_balance REAL NOT NULL,
  count INTEGER NOT NULL DEFAULT 1,
  sources_json TEXT,
  name TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_learned_composition_key ON learned_composition(profile_key);

-- Graphics profiles
CREATE TABLE IF NOT EXISTS learned_graphics (
  id TEXT PRIMARY KEY,
  profile_key TEXT NOT NULL UNIQUE,
  edge_density REAL NOT NULL,
  spatial_variance REAL NOT NULL,
  busyness REAL NOT NULL,
  count INTEGER NOT NULL DEFAULT 1,
  sources_json TEXT,
  name TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_learned_graphics_key ON learned_graphics(profile_key);

-- Temporal profiles
CREATE TABLE IF NOT EXISTS learned_temporal (
  id TEXT PRIMARY KEY,
  profile_key TEXT NOT NULL UNIQUE,
  duration REAL NOT NULL,
  motion_trend TEXT NOT NULL,
  count INTEGER NOT NULL DEFAULT 1,
  sources_json TEXT,
  name TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_learned_temporal_key ON learned_temporal(profile_key);

-- Technical profiles
CREATE TABLE IF NOT EXISTS learned_technical (
  id TEXT PRIMARY KEY,
  profile_key TEXT NOT NULL UNIQUE,
  width INTEGER NOT NULL,
  height INTEGER NOT NULL,
  fps REAL NOT NULL,
  count INTEGER NOT NULL DEFAULT 1,
  sources_json TEXT,
  name TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_learned_technical_key ON learned_technical(profile_key);

-- Name reserve: used names (for uniqueness checks)
CREATE TABLE IF NOT EXISTS name_reserve (
  name TEXT PRIMARY KEY,
  used_at TEXT NOT NULL DEFAULT (datetime('now'))
);
