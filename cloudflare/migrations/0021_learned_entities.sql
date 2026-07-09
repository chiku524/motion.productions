-- Blended registry: stylized scene entities (circle/rect/arrow/character profiles)
CREATE TABLE IF NOT EXISTS learned_entities (
  id TEXT PRIMARY KEY,
  profile_key TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL,
  trajectory TEXT,
  bounce INTEGER NOT NULL DEFAULT 0,
  color_hint TEXT,
  label TEXT,
  directionality TEXT,
  count INTEGER NOT NULL DEFAULT 1,
  sources_json TEXT,
  name TEXT,
  entity_json TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_learned_entities_key ON learned_entities(profile_key);
CREATE INDEX IF NOT EXISTS idx_learned_entities_kind ON learned_entities(kind);
