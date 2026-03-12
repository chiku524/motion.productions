# Registry JSON Review & Workflow Optimization

**Reviewed exports:** `motion-registries-2026-02-21.json`, `motion-registries-2026-03-12.json`  
**Note:** `motion-registries-2026-02-24.json` was not found in the workspace; analysis uses the two available exports.

**Goal:** Successfully complete each registry with all possible primitive + discovered values.

**Implementation status (post-enhancement):** All enhancements below have been implemented in code: full CSS color primitives (141), expanded sound primitives (34), expanded origins (narrative, audio mood, technical, etc.), depth_breakdown persisted for all dynamic discoveries, and full dynamic primitive seeding (motion, lighting, composition, time, temporal, technical, depth). The loop seeds primitives at start of each run via `grow_all_from_video()`.

**Next steps (run these):**
1. **Bootstrap registries (local + optional color sweep):**  
   `python scripts/registry_bootstrap.py`  
   Seeds all static and dynamic primitives. Add `--color-sweep` to also register an RGB grid; add `--api-base https://motion.productions` to POST novel discoveries to the API.
2. **Color sweep only (e.g. periodic):**  
   `python scripts/color_sweep.py --api-base https://motion.productions`  
   Use `--steps 6` (default, 216 cells) or `--steps 8` for denser grid; `--dry-run` to preview.
3. **Deploy and run the loop** so workers sync the new primitives and discoveries to the API; frame workers grow static, window workers grow dynamic + narrative.

---

## 1. Export comparison summary

| Aspect | 2026-02-21 | 2026-03-12 |
|--------|------------|------------|
| **Schema** | No `exported_schema_version` | `exported_schema_version: 2` |
| **Pure static color key** | `"100,100,150_1.0"` (RGB + opacity suffix) | `"100,100,150"` (RGB only; opacity separate or normalized) |
| **Registries** | pure_static, blended_dynamic, semantic_narrative, coverage_snapshot | Same + loop_progress |
| **Static color discoveries** | Many (e.g. Slate 129, Mist 122, Flint 102) | Same keys, higher counts (Slate 203, Mist 192, Flint 178) — growth confirmed |
| **Static sound** | Primitives (silence, rumble, tone, hiss) + discovered blends | Same; some discoveries with depth_breakdown (origin_noises); primitives show count 0 |
| **Blended dynamic** | canonical (gradient, camera, motion, sound) + discoveries (colors, motion, etc.) | Same; more camera_motion canonical values (roll, truck, pedestal, arc, tracking, birds_eye, whip_pan, rotate) |
| **Coverage snapshot (Mar 12)** | — | static_colors_coverage_pct: **1.35%**, narrative_min_coverage_pct: **100%**, static_sound_coverage_pct: **100%** |
| **Loop progress (Mar 12)** | — | total_runs 20, runs_with_learning 19, discovery_rate_pct 50, exploit_count 611, explore_count 4139 |

**Findings:**
- **Static colors** are growing (counts increased from Feb to Mar) but **coverage is very low (1.35%)** vs target (~28k cells or similar completion metric). Discovery is biased toward gray/teal/slate tones.
- **Static sound** reports 100% coverage (all four primitives present); discovered blends exist (e.g. 0.11_low_low, 0.3_mid_high) but primitives show count 0 in the export — acceptable if “coverage” means “all primitives seeded.”
- **Narrative** has 100% min coverage; many aspects have low-count or single-count entries (e.g. genre: ad, documentary, explainer, sci-fi, thriller, tutorial, vlog at 1). NARRATIVE_ORIGINS has more values than are well-represented.
- **Blended** has canonical gradient/camera/motion/sound and discoveries; some depth_breakdown inconsistencies (e.g. "ocean"/"default"/"opacity" in early Feb color depth vs primitive names in Mar).

---

## 2. Primitive vs discovered alignment

### 2.1 Color primitives

- **Export / API:** Exports show **16** color primitives (black, white, red, green, blue, yellow, cyan, magenta, orange, purple, pink, brown, navy, gray, olive, teal). This matches `blend_depth.COLOR_ORIGIN_PRIMITIVES` used for **depth_breakdown**.
- **Code:** `static_registry.STATIC_COLOR_PRIMITIVES` seeds **60+** colors (indigo, violet, coral, gold, forestgreen, etc.). Those are for **creation pool and variety**; depth is still computed against the 16 so exports stay consistent.
- **Gap:** Ensure the Worker/API “primitives” list used for coverage and for-creation matches the same 16 (or the full 60+ if you want coverage to reflect the larger set). Today, coverage at 1.35% suggests the denominator is large (e.g. ~28k cells); filling it requires more discovery, not more primitives in the export.

### 2.2 Sound primitives

- **Export:** Four primitives (silence, rumble, tone, hiss) with count 0 in the discoveries list; discovered entries use keys like `0.11_low_low` and depth_breakdown with `origin_noises`.
- **Code:** `STATIC_SOUND_PRIMITIVES` has 10 entries (silence + strength bands for rumble/tone/hiss); `SOUND_ORIGIN_PRIMITIVES` in blend_depth is the 4 names. Pure sound keys must use only primitive tones (low, mid, high, silent, neutral) per REGISTRY_FOUNDATION.
- **Gap:** No major mismatch. To “complete” pure sound: ensure every primitive has non-zero count over time (frame workers + sound_loop) and that discovered blends cover a wide range of amplitude/tone combinations.

### 2.3 Dynamic primitives

- **Gradient:** 4 (vertical, horizontal, radial, angled) — seeded and present in export.
- **Camera:** Origins list 16 motion_type values; export canonical lists 15 (including roll, truck, pedestal, arc, tracking, birds_eye, whip_pan, rotate). Ensure `ensure_dynamic_primitives_seeded` uses the full `CAMERA_ORIGINS["motion_type"]` so all 16 are seeded.
- **Transition:** cut, fade, dissolve, wipe — present.
- **Audio semantic:** presence values (silence, ambient, music, sfx, full) — present as canonical “sound” entries (tempo/mood/presence).

### 2.4 Narrative primitives

- **NARRATIVE_ORIGINS** (origins.py): genre (12), tone (10), style (5), tension_curve (4), settings (14), themes (14), scene_type (10). Export shows many of these but with uneven counts; some entry_key values are NARRATIVE_ORIGINS, others are discovered (e.g. “neon”, “golden_hour”).
- **Gap:** “Complete” = every NARRATIVE_ORIGINS value has at least one entry. Use **targeted narrative prompts** (§2.4) and coverage-driven prompt selection so low-count origins get more runs.

---

## 3. Workflow optimizations (to complete each registry)

### 3.1 Frame workers (Explorer + Exploiter)

- **LOOP_EXTRACTION_FOCUS=frame** — already in config; verify on deploy so only static (color + sound) is grown and posted.
- **Static color completion:**  
  - Run **color_sweep** periodically to batch-register RGB grid cells (scripts/color_sweep.py).  
  - Use **coverage-aware prompt selection**: when `static_colors_coverage_pct < 25`, bias toward warm/green and lighting/gradient mods (already in prompt_gen).  
  - Keep Explorer (100% explore) and Exploiter (100% exploit) both on frame so discovery and reinforcement both feed static.
- **Static sound completion:**  
  - Ensure **sound_loop** is deployed so procedural audio → extract → grow static_sound runs without video.  
  - Ensure frame workers have audio decode working and **derive_static_sound_from_spec** fallback when audio is empty so every run adds at least one static_sound path.  
  - Procedural audio should vary mid/high (tone, hiss) not only low (rumble) per §2.5.

### 3.2 Window worker (Balanced)

- **LOOP_EXTRACTION_FOCUS=window** — only dynamic + narrative growth and post.
- **Dynamic completion:**  
  - Confirm **ensure_dynamic_primitives_seeded** runs at start of window growth and seeds full camera list (all motion_type from origins).  
  - Ensure extraction and POST include **depth_breakdown** for motion, lighting, composition, graphics where applicable (per REGISTRY_AND_WORKFLOW_IMPROVEMENTS P0).  
  - Worker merge of learned_gradient, learned_camera, learned_audio_semantic into registries API is done; verify export shows these under blended_dynamic.
- **Narrative completion:**  
  - Use **generate_targeted_narrative_prompt** when exploring (coverage-driven) so missing or low-count NARRATIVE_ORIGINS get prompts.  
  - **Discovery-adjusted exploit ratio:** when narrative_min_coverage_pct < 50, cap exploit (already in automate_loop).  
  - Run **backfill_registry_names** so narrative entries get semantic names and cascade to prompts/interpretations.

### 3.3 Interpretation worker

- Ensures interpretation registry is filled; main loop uses interpretation_prompts when exploring. No change needed for “primitive + discovered” completeness of static/dynamic/narrative; it improves prompt variety and quality.

### 3.4 Discovery-adjusted exploit and coverage

- **Exploit cap when coverage is low** (static_colors_coverage_pct < 10 or narrative_min_coverage_pct < 50) — already implemented; verify GET /api/registries/coverage returns correct numbers.  
- **Coverage denominator:** Align with completion_targets / coverage_snapshot definition (e.g. static color “cells” = granularity of RGB + opacity grid). If 1.35% is correct, prioritize color_sweep and explorer volume to raise it.

---

## 4. Enhancements to maximize primitive + discovered values

### 4.1 Pure static (color + sound)

| Enhancement | Action |
|-------------|--------|
| **Seed all 60+ color primitives in API** | If the Worker only exposes 16, consider syncing all STATIC_COLOR_PRIMITIVES to D1/API so “primitives” in export and for-creation match local seeding and creation pool. |
| **Color sweep on a schedule** | Run `scripts/color_sweep.py` (e.g. weekly or after N explore runs) to register a grid of RGB values and raise static_colors_coverage_pct. |
| **Single opacity tier for keys** | Mar 12 export uses RGB-only keys; if opacity is no longer in the key, ensure tolerance and keying in growth match (no duplicate keys for same RGB at different opacity if you collapsed opacity). |
| **Sound: primitive count in export** | Primitives with count 0 is OK if they are seeded and used; optionally ensure at least one “touch” per primitive (e.g. from sound_loop or spec-derived) so counts become non-zero for reporting. |
| **Depth breakdown consistency** | Ensure every static color discovery uses only the 16 COLOR_ORIGIN_PRIMITIVES names in depth_breakdown; fix any legacy "ocean"/"default"/"opacity" in old data or extraction. |

### 4.2 Blended dynamic

| Enhancement | Action |
|-------------|--------|
| **Seed full camera list** | In ensure_dynamic_primitives_seeded use full origins.get("camera", {}).get("motion_type") (all 16) so export canonical matches origins. |
| **Depth for every discovery** | Add depth computation for motion, lighting, composition, graphics in post_dynamic_discoveries / growth so every discovered dynamic entry has primitive_depths/depth_breakdown where applicable. |
| **Canonical vs discovered** | Keep canonical lists (gradient_type, camera_motion, motion, sound) as the “primitives”; discovered entries are novel combinations. Ensure no canonical value is missing from seeding. |

### 4.3 Semantic narrative

| Enhancement | Action |
|-------------|--------|
| **Targeted narrative prompts** | When coverage is loaded, use generate_targeted_narrative_prompt for a fraction of explore runs so NARRATIVE_ORIGINS with zero or low count get explicit prompts. |
| **Backfill names** | Run backfill_registry_names so entries with names like "genre_star", "mood_amber", "theme_dawnure" get semantic names; cascade updates prompts/interpretations. |
| **Narrative origins coverage metric** | narrative_min_coverage_pct 100% in the export is good; keep defining “min coverage” as the minimum over aspects of the share of NARRATIVE_ORIGINS that have at least one entry. |

### 4.4 Cross-cutting

| Enhancement | Action |
|-------------|--------|
| **LOOP_WORKER_OFFSET_SECONDS** | Keeps frame/window workers from hitting D1 at the same time; already in workflows.yaml. |
| **Completion targets** | Use completion_targets.py and coverage_snapshot in GET /api/registries/coverage to drive exploit cap and prompt bias. |
| **Runs with learning/discovery** | Fix any gap where runs_with_learning or runs_with_discovery is undercounted so loop_progress reflects reality (REGISTRY_AND_WORKFLOW_IMPROVEMENTS P1). |

---

## 5. Checklist: “Complete” per registry

- **Pure — Color:** Every (r,g,b) cell in the chosen grid (e.g. tolerance 25, opacity steps 21 or single tier) either has a discovery or is covered by color_sweep; depth_breakdown uses only 16 primitives; all 16 (or 60+) primitives seeded and visible in export.
- **Pure — Sound:** All four primitives seeded and preferably with non-zero count; discovered blends cover a wide range of amplitude × tone combinations; keys use only primitive tones.
- **Blended:** Every canonical gradient/camera/transition/presence value seeded; every discovery has depth_breakdown where applicable; Worker merge keeps learned_* in sync with export.
- **Semantic:** Every NARRATIVE_ORIGINS value has at least one narrative entry; names are semantic (backfill); targeted narrative prompts and coverage-driven exploit cap keep growth balanced.

---

## 6. References

- **WORKFLOWS_AND_REGISTRIES.md** — Frame vs window, workflows, extraction.
- **REGISTRY_AND_WORKFLOW_IMPROVEMENTS.md** — Prioritized plan, §2.1–§2.8.
- **PRECISION_VERIFICATION_CHECKLIST.md** — LOOP_EXTRACTION_FOCUS, backfill, sound, creation.
- **config/workflows.yaml** — Explorer, Exploiter, Balanced, Interpretation, Sound.
- **src/knowledge/static_registry.py** — STATIC_COLOR_PRIMITIVES, STATIC_SOUND_PRIMITIVES.
- **src/knowledge/origins.py** — NARRATIVE_ORIGINS, CAMERA_ORIGINS, etc.
- **src/knowledge/blend_depth.py** — COLOR_ORIGIN_PRIMITIVES (16), SOUND_ORIGIN_PRIMITIVES, depth computation.
