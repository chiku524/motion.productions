-- Narrative registry: themes, plots, settings, genre, mood, scene_type (film aspects)
-- One table for all aspects; aspect column distinguishes genre, mood, plots, settings, themes, scene_type.

CREATE TABLE IF NOT EXISTS narrative_entries (
  id TEXT PRIMARY KEY,
  aspect TEXT NOT NULL,
  entry_key TEXT NOT NULL,
  value TEXT,
  count INTEGER NOT NULL DEFAULT 1,
  sources_json TEXT,
  name TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(aspect, entry_key)
);
CREATE INDEX IF NOT EXISTS idx_narrative_entries_aspect_key ON narrative_entries(aspect, entry_key);
CREATE INDEX IF NOT EXISTS idx_narrative_entries_created_at ON narrative_entries(created_at);
