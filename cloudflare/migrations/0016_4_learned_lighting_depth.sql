-- Part 4/4 of dynamic depth_breakdown (split to avoid D1 CPU limit 7429)
ALTER TABLE learned_lighting ADD COLUMN IF NOT EXISTS depth_breakdown_json TEXT;
