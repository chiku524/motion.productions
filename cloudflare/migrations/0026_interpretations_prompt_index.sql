-- Approved by Nico 2026-10-31 (was pending 0105). Lets the backfill-prompts IN-check seek by prompt instead of walking
-- every status='done' row (~4.8k rows read per 40-prompt chunk on 2026-10-31). One-time cost ~= one write per
-- interpretations row (~5k), then +1 index write per insert/delete. Reads per rebuild drop to ~O(prompts checked).
CREATE INDEX IF NOT EXISTS idx_interpretations_prompt ON interpretations(prompt);
