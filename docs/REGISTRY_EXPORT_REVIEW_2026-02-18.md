# Registry export review — motion-registries-2026-02-18.json

Review of patterns in the JSON export and how they align with the mission: **100% precision**, **comprehensive data acquisition** (every combination of origin/primitive values), and **robust prompt interpretation**.

---

## 1. Interpretation registry — ensure the loop is working

**Observation:** Every interpretation entry had `updated_at` on **2026-02-12**; export 2026-02-18. So no new interpretations were being stored. Railway logs showed no mention of `/api/interpretations` (only `/api/knowledge/discoveries` timeouts).

**Changes made:**

- **automate_loop** now **logs** before and after POST /api/interpretations: `INFO: POST /api/interpretations (job_id=...)` and `INFO: Interpretation recorded (job_id=...)`. So in Railway you will see whether each run is posting and succeeding.
- Same POST now uses **timeout=30**, **max_retries=5**, **backoff_seconds=2.0** (aligned with learning) so transient failures are retried.

**If you still see no new rows:** (1) Confirm the main loop (automate_loop) is the process running on Railway, not only sound_loop. (2) Check logs for `Interpretation recorded` or `POST /api/interpretations failed`. (3) Optionally backfill from recent jobs: `python scripts/backfill_interpretations.py --api-base https://motion.productions --limit 100`.

---

## 2. Pure — Sound: four primitives; mesh discovers blends with depth %

**Clarification (mission):** There are **exactly four** sound origin primitives: **silence**, **rumble**, **tone**, **hiss**. The mesh does not “discover” the primitives themselves; it **uses** them to discover **new sound values** (blends) that are derived from primitives, with a **depth %** (how much each primitive contributes)—analogous to pure colors and their depth_breakdown vs the 16 color primitives. Each discovered sound entry is stored with `depth_breakdown` = `origin_noises` (weights) + `strength_pct` (depth %). **Depth %** for every discovered value measures how much each origin/primitive makes up that value; the mesh is a playground where primitives and discovered values blend for further discovery.

### 2b. Only rumble and silence in current export

**Observation:** All nine static sound discoveries in the export map to:

- **Rumble** (keys like `0.06_low_low`, `0.09_low_low`, …) — amplitude in 0.04–0.09, tone **low**.
- **Silence** (keys `0.0_silent_silent`, `0.0_silent`) — amplitude 0, tone **silent**.

There are **no** discoveries that map to primitives **tone** (mid) or **hiss** (high). So the mesh is not growing toward the full set of origin noises (silence, rumble, tone, hiss).

**Root cause:**

- **Procedural audio** (`_generate_procedural_audio` in `src/audio/sound.py`) uses a single **Sine** at a mood-dependent frequency. All mood frequencies are **below 200 Hz** (44–165 Hz). So the dominant frequency in the WAV is always in the **low** band.
- **Extraction** (`_extract_audio_segments` in `extractor_per_instance.py`) uses FFT peak frequency: &lt;200 Hz → `low` (rumble), 200–2000 → `mid` (tone), ≥2000 → `high` (hiss). With current procedural audio, we never get mid/high.
- **Sound loop** and any video-derived static sound therefore only ever see **low** or **silent** → only rumble and silence in the mesh.

**Recommendation:** In `_generate_procedural_audio`, add **mid** (e.g. 220–440 Hz) and **high** (e.g. 880–2000 Hz) components for some moods or as a random layer, so extraction can produce tone/hiss and the mesh can grow toward all four primitives.

---

## 3. Pure — Sound: standardized key and depth

**Done:** Static sound key is now **standardized** to `amplitude_tone_timbre` (timbre defaults to tone when missing). Every new entry from extraction or spec gets `depth_breakdown` from `compute_sound_depth`: **origin_noises** (primitive weights) + **strength_pct** (depth %). So we record origin noises and a depth % for each new sound value derived from primitives.

---

## 4. Pure — Colors: exactly 16 primitives; depth_breakdown must use only these

**Confirmed:** There are **exactly 16** color origin primitives (see `blend_depth.COLOR_ORIGIN_PRIMITIVES` and `NUM_COLOR_PRIMITIVES`). Static color depth_breakdown must use only these names (plus `opacity` for the opaque level). Python path already uses `compute_color_depth(r,g,b)` for static colors.

**Observation:** One export entry showed `"ocean": 52, "default": 48` in depth_breakdown—palette-like labels, not primitives. **Recommendation:** Run depth backfill so all static (and learned) colors get depth recomputed from RGB with `compute_color_depth`: `python scripts/backfill_registry_depths.py --api-base https://motion.productions` (and/or `--table static_colors`). Audit Worker paths that write static/learned color depth and ensure they never write non-primitive keys.

---

## 5. Blended dynamic: very high counts — mission alignment

**Observation:** Blended (learned) colors have huge counts (e.g. Flax 24,566; Soft 19,439). Same in other industries: a few values dominate.

**Why this does not mean the algorithms are wrong:**  
- The mission is to **document every combination** of origin/primitive values and give them authentic names. High counts on **some** combinations mean those combinations are chosen often (e.g. popular palettes or prompts). The algorithms are **recording** correctly; they are not failing to record.  
- **Coverage** (filling the mesh with every combination over time) is achieved by **exploration** (diverse prompts, underused/recent bias in the builder). High counts on a subset are expected; the system is designed to also favor lower-count and recent entries so discovery broadens.  
- **Precision** (learning POST success, discovery POST success) is separate: we want 100% of runs to be logged so diagnostics are accurate. That’s a matter of retries and no skipped code paths, not of changing how counts work.

**Recommendation:** Keep underused/recent bias and explore ratio; continue to run diverse prompts. Over time the mesh will fill with more combinations while some values remain high-count.

---

## 6. Non-semantic prompts/names — one script fixes both

**Yes, there is a script:** `python scripts/backfill_registry_names.py --api-base https://motion.productions` (use `--dry-run` first to preview). It calls **POST /api/registries/backfill-names**, which:

- Replaces gibberish/inauthentic **registry names** (static_colors, static_sound, learned_*, narrative_entries, etc.) with semantic ones.
- **Cascades** the old→new name into: **learning_runs.prompt**, **interpretations.prompt** and **instruction_json**, **jobs.prompt**, learned_blends (source_prompt, inputs_json, output_json, primitive_depths_json), and all **sources_json** columns.

So one run updates both registry names and prompts that reference those names. No new prompts are added to the interpretation/linguistic registry by this script—that growth comes from the main loop (POST /api/interpretations) and interpret worker. If videos in the UI already show better, more semantic prompts, interpretation is working locally; ensuring the main loop POSTs successfully (and logs “Interpretation recorded”) will make the interpretation registry grow again.

---

## 7. Precision 100% — every run must be logged

**Goal:** Precision at 100% with respect to the mission: every completed run that should count must have **POST /api/learning** (and discovery) succeed so the system accurately reflects progress toward “every combination of origin/primitive values documented.”

**Observation:** precision_pct **85** (target 95) means ~15% of runs are missing a learning row (timeout, 429/503, or code path skipped).

**Checklist:**

1. **automate_loop** (Railway): After upload, it does POST /api/learning with `job_id`, with **5 retries** and 2s backoff, timeout 45s. No other code path should complete a run without calling this when learning is intended.
2. **Interpretation:** Same loop now logs `POST /api/interpretations` and “Interpretation recorded” with 30s timeout and 5 retries, so you can confirm in Railway logs that interpretations are being stored.
3. **Backfill (optional):** For jobs that completed but have no `learning_runs` row, a backfill script can POST /api/learning with job_id and minimal spec/analysis so precision moves toward 100%.

---

## 8. Summary: patterns not fully aligned with mission

| Pattern | Issue | Action |
|--------|--------|--------|
| Interpretation registry | No new rows | Log + retry for POST /api/interpretations in automate_loop; check Railway for "Interpretation recorded"; backfill if needed |
| Pure sound (4 primitives) | Only rumble + silence in export | Add mid/high in procedural audio; key standardized to amplitude_tone_timbre; depth = origin_noises + strength_pct |
| Static color depth | 16 primitives only | NUM_COLOR_PRIMITIVES asserted; run backfill_registry_depths for any non-primitive depth_breakdown |
| Gibberish names | Non-semantic names/prompts | Run backfill_registry_names (cascades to interpretations, jobs, learning_runs, sources_json) |
| Precision 100% | Learning missing for ~15% runs | Learning POST has 5 retries; ensure no path skips it; optional backfill for missing learning_runs |

---

## 9. References

- **Mission:** REGISTRY_REVIEW_AND_IMPROVEMENT_PLAN.md (§ Refined mission), MISSION_AND_STRATEGIC_OPTIMIZATIONS.md
- **Sound extraction:** `src/knowledge/extractor_per_instance.py` (`_extract_audio_segments`, FFT tone), `src/audio/sound.py` (`_generate_procedural_audio`, mood_config frequencies)
- **Interpretation:** `scripts/automate_loop.py` (POST /api/interpretations after each run), interpret_loop.py, Worker POST /api/interpretations
- **Naming:** scripts/backfill_registry_names.py, PRECISION_VERIFICATION_CHECKLIST.md
