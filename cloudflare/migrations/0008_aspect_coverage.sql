-- Full aspect coverage: static color sub-aspects + motion direction/rhythm

-- Static colors: luminance, chroma, opacity (align with doc sub-aspects)
ALTER TABLE static_colors ADD COLUMN luminance REAL;
ALTER TABLE static_colors ADD COLUMN chroma REAL;
ALTER TABLE static_colors ADD COLUMN opacity REAL;

-- Learned motion: direction, rhythm (motion sub-aspects)
ALTER TABLE learned_motion ADD COLUMN motion_direction TEXT;
ALTER TABLE learned_motion ADD COLUMN motion_rhythm TEXT;
