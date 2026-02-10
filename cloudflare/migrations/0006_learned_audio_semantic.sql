-- Semantic audio (music, melody, dialogue, sfx) per window — dynamic registry in D1
CREATE TABLE IF NOT EXISTS learned_audio_semantic (
  id TEXT PRIMARY KEY,
  profile_key TEXT NOT NULL UNIQUE,
  role TEXT NOT NULL,
  count INTEGER NOT NULL DEFAULT 1,
  sources_json TEXT,
  name TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_learned_audio_semantic_key ON learned_audio_semantic(profile_key);
