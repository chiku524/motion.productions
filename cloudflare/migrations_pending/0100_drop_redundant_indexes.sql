-- NOT APPLIED. See README.md in this folder.
-- Each index below duplicates the auto-index SQLite builds for a UNIQUE constraint on the same column(s),
-- or is a strict prefix of another index. Dropping them removes one index write per insert/update/delete.
DROP INDEX IF EXISTS idx_learned_colors_key;
DROP INDEX IF EXISTS idx_learned_motion_key;
DROP INDEX IF EXISTS idx_learned_lighting_key;
DROP INDEX IF EXISTS idx_learned_composition_key;
DROP INDEX IF EXISTS idx_learned_graphics_key;
DROP INDEX IF EXISTS idx_learned_temporal_key;
DROP INDEX IF EXISTS idx_learned_technical_key;
DROP INDEX IF EXISTS idx_learned_audio_semantic_key;
DROP INDEX IF EXISTS idx_learned_time_key;
DROP INDEX IF EXISTS idx_learned_gradient_key;
DROP INDEX IF EXISTS idx_learned_camera_key;
DROP INDEX IF EXISTS idx_learned_transition_key;
DROP INDEX IF EXISTS idx_learned_depth_key;
DROP INDEX IF EXISTS idx_learned_entities_key;
DROP INDEX IF EXISTS idx_static_colors_key;
DROP INDEX IF EXISTS idx_static_sound_key;
DROP INDEX IF EXISTS idx_narrative_entries_aspect_key;
DROP INDEX IF EXISTS idx_feedback_job_id;
-- prefix of idx_static_colors_family_shade(family, shade)
DROP INDEX IF EXISTS idx_static_colors_family;
-- NOTE: idx_learned_colors_key above is only valid while learned_colors still exists with UNIQUE(color_key).