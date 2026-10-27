-- NOT APPLIED. Optional; the Worker no longer needs these (see docs/D1_FREE_TIER.md, "Read-scan mitigations").
-- Do NOT run while the DB is over its 500 MB cap: each CREATE INDEX writes every row's index entry and adds storage.
CREATE INDEX IF NOT EXISTS idx_learned_blends_name ON learned_blends(name);
CREATE INDEX IF NOT EXISTS idx_interpretations_status_updated ON interpretations(status, updated_at);
