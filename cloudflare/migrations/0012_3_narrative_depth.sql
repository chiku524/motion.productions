-- Part 3/6 of depth_breakdown (split to avoid D1 CPU limit 7429)
ALTER TABLE narrative_entries ADD COLUMN IF NOT EXISTS depth_breakdown_json TEXT;
