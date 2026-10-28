-- 0101_color_coverage_chunks.sql  (APPLIED to remote D1 2026-10-27 via d1 execute; idempotent CREATE IF NOT EXISTS)
--
-- Exact 8-bit colour coverage ("color.L2.a20", 2^24 cells) as ONE ROW PER 64 KiB CHUNK, never one row per colour.
-- 32 chunks per space x (observed | verified | declared) bit planes in the same row: the whole registry is 32 rows.
--
-- * `id` is the rowid alias (INTEGER PRIMARY KEY = space_no * 1024 + chunk_idx), so there is NO secondary index
--   and an upsert is exactly 1 row written.
-- * BLOB = 65,536 bytes per plane (LSB-first bitset, bit i of the chunk = cell chunk_idx * 524288 + i).
-- * the *_n columns are popcounts maintained by the Worker so the coverage report reads counts only (never blobs).
-- Storage: 32 rows x <= 192 KiB = 6 MiB at most (~1.2% of the 500 MB D1 cap), constant, it never grows.
CREATE TABLE IF NOT EXISTS color_coverage_chunks (
  id INTEGER PRIMARY KEY,
  space_id TEXT NOT NULL,
  chunk_idx INTEGER NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  observed BLOB,
  verified BLOB,
  declared BLOB,
  observed_n INTEGER NOT NULL DEFAULT 0,
  verified_n INTEGER NOT NULL DEFAULT 0,
  declared_n INTEGER NOT NULL DEFAULT 0,
  covered_n INTEGER NOT NULL DEFAULT 0,
  declared_only_n INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);