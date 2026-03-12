-- Part 1/6 of depth_breakdown (split to avoid D1 CPU limit 7429)
ALTER TABLE static_colors ADD COLUMN depth_breakdown_json TEXT;
