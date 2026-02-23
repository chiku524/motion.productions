# Mission & operations

**Purpose:** Align the `motion.productions` project with a clear mission, five optimization areas, and a codebase audit for 100% precision, data completeness, and prompt interpretation readiness.

**Reference:** REGISTRY_FOUNDATION.md, REGISTRY_REVIEW_AND_IMPROVEMENT_PLAN.md.

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
| **Monitor extraction focus** | Use **`LOOP_EXTRACTION_FOCUS`** (not `LCXP_EXTRACTION_FOCUS`) on each worker. See **RAILWAY_CONFIG.md** §8 and **REGISTRY_REVIEW_AND_IMPROVEMENT_PLAN.md**. |
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
|----------|---------|
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

## Reference

- **Living plan:** REGISTRY_REVIEW_AND_IMPROVEMENT_PLAN.md
- **Verification:** PRECISION_VERIFICATION_CHECKLIST.md
- **Env:** **`LOOP_EXTRACTION_FOCUS`** — RAILWAY_CONFIG.md §8.1 (exact name; not LCXP).
- **Logging:** `Growth [frame]`, `Growth [window]`, `Missing learning (job_id=...)`, `Missing discovery (job_id=...)`.
- **Backfill:** `scripts/backfill_registry_names.py`; API `POST /api/registries/backfill-names`.
- **Sound workflow:** `scripts/sound_loop.py`; config `workflows.yaml`.
