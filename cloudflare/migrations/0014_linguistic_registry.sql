-- Linguistic registry: learned mappings from user phrasing to canonical values
-- Enables interpretation workflow to learn synonyms, slang, dialect, paraphrases
-- so the system can handle "anything and everything" from users

CREATE TABLE IF NOT EXISTS linguistic_registry (
  id TEXT PRIMARY KEY,
  span TEXT NOT NULL,           -- user phrase/word (e.g. "lit", "chill", "colour")
  canonical TEXT NOT NULL,      -- resolved value (e.g. "bright", "slow", "ocean")
  domain TEXT NOT NULL,         -- palette | motion | lighting | genre | gradient | camera | etc.
  variant_type TEXT NOT NULL DEFAULT 'synonym',  -- synonym | slang | dialect | paraphrase
  count INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_linguistic_registry_span_domain ON linguistic_registry(span, domain);
CREATE INDEX IF NOT EXISTS idx_linguistic_registry_domain ON linguistic_registry(domain);
CREATE INDEX IF NOT EXISTS idx_linguistic_registry_canonical ON linguistic_registry(canonical);
