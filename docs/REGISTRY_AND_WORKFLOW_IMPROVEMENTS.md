# Registry and workflow improvements

**Consolidated from:** REGISTRY_REVIEW_AND_IMPROVEMENT_PLAN, WORKFLOW_EFFICIENCY_AND_REGISTRY_COMPLETION, WORKFLOW_IMPROVEMENT_PLAN_FROM_REPORTS, MANUS_AI_ENHANCEMENT_REPORT_REVIEW.

**References:** [WORKFLOWS_AND_REGISTRIES.md](WORKFLOWS_AND_REGISTRIES.md), [DEPLOYMENT.md](DEPLOYMENT.md).

---

# Part 0 — Mission & operations

**Purpose:** Align the `motion.productions` project with a clear mission, five optimization areas, and a codebase audit for 100% precision, data completeness, and prompt interpretation readiness.

**Reference:** [REGISTRY_FOUNDATION.md](REGISTRY_FOUNDATION.md), Part I below.

---

## Refined mission statement

- **Core objective:** Achieve **100% precision** in all workflow algorithms and functions so that results across the platform are **100% accurate**.
- **Data acquisition:** Systematically acquire and record **every possible combination** of origin/primitive values across all video-related aspects (sound, color, motion, theme, plot, etc.). Each discovered value receives an **authentic, semantically meaningful name** in its registry.
- **Ultimate goal:** Build a **complete, granular dataset** across the Pure (Static), Blended (Dynamic), Semantic (Narrative), and Interpretation registries. This dataset is the foundation for a **fully capable prompt interpretator** that understands user prompts (including slang and multi-sense words) and generates corresponding videos with high accuracy.

---

## 1. Strategic optimizations (operations)

### 1.1 Registry completeness & precision

| Action | How |
|--------|-----|
| **Monitor extraction focus** | Use **`LOOP_EXTRACTION_FOCUS`** (not `LCXP_EXTRACTION_FOCUS`) on each worker. See **[DEPLOYMENT.md](DEPLOYMENT.md)** (Fly.io section) §8 and Part I below. |
| **Verify logs** | Explorer/Exploiter (frame): expect `Growth [frame]`. Balanced (window): expect `Growth [window]`. Wrong or unset env → `Growth [all]`. |
| **Eliminate missing learning/discovery** | Investigate every `Missing discovery (job_id=...)` and `Missing learning (job_id=...)` in logs; fix POST/sync so successful runs always contribute. |
| **Backfill propagation** | Backfill scripts replace gibberish names with semantic ones; **cascade** must propagate new names to prompts, **sources_json**, and **blend JSON** so no reference to the old name remains. |

### 1.2 Sound discovery workflow

Deploy **`sound_loop.py`** as a dedicated process; ensure for-creation returns static_sound and builder uses it (pure_sounds, mood/tone refinement).

### 1.3 Interpretation & linguistic precision

Monitor Interpret worker logs: `[cycle] interpreted`, `[cycle] backfill`, `[cycle] generated`, `[cycle] linguistic growth`. Use growing linguistic registry and semantic info so prompts are meaningful and diverse.

### 1.4 Creation-phase behavior

Every creation choice driven by data (origin/primitive + registry). Use wider selection pools (2–3 palette hints), underused/recent bias, and aggressively randomize DEFAULT gradient/motion/camera when no user hint.

### 1.5 Registry density monitoring

Review exported registry JSON for sparse or stagnant categories; investigate extraction and creation-phase integration for each.

---

## 2. Codebase audit: workflow & creation

**Date:** 2026-02-17. **Scope:** Interpretation, creation, extraction, growth, sync.

### 2.1 LOOP_EXTRACTION_FOCUS

**Correct env name:** **`LOOP_EXTRACTION_FOCUS`** — not `LCXP_EXTRACTION_FOCUS`.

| Location | Finding |
|----------|----------|
| `scripts/automate_loop.py` | Reads env; normalizes to `frame` \| `window` \| `all`. Invalid/unset → `all`. |
| `src/knowledge/growth_per_instance.py` | `grow_all_from_video(..., extraction_focus=)` gates `do_frame` and `do_window`. |
| Post logic | `frame` → only `post_static_discoveries`; `window` → only `post_dynamic_discoveries` + `post_narrative_discoveries`; `grow_and_sync_to_api` only for window/all. |
| Log message | `Growth [frame]` or `Growth [window]` or `Growth [all]`. |

First run when `extraction_focus == "all"` logs: *"LOOP_EXTRACTION_FOCUS is unset → Growth [all]. For split workers set ..."*

### 2.2 Missing learning / discovery

job_id passed in all post_* and POST /api/learning. On failure: `Missing discovery (job_id=...)` and `Missing learning (job_id=...)`. After growth/sync, `post_discoveries(api_base, {"job_id": job_id})` is always called.

### 2.3 Backfill

`POST /api/registries/backfill-names`; cascade updates learning_runs.prompt, interpretations, jobs.prompt, learned_blends (source_prompt, inputs_json, output_json, primitive_depths_json), all sources_json. Script: `scripts/backfill_registry_names.py`.

### 2.4 Creation: pure-per-frame and data-driven

| Component | Implementation |
|-----------|----------------|
| **builder.py** | `_build_pure_color_pool()` = origin + static_colors + learned_colors; `creation_mode = "pure_per_frame"` when pool non-empty. Spec carries `pure_colors`, `creation_mode`. |
| **renderer.py** | `_render_pure_per_frame()`: per-pixel color from `pure_colors` via hash of (xx, yy, t, seed). |
| **Parameterization** | Palette: 2–3 hints, underused bias. Motion, gradient, camera: _pool_from_knowledge(learned_* + origin_*). Audio: learned_audio + static_sound; weighted_choice_favor_recent / underused. Pure sounds: 3–5 from static_sound. |

### 2.5 sound_loop.py

Location: `scripts/sound_loop.py`. Generates WAV, segments via `read_audio_segments_only()`, grows static sound via `grow_static_sound_from_audio_segments()`, POSTs via `post_static_discoveries`. for-creation returns static_sound; builder uses it.

### 2.6 Interpretation and linguistic

Interpret worker: queue, backfill, generation, linguistic growth (logs: `[cycle] interpreted`, backfill, generated, linguistic growth). Prompt gen: automation/prompt_gen.py (slot pools, _expand_from_knowledge), interpretation/prompt_gen.py (interpret_loop). Linguistic registry: fetch in interpret_loop; growth via extract_linguistic_mappings + post_linguistic_growth.

### 2.7 Code quality

- Growth/sync/creation/interpretation functions aligned with REGISTRY_FOUNDATION (pure vs blended, naming).
- No recursion in src/ (audit confirmed).
- Tests: `tests/test_builder_and_sync.py` for _build_pure_color_pool and growth_metrics. Run: `python -m pytest tests/ -v`.

---

# Part I — Registry review and improvement plan

## Refined mission: 100% precision

1. **Comprehensive data acquisition:** Record every possible combination of origin/primitive values; each discovery gets an **authentic, semantically meaningful name**.
2. **Robust prompt interpretation:** Build a complete knowledge base across Pure, Blended, Semantic, and Interpretation registries.

**Five key areas:** Registry completeness (LOOP_EXTRACTION_FOCUS, backfill); Creation phase (pure-per-frame, data-driven); Sound discovery (sound_loop); Interpretation & linguistic; Code quality (tests, REGISTRY_FOUNDATION alignment).

**Configuration:** Use **`LOOP_EXTRACTION_FOCUS`** (not `LCXP_EXTRACTION_FOCUS`): `frame` for Explorer/Exploiter, `window` for Balanced. See [DEPLOYMENT.md](DEPLOYMENT.md) (Fly.io section). Logging: `Growth [frame]`, `Growth [window]`, `Missing learning (job_id=...)`, `Missing discovery (job_id=...)`.

## Export review: sparse categories

- **Pure sound:** Sparse until per-frame/per-segment audio decoding; spec-derived fallback used when decoded audio empty.
- **Blended gradient/camera/sound:** Worker now merges learned_gradient, learned_camera, learned_audio_semantic; per-window discoveries appear in export.
- **Depth for learned colors:** Single "depth vs pure static" with 16-primitive breakdown; stored in learned_colors.

## Prioritized plan (100% precision)

**P1 — Critical:** Depth for learned colors (done); merge gradient/camera/sound in registries API (done); ensure job_id on every learning/discovery path.

**P2 — High:** Narrative = intended (spec+prompt), not observed; interpretation + linguistic workflow; UI single depth concept.

**P3 — Medium:** Pure static sound extraction from MP4; dynamic audio_semantic in registries.

**P4 — Ongoing:** Algorithms audit; longer videos / multi-segment.

## Implementation status (registry & creation)

- LOOP_EXTRACTION_FOCUS (frame/window) in automate_loop and growth_per_instance.
- GET /api/knowledge/for-creation returns static_sound; builder uses it.
- backfill_registry_names.py; POST /api/registries/backfill-names with cascade.
- pure-per-frame creation mode in builder and renderer.
- Missing learning/discovery logs include job_id.

---

# Part II — Workflow efficiency and registry completion

## What “registry complete” means

| Registry | Complete = |
|----------|------------|
| Pure — Color | Every color key (r,g,b + opacity) ≈ 28k cells |
| Pure — Sound | All four primitives in depth_breakdown |
| Blended | Every canonical value per domain; novel combos recorded |
| Semantic | Every NARRATIVE_ORIGINS value recorded |

## High-impact enhancements

- **§2.1 Coverage-aware prompt selection:** GET /api/registries/coverage; pass coverage into pick_prompt; bias toward under-sampled aspects. **Implemented.**
- **§2.2 Discovery-adjusted exploit ratio:** Cap exploit when static_colors_coverage_pct < 10 or narrative_min_coverage_pct < 50. **Implemented.**
- **§2.3 Extraction efficiency:** max_frames, sample_every configurable; adaptive sample_every for short videos. **Implemented.**
- **§2.4 Targeted narrative prompts:** generate_targeted_narrative_prompt when exploring. **Implemented.**
- **§2.5 Static sound (tone/hiss):** Procedural audio adds mid/high layers; derive_static_sound_from_spec varies tone. **Implemented.**
- **§2.6 Parallel workers:** Explorer + Exploiter in config/workflows.yaml.
- **§2.7 Color sweep:** scripts/color_sweep.py for batch RGB grid.
- **§2.8 Completion targets:** completion_targets.py; coverage_snapshot in GET /api/registries/coverage.

---

# Part III — Workflow improvement plan (from reports)

## Report findings

**Working:** Blended registry growth (lighting, composition, graphics); pure static color depth; schema v2; core loop.

**Critical issues:** Numeric-suffix names (backfill_registry_names.py); missing depth_breakdown for motion/lighting/etc.; pure sound key leakage (primitive tones only); runs_with_learning gap; semantic stagnation; linguistic gaps; color bias.

## Prioritized action plan

**P0:** (1) Run backfill_registry_names.py; (2) Add depth_breakdown to per-window dynamic; (3) Enforce primitive-only tones in static sound.

**P1:** (4) Seed linguistic domains; (5) Tone/style synonyms; (6) Zone-aware creation biasing; (7) Fix runs_with_learning gap.

**P2:** Schema v2 (done); track exploit_count/explore_count; expand procedural prompt pool; depth_breakdown for narrative; generate.py full growth or deprecate.

**P3:** Transition detection; parallax; coverage targets in snapshot; interpretation cap; batch-seed linguistic.

## Recommended next steps

1. Run backfill (dry-run then live): `python scripts/backfill_registry_names.py --api-base https://motion.productions --timeout 300`
2. Add depth computation for motion/lighting/composition/graphics in post_dynamic_discoveries.
3. Harden static sound key (primitive tones only).
4. Verify LOOP_EXTRACTION_FOCUS on each worker service.
5. Seed five missing linguistic domains.

---

# Part IV — Manus AI report review & adoption

## Report summary

Architecture correct. Data gaps: Pure sound (deployment/sound_loop); six empty Blended categories (Worker merge added); colors_from_blends numeric names (backfill); linguistic domains (seed script); color coverage (coverage bias, color_sweep).

## Priority matrix → actions

| # | Finding | Action |
|---|---------|--------|
| 1 | Zero sound | Deploy sound_loop; verify POST; procedural audio mid/high |
| 2 | Six empty Blended | Worker merges learned_lighting/composition/etc. (done) |
| 3 | Non-semantic names | backfill_registry_names.py |
| 4 | Linguistic domains | seed_linguistic_domains.py |
| 5 | Color coverage | GET /api/registries/coverage; coverage bias; color_sweep |

## Verification checklist

LOOP_EXTRACTION_FOCUS set; sound_loop deployed; Balanced posting; backfill run; linguistic seeded; coverage monitored; tests pass.

## Findings status

Sound: Addressed (spec-derived fallback). Blended merge: Addressed (Worker). Names: Operational (run backfill). Linguistic: Addressed (seed script). Color: Addressed (bias, color_sweep). Phases B–F: Roadmap.

---

# Part V — Registry JSON review & export analysis

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

## V.1. Export comparison summary

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

## V.2. Primitive vs discovered alignment

### V.2.1 Color primitives

- **Export / API:** Exports show **16** color primitives (black, white, red, green, blue, yellow, cyan, magenta, orange, purple, pink, brown, navy, gray, olive, teal). This matches `blend_depth.COLOR_ORIGIN_PRIMITIVES` used for **depth_breakdown**.
- **Code:** `static_registry.STATIC_COLOR_PRIMITIVES` seeds **60+** colors (indigo, violet, coral, gold, forestgreen, etc.). Those are for **creation pool and variety**; depth is still computed against the 16 so exports stay consistent.
- **Gap:** Ensure the Worker/API “primitives” list used for coverage and for-creation matches the same 16 (or the full 60+ if you want coverage to reflect the larger set). Today, coverage at 1.35% suggests the denominator is large (e.g. ~28k cells); filling it requires more discovery, not more primitives in the export.

### V.2.2 Sound primitives

- **Export:** Four primitives (silence, rumble, tone, hiss) with count 0 in the discoveries list; discovered entries use keys like `0.11_low_low` and depth_breakdown with `origin_noises`.
- **Code:** `STATIC_SOUND_PRIMITIVES` has 10 entries (silence + strength bands for rumble/tone/hiss); `SOUND_ORIGIN_PRIMITIVES` in blend_depth is the 4 names. Pure sound keys must use only primitive tones (low, mid, high, silent, neutral) per REGISTRY_FOUNDATION.
- **Gap:** No major mismatch. To “complete” pure sound: ensure every primitive has non-zero count over time (frame workers + sound_loop) and that discovered blends cover a wide range of amplitude/tone combinations.

### V.2.3 Dynamic primitives

- **Gradient:** 4 (vertical, horizontal, radial, angled) — seeded and present in export.
- **Camera:** Origins list 16 motion_type values; export canonical lists 15 (including roll, truck, pedestal, arc, tracking, birds_eye, whip_pan, rotate). Ensure `ensure_dynamic_primitives_seeded` uses the full `CAMERA_ORIGINS["motion_type"]` so all 16 are seeded.
- **Transition:** cut, fade, dissolve, wipe — present.
- **Audio semantic:** presence values (silence, ambient, music, sfx, full) — present as canonical “sound” entries (tempo/mood/presence).

### V.2.4 Narrative primitives

- **NARRATIVE_ORIGINS** (origins.py): genre (12), tone (10), style (5), tension_curve (4), settings (14), themes (14), scene_type (10). Export shows many of these but with uneven counts; some entry_key values are NARRATIVE_ORIGINS, others are discovered (e.g. “neon”, “golden_hour”).
- **Gap:** “Complete” = every NARRATIVE_ORIGINS value has at least one entry. Use **targeted narrative prompts** (Part II §2.4) and coverage-driven prompt selection so low-count origins get more runs.

---

## V.3. Workflow optimizations (to complete each registry)

### V.3.1 Frame workers (Explorer + Exploiter)

- **LOOP_EXTRACTION_FOCUS=frame** — already in config; verify on deploy so only static (color + sound) is grown and posted.
- **Static color completion:**  
  - Run **color_sweep** periodically to batch-register RGB grid cells (`scripts/color_sweep.py`).  
  - Use **coverage-aware prompt selection**: when `static_colors_coverage_pct < 25`, bias toward warm/green and lighting/gradient mods (already in prompt_gen).  
  - Keep Explorer (100% explore) and Exploiter (100% exploit) both on frame so discovery and reinforcement both feed static.
- **Static sound completion:**  
  - Ensure **sound_loop** is deployed so procedural audio → extract → grow static_sound runs without video.  
  - Ensure frame workers have audio decode working and **derive_static_sound_from_spec** fallback when audio is empty so every run adds at least one static_sound path.  
  - Procedural audio should vary mid/high (tone, hiss) not only low (rumble) per Part II §2.5.

### V.3.2 Window worker (Balanced)

- **LOOP_EXTRACTION_FOCUS=window** — only dynamic + narrative growth and post.
- **Dynamic completion:**  
  - Confirm **ensure_dynamic_primitives_seeded** runs at start of window growth and seeds full camera list (all motion_type from origins).  
  - Ensure extraction and POST include **depth_breakdown** for motion, lighting, composition, graphics where applicable (Part I P0).  
  - Worker merge of learned_gradient, learned_camera, learned_audio_semantic into registries API is done; verify export shows these under blended_dynamic.
- **Narrative completion:**  
  - Use **generate_targeted_narrative_prompt** when exploring (coverage-driven) so missing or low-count NARRATIVE_ORIGINS get prompts.  
  - **Discovery-adjusted exploit ratio:** when narrative_min_coverage_pct < 50, cap exploit (already in automate_loop).  
  - Run **backfill_registry_names** so narrative entries get semantic names and cascade to prompts/interpretations.

### V.3.3 Interpretation worker

Ensures interpretation registry is filled; main loop uses interpretation_prompts when exploring. No change needed for “primitive + discovered” completeness of static/dynamic/narrative; it improves prompt variety and quality.

### V.3.4 Discovery-adjusted exploit and coverage

- **Exploit cap when coverage is low** (static_colors_coverage_pct < 10 or narrative_min_coverage_pct < 50) — already implemented; verify GET /api/registries/coverage returns correct numbers.  
- **Coverage denominator:** Align with completion_targets / coverage_snapshot definition (e.g. static color “cells” = granularity of RGB + opacity grid). If 1.35% is correct, prioritize color_sweep and explorer volume to raise it.

---

## V.4. Enhancements to maximize primitive + discovered values

### V.4.1 Pure static (color + sound)

| Enhancement | Action |
|-------------|--------|
| **Seed all 60+ color primitives in API** | If the Worker only exposes 16, consider syncing all STATIC_COLOR_PRIMITIVES to D1/API so “primitives” in export and for-creation match local seeding and creation pool. |
| **Color sweep on a schedule** | Run `scripts/color_sweep.py` (e.g. weekly or after N explore runs) to register a grid of RGB values and raise static_colors_coverage_pct. |
| **Single opacity tier for keys** | Mar 12 export uses RGB-only keys; if opacity is no longer in the key, ensure tolerance and keying in growth match (no duplicate keys for same RGB at different opacity if you collapsed opacity). |
| **Sound: primitive count in export** | Primitives with count 0 is OK if they are seeded and used; optionally ensure at least one “touch” per primitive (e.g. from sound_loop or spec-derived) so counts become non-zero for reporting. |
| **Depth breakdown consistency** | Ensure every static color discovery uses only the 16 COLOR_ORIGIN_PRIMITIVES names in depth_breakdown; fix any legacy "ocean"/"default"/"opacity" in old data or extraction. |

### V.4.2 Blended dynamic

| Enhancement | Action |
|-------------|--------|
| **Seed full camera list** | In ensure_dynamic_primitives_seeded use full origins.get("camera", {}).get("motion_type") (all 16) so export canonical matches origins. |
| **Depth for every discovery** | Add depth computation for motion, lighting, composition, graphics in post_dynamic_discoveries / growth so every discovered dynamic entry has primitive_depths/depth_breakdown where applicable. |
| **Canonical vs discovered** | Keep canonical lists (gradient_type, camera_motion, motion, sound) as the “primitives”; discovered entries are novel combinations. Ensure no canonical value is missing from seeding. |

### V.4.3 Semantic narrative

| Enhancement | Action |
|-------------|--------|
| **Targeted narrative prompts** | When coverage is loaded, use generate_targeted_narrative_prompt for a fraction of explore runs so NARRATIVE_ORIGINS with zero or low count get explicit prompts. |
| **Backfill names** | Run backfill_registry_names so entries with names like "genre_star", "mood_amber", "theme_dawnure" get semantic names; cascade updates prompts/interpretations. |
| **Narrative origins coverage metric** | narrative_min_coverage_pct 100% in the export is good; keep defining “min coverage” as the minimum over aspects of the share of NARRATIVE_ORIGINS that have at least one entry. |

### V.4.4 Cross-cutting

| Enhancement | Action |
|-------------|--------|
| **LOOP_WORKER_OFFSET_SECONDS** | Keeps frame/window workers from hitting D1 at the same time; already in workflows.yaml. |
| **Completion targets** | Use completion_targets.py and coverage_snapshot in GET /api/registries/coverage to drive exploit cap and prompt bias. |
| **Runs with learning/discovery** | Fix any gap where runs_with_learning or runs_with_discovery is undercounted so loop_progress reflects reality (Part I P1). |

---

## V.5. Checklist: “Complete” per registry

- **Pure — Color:** Every (r,g,b) cell in the chosen grid (e.g. tolerance 25, opacity steps 21 or single tier) either has a discovery or is covered by color_sweep; depth_breakdown uses only 16 primitives; all 16 (or 60+) primitives seeded and visible in export.
- **Pure — Sound:** All four primitives seeded and preferably with non-zero count; discovered blends cover a wide range of amplitude × tone combinations; keys use only primitive tones.
- **Blended:** Every canonical gradient/camera/transition/presence value seeded; every discovery has depth_breakdown where applicable; Worker merge keeps learned_* in sync with export.
- **Semantic:** Every NARRATIVE_ORIGINS value has at least one narrative entry; names are semantic (backfill); targeted narrative prompts and coverage-driven exploit cap keep growth balanced.

---

# References

- **REGISTRY_FOUNDATION.md** — Authoritative foundation
- **WORKFLOWS_AND_REGISTRIES.md** — Full picture
- **Part 0** (above) — Mission & strategic operations
- **DEPLOYMENT.md** — Cloudflare Worker + Fly.io background workers
- **PRECISION_VERIFICATION_CHECKLIST.md** — Operator verification
- **ALGORITHMS_AND_FUNCTIONS_AUDIT.md** — Audit of extraction/growth
- **scripts/backfill_registry_names.py**, **scripts/color_sweep.py**, **scripts/registry_export_analysis.py**
