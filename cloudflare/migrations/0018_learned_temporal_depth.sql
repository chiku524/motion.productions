-- learned_dynamic_meta is created at runtime by the Worker (ensureLearnedDynamicMetaTable) so remote
-- `wrangler d1 migrations apply` / import does not hit D1 CPU limit 7429 on very large databases.
-- This file remains for migration ordering and marking 0018 applied.
SELECT 1;
