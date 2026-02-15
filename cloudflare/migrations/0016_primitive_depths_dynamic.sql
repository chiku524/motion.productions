-- Per-instance depth_breakdown for dynamic aspects (motion, gradient, camera, lighting)
-- Aligns with REGISTRY_FOUNDATION: every non-pure element records depth_breakdown.

ALTER TABLE learned_motion ADD COLUMN depth_breakdown_json TEXT;
ALTER TABLE learned_gradient ADD COLUMN depth_breakdown_json TEXT;
ALTER TABLE learned_camera ADD COLUMN depth_breakdown_json TEXT;
ALTER TABLE learned_lighting ADD COLUMN depth_breakdown_json TEXT;
