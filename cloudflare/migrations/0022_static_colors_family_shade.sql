-- Hue-family / shade indexes for public registry explorer browse filters.
ALTER TABLE static_colors ADD COLUMN family TEXT;
ALTER TABLE static_colors ADD COLUMN shade TEXT;
CREATE INDEX IF NOT EXISTS idx_static_colors_family ON static_colors(family);
CREATE INDEX IF NOT EXISTS idx_static_colors_family_shade ON static_colors(family, shade);
