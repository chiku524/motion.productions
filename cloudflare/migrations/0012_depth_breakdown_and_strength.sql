-- depth_breakdown (Pure/Blended/Semantic) and strength_pct (Pure sound)
-- Aligns D1 with REGISTRY_FOUNDATION: every non-primitive has depth_breakdown;
-- static sound entries record strength_pct (actual sound noises + measurement).

-- Pure registry: static colors — store depth_breakdown (origin colors + opacity)
ALTER TABLE static_colors ADD COLUMN depth_breakdown_json TEXT;

-- Pure registry: static sound — store depth_breakdown (origin_noises + strength_pct) and strength_pct
ALTER TABLE static_sound ADD COLUMN depth_breakdown_json TEXT;
ALTER TABLE static_sound ADD COLUMN strength_pct REAL;

-- Semantic registry: narrative entries — optional depth_breakdown for elements
ALTER TABLE narrative_entries ADD COLUMN depth_breakdown_json TEXT;

-- Blended registry: learned_audio_semantic — depth_breakdown (role, mood, tempo, presence)
ALTER TABLE learned_audio_semantic ADD COLUMN depth_breakdown_json TEXT;
