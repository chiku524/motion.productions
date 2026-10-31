-- 0104_axis_coverage.sql  (PENDING - not applied; needs Nico's approval)
--
-- Compact aggregates for the opacity plane and cross-axis pair coverage shown on the site.
-- ONE ROW PER AGGREGATE KEY, a fixed allow-list of 32 keys (16 opacity levels + opacity total + 15 axis pairs):
--
-- * `id` is the rowid alias (INTEGER PRIMARY KEY = position of the key in the Worker's AXES_KEYS list), so there is
--   NO secondary index and an upsert is exactly 1 row written.
-- * seen / universe are counts only (never the raw sets): seen is merged as max(existing, new) so several loop
--   containers can sync in any order.
-- Storage: 32 rows x ~100 bytes, constant. Cost: <= 32 rows written per sync (only changed keys), ~4 syncs/day.
CREATE TABLE IF NOT EXISTS axis_coverage (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,
  key TEXT NOT NULL,
  seen INTEGER NOT NULL DEFAULT 0,
  universe INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
