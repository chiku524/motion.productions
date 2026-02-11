-- User-prompt interpretation queue and results (no create/render).
-- Interpretation worker (Railway) polls queue, interprets, stores result here.
-- Main loop uses interpretation_prompts from GET /api/knowledge/for-creation.

CREATE TABLE IF NOT EXISTS interpretations (
  id TEXT PRIMARY KEY,
  prompt TEXT NOT NULL,
  instruction_json TEXT,
  source TEXT NOT NULL DEFAULT 'worker',
  status TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_interpretations_status ON interpretations(status);
CREATE INDEX IF NOT EXISTS idx_interpretations_updated_at ON interpretations(updated_at);
