-- Part 1/4 of dynamic depth_breakdown (split to avoid D1 CPU limit 7429)
ALTER TABLE learned_motion ADD COLUMN depth_breakdown_json TEXT;
