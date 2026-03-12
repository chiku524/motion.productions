-- Part 4/6 of depth_breakdown (split to avoid D1 CPU limit 7429)
ALTER TABLE learned_audio_semantic ADD COLUMN depth_breakdown_json TEXT;
