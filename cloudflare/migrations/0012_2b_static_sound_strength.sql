-- Part 2b/6 of depth_breakdown (split to avoid D1 CPU limit 7429)
ALTER TABLE static_sound ADD COLUMN IF NOT EXISTS strength_pct REAL;
