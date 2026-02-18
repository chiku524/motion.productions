# Codebase Audit: Mission Alignment

**Date:** 2026-02-17  
**Scope:** 100% precision, data completeness, and prompt interpretation readiness across interpretation, creation, extraction, growth, and sync.

**Reference:** MISSION_AND_STRATEGIC_OPTIMIZATIONS.md, REGISTRY_FOUNDATION.md, REGISTRY_REVIEW_AND_IMPROVEMENT_PLAN.md.

---

## 1. Workflow Configuration and Execution Precision

### 1.1 Extraction Focus (LOOP_EXTRACTION_FOCUS)

**Correct env name:** **`LOOP_EXTRACTION_FOCUS`** — not `LCXP_EXTRACTION_FOCUS`. The codebase uses only `LOOP_EXTRACTION_FOCUS`.

| Location | Finding |
|----------|---------|
| `scripts/automate_loop.py` | Reads `os.environ.get("LOOP_EXTRACTION_FOCUS")`; normalizes to `frame` \| `window` \| `all`. Invalid/unset → `all`. |
| `src/knowledge/growth_per_instance.py` | `grow_all_from_video(..., extraction_focus=)` gates `do_frame` and `do_window`. `frame` → only per-frame static growth; `window` → only per-window dynamic + narrative. |
| Post logic | When `extraction_focus == "frame"`: only `post_static_discoveries(static_colors, static_sound)`. When `extraction_focus == "window"`: only `post_dynamic_discoveries` + `post_narrative_discoveries`; `grow_and_sync_to_api` only called for window/all. |
| Log message | `Growth [frame]` or `Growth [window]` or `Growth [all]` — confirms runtime behavior. |

**Fix applied:** First run when `extraction_focus == "all"` now logs: *"LOOP_EXTRACTION_FOCUS is unset → Growth [all]. For split workers set LOOP_EXTRACTION_FOCUS=frame or =window (see RAILWAY_CONFIG.md §8)."*

**Verification:** Set `LOOP_EXTRACTION_FOCUS=frame` on Explorer/Exploiter and `LOOP_EXTRACTION_FOCUS=window` on Balanced; confirm logs show `Growth [frame]` / `Growth [window]` and no `Growth [all]` on those workers.

### 1.2 Missing Learning / Missing Discovery

| Mechanism | Status |
|-----------|--------|
| **job_id** | Passed in `post_static_discoveries`, `post_dynamic_discoveries`, `post_narrative_discoveries`, `grow_and_sync_to_api`, `post_discoveries(..., {"job_id": job_id})`, and `POST /api/learning`. |
| **Logs** | On failure: `Missing discovery (job_id=...)` and `Missing learning (job_id=...)` with status/exception so diagnostics can trace which jobs failed. |
| **Guaranteed discovery run** | After growth/sync (success or fail), `post_discoveries(api_base, {"job_id": job_id})` is always called so the API can insert a `discovery_runs` row for that job. |

**Recommendation:** For persistent missing learning/discovery, check: (1) network/API availability and retries, (2) API response status and body, (3) Worker diagnostics (e.g. last N jobs summary). Optional: backfill script that POSTs `/api/learning` for completed jobs without a `learning_runs` row.

### 1.3 Backfill Script Accuracy

| Item | Status |
|------|--------|
| **Primary update** | `POST /api/registries/backfill-names` updates name in the target table (static_colors, learned_colors, learned_motion, learned_blends, etc.). |
| **Cascade** | `cascadeNameUpdate(oldName, newName)` in Cloudflare worker updates: `learning_runs.prompt`, `interpretations.prompt`, `interpretations.instruction_json`, `jobs.prompt`, `learned_blends.source_prompt`, **learned_blends.inputs_json**, **learned_blends.output_json**, **learned_blends.primitive_depths_json**, and all `sources_json` columns for static_colors, static_sound, learned_*, narrative_entries. |
| **Script** | `scripts/backfill_registry_names.py` calls the API; no direct DB access. Propagation is done server-side. |

**Conclusion:** Backfill propagates new names to prompts, instruction_json, jobs, source_prompt, blend JSON (inputs/output/primitive_depths), and sources_json. Semantic consistency is maintained.

---

## 2. Creation Phase: Pure-Per-Frame and Data-Driven Behavior

### 2.1 Pure-Per-Frame Creation

| Component | Implementation |
|-----------|----------------|
| **builder.py** | `_build_pure_color_pool()` builds pool = origin primitives + static_colors + learned_colors (RGB tuples). `creation_mode = "pure_per_frame"` when pool non-empty, else `"blended"`. Spec carries `pure_colors` and `creation_mode`. |
| **renderer.py** | `render_frame()` checks `creation_mode == "pure_per_frame"` and `pure_colors`; calls `_render_pure_per_frame(xx, yy, pure_colors, t, seed, intensity)`. |
| **_render_pure_per_frame** | Per-pixel color index from deterministic hash of (xx, yy, t, seed); each pixel gets a color from `pure_colors`. Light noise added for local variation. No single blended palette applied to the whole frame. |

**Conclusion:** Pure-per-frame is implemented: random placement of pure colors from the registry at each pixel, with temporal variation via `t`.

### 2.2 Data-Driven Parameterization

| Decision | Source | Notes |
|----------|--------|-------|
| Palette | PALETTES + learned_colors/static_colors names; 2–3 hints when default/empty, weighted toward underused. | No single hardcoded default. |
| Motion | learned_motion → motion_type; weighted_choice_favor_underused by count; 50% random vs deterministic when seed_hint. | Registry-first. |
| Gradient / camera | _pool_from_knowledge(learned_*, origin_*); secure_choice. | Registry or origin only. |
| Audio | learned_audio + static_sound; 35% weighted_choice_favor_recent (created_at), else most_common tempo/mood/presence. | Not always most_common. |
| Pure sounds | 3–5 from static_sound via weighted_choice_favor_underused(count). | Fed into audio mixing. |

**Conclusion:** Creation choices are driven by API/registry data; underused/recent bias and wider palette hints (2–3) are in place.

### 2.3 Advanced Selection Strategies

- **Wider pools:** 2–3 palette hints when pool has ≥2 entries; multiple pure sounds per run.
- **Underused bias:** `weighted_choice_favor_underused` for motion, pure_sounds, palette names (when count available).
- **Recent bias:** `weighted_choice_favor_recent` for learned_audio when randomly picking.
- **Randomization of DEFAULTs:** Gradient, motion, camera when DEFAULT use secure_choice from full pool (learned + origin).

---

## 3. Dedicated Sound Discovery Workflow

### 3.1 sound_loop.py

| Item | Status |
|------|--------|
| **Location** | `scripts/sound_loop.py` |
| **Behavior** | No video: generates WAV via `generate_audio_only(mood, tempo, presence)`; segments via `read_audio_segments_only()`; grows static sound via `grow_static_sound_from_audio_segments()`; POSTs via `post_static_discoveries(api_base, [], novel_list, job_id=None)`. |
| **job_id** | Passed as `None` (sound-only runs are not jobs from the queue). Discovery run is not recorded for sound-only; acceptable for a dedicated sound worker. |
| **Integration** | Pure sound values are in static_sound registry; GET /api/knowledge/for-creation returns them; builder and audio pipeline use them (pure_sounds mixing, mood/tone refinement). |

**Conclusion:** Sound-only workflow is implemented and feeds the static sound registry; frame-focused video workflows consume it via for-creation and builder.

---

## 4. Interpretation and Linguistic Precision

### 4.1 Interpret Worker

| Log message | When |
|-------------|------|
| `[cycle] interpreted: <prompt>…` | After interpreting a queued prompt and PATCHing result. |
| `[cycle] backfill: n interpreted` | After backfilling prompts from jobs and interpreting them. |
| `[cycle] generated: <prompt>…` | After generating a prompt, interpreting it, and POSTing to /api/interpretations. |
| `[cycle] linguistic growth: +n new, m updated` | After posting extracted linguistic mappings. |

**Conclusion:** Interpret worker runs queue, backfill, generation, and linguistic growth; log lines match the intended cycle behavior.

### 4.2 Procedural Prompt Generator

| Component | Usage |
|-----------|--------|
| **src/automation/prompt_gen.py** | Slot-based instructive templates; _build_slot_pools() from static_sound, learned_colors, learned_motion, learned_audio, gradient/camera; _expand_from_knowledge() adds learned + interpretation_prompts phrases (short, non-imperative); is_semantic_name filters gibberish. |
| **src/interpretation/prompt_gen.py** | Used by interpret_loop for generate_interpretation_prompt_batch(); filter_gibberish_prompts(strict=True) applied. |

**Conclusion:** Prompt generators use registry and linguistic/semantic data; interpretation_prompts feed into extra modifiers for natural-language reuse.

### 4.3 Linguistic Registry

- Fetched in interpret_loop via `fetch_linguistic_registry(api_base)` and passed to `interpret_user_prompt(..., linguistic_registry=...)`.
- Growth via `extract_linguistic_mappings(prompt, instruction)` and `post_linguistic_growth(api_base, all_extracted)`.
- Not present in registry JSON exports; growth is observable via `[cycle] linguistic growth` logs and API.

---

## 5. Code Quality and Standards

### 5.1 Algorithm / Function Audit (Registry-Affecting)

| Workflow | Functions | Contract / alignment |
|----------|-----------|----------------------|
| **Growth** | ensure_static_color_in_registry, ensure_static_sound_in_registry, grow_all_from_video, grow_narrative_from_spec | Inputs: frame/spec/data; outputs/side effects: in-memory registry + optional novel_for_sync. Aligned with REGISTRY_FOUNDATION (pure vs blended, naming). |
| **Sync** | post_static_discoveries, post_dynamic_discoveries, post_narrative_discoveries, post_discoveries, grow_and_sync_to_api | Send payload to API; job_id when provided. |
| **Creation** | build_spec_from_instruction, _build_palette_from_blending, _build_pure_color_pool, _build_motion_from_blending, _refine_audio_from_knowledge | Instruction + knowledge → SceneSpec; no hardcoded defaults; registry-first. |
| **Interpretation** | interpret_user_prompt, extract_linguistic_mappings, post_linguistic_growth | Prompt → instruction; mappings → API. |

**Recommendation:** Add docstrings to any remaining public functions that mutate or post registry data; add unit tests for critical paths (e.g. _build_pure_color_pool with empty knowledge, ensure_static_* with minimal payload).

### 5.2 Recursion

- Grep for `recursion`, `recursive`, `RecursionError` in `src/` found **no matches**.
- No recursive patterns identified in growth, sync, or creation that would risk stack overflow.

### 5.3 Standards References

- **REGISTRY_FOUNDATION.md:** Pure = single frame/pixel/sample; Blended = time/distance; naming 100% semantic.
- **LOOP STANDARDS:** Refer to INTENDED_LOOP.md and WORKFLOWS_AND_REGISTRIES.md for flow and extraction focus.

---

## 6. Summary and Action Checklist

| Area | Status | Action |
|------|--------|--------|
| LOOP_EXTRACTION_FOCUS | Enforced in code; name is correct (not LCXP). | Set on each worker per RAILWAY_CONFIG.md §8; monitor Growth [frame/window]. |
| Missing learning/discovery | job_id on all paths; logs include job_id on failure. | Investigate failures via job_id; consider retries/backfill if needed. |
| Backfill propagation | Cascade includes prompts, instruction_json, jobs, source_prompt, blend JSON, sources_json. | Run backfill_registry_names.py as needed; no code change required. |
| Pure-per-frame creation | Implemented in builder + renderer; per-pixel pure colors. | Monitor diversity of outputs (registry growth). |
| Data-driven creation | Palette, motion, gradient, camera, audio use registry + underused/recent bias. | None. |
| sound_loop.py | Implemented; posts static_sound; creation uses static_sound. | Deploy as separate worker if not already. |
| Interpret worker | Queue, backfill, generated, linguistic growth all logged. | Monitor [cycle] lines for continuity. |
| Prompt gen | Slot pools and _expand_from_knowledge use registry + interpretation_prompts. | None. |
| Recursion | None found in src. | None. |
| Tests / docs | Some critical paths lack tests. | Add tests for ensure_static_*, _build_pure_color_pool, post_* where feasible. |

---

## 7. Next steps implemented (post-audit)

| Step | Implementation |
|------|----------------|
| **Unit tests** | **tests/test_builder_and_sync.py** added: `_build_pure_color_pool` (empty knowledge, with static/learned, RGB clamping) and **growth_metrics** (remote_sync). Run: `python -m pytest tests/ -v` or `python -m unittest discover -s tests -p "test_*.py" -v`. |
| **Learning POST retries** | **automate_loop.py** now calls `api_request_with_retry(..., max_retries=5, backoff_seconds=2.0)` explicitly for `POST /api/learning` to reduce "missing learning" from transient 5xx/429/connection failures. |

This audit confirms alignment with the mission of 100% precision, data completeness, and prompt interpretation readiness, with targeted improvements applied and recommendations for ongoing monitoring and testing.
