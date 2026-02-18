-- Learned colors: store depth_breakdown vs pure (static) primitives (16 colors) — living plan Priority 1
ALTER TABLE learned_colors ADD COLUMN depth_breakdown_json TEXT;
