# Registry & Loop Audit: Functions and Algorithms

This document audits every function and algorithm that supports the **static**, **dynamic**, and **narrative** registry goals:

- **Static:** Record every instance of static elements (color, sound) **per frame**; use name-generator when unnamed.
- **Dynamic:** Record every instance of dynamic elements (motion, time, lighting, composition, graphics, temporal, technical, audio_semantic) **per combined frames**; use name-generator when unnamed. (No separate “blends” category; lenient non-pure only.)
- **Narrative:** Record narrative elements (genre, mood, plots, settings, themes, scene_type) from spec; use name-generator when unnamed.

**Full algorithm/function audit:** For a module-by-module audit of **every** algorithm and function (interpretation, creation, renderer, pipeline, extraction, growth, registries, blending, names, sync, loop) with **100% precision** and **workflow success**, see **[ALGORITHMS_AND_FUNCTIONS_AUDIT.md](ALGORITHMS_AND_FUNCTIONS_AUDIT.md)**.

**Status legend:**

- **Complete** — 100% precise and accurate for its intended scope; flawless with respect to the project goal.
- **Needs work** — Does not fully align with the goal (e.g. not per-frame, not per combined-frames, name-generator not used, or single registry instead of separate static/dynamic/narrative).
- **Legacy** — Correct for legacy path; primary workflow uses per-instance growth and three registries.

---

## 1. Knowledge: Extraction

### `src/knowledge/extractor_per_instance.py` (primary for growth)

| Function / algorithm | Purpose | Alignment with goal | Status |
|----------------------|---------|---------------------|--------|
| `extract_static_per_frame()` | Yield one dict per frame: color (dominant RGB, brightness, contrast, saturation, hue, variance), sound (amplitude, tone). | **Static:** Every frame yields one static instance; sound from decoded audio per frame. | **Complete** |
| `extract_dynamic_per_window()` | Yield one dict per window (2+ frames): motion, time, lighting, composition, graphics, audio_semantic. | **Dynamic:** Per-window instances for all dynamic aspects. | **Complete** |

### `src/knowledge/extractor.py` (legacy aggregate)

| Function / algorithm | Purpose | Alignment with goal | Status |
|----------------------|---------|---------------------|--------|
| `extract_from_video()` | One `BaseKnowledgeExtract` per video (one dominant color, one motion profile, aggregates). | Whole-video summary only; no per-frame/per-window. | **Legacy** — Used for analysis dict and learning log; growth uses extractor_per_instance. |
| `_closest_palette()` / `_motion_trend()` / `_luminance_balance()` | Helpers. | Correct. | **Complete** |

### `src/knowledge/schema.py`

| Function / type | Purpose | Alignment with goal | Status |
|-----------------|---------|---------------------|--------|
| `BaseKnowledgeExtract` | Dataclass for extraction result. | Holds one dominant color, one motion profile, aggregates. No per-frame color array, no per-sample sound, no per-segment dynamic values. | **Needs work** — Extend (or add parallel structures) for per-frame static instances and per–combined-frames dynamic instances if “every instance” is to be stored. |
| `to_dict()` | Serialize extract for API/logging. | Faithful to current schema. | **Complete** |

---

## 2. Knowledge: Metrics (per-frame algorithms)

### `src/analysis/metrics.py`

| Function | Purpose | Alignment with goal | Status |
|----------|---------|---------------------|--------|
| `color_histogram()` | Per-channel RGB histogram for one frame. | Correct building block for per-frame color. | **Complete** |
| `dominant_colors()` | Approximate dominant RGB by spatial mean (n=1 default). | Single dominant per frame; no multi-color clustering. Good enough as one signal; “every instance” would need more colors per frame or per-pixel sampling. | **Complete** for current use; **Needs work** if goal is “every distinct color per frame.” |
| `frame_difference()` | Mean absolute difference between two frames (motion signal). | Correct for frame-pair motion. | **Complete** |
| `brightness_and_contrast()` | Mean brightness and std for one frame. | Correct. | **Complete** |
| `saturation_and_hue()` | Mean saturation and hue (HSV) for one frame. | Correct. | **Complete** |
| `edge_density()` | High-frequency energy (Sobel-like) for one frame. | Correct. | **Complete** |
| `spatial_variance()` | Variance of luminance across blocks. | Correct. | **Complete** |
| `gradient_strength()` | Mean gradient magnitude. | Correct. | **Complete** |
| `center_of_mass()` | Luminance-weighted center (x,y). | Correct. | **Complete** |
| `color_variance()` | Variance of RGB across pixels. | Correct. | **Complete** |

---

## 3. Knowledge: Growth (compare → add novel)

### `src/knowledge/growth_per_instance.py` (primary)

| Function | Purpose | Alignment with goal | Status |
|----------|---------|---------------------|--------|
| `grow_from_video()` | Per-frame static to ensure_static_color_in_registry, ensure_static_sound_in_registry. | **Static:** Every frame contributes; novel entries get sensible name. | **Complete** |
| `grow_dynamic_from_video()` | Per-window dynamic to ensure_dynamic_*_in_registry. | **Dynamic:** Every window contributes; novel entries named. | **Complete** |
| `ensure_static_*_in_registry()` / `_ensure_dynamic_in_registry()` | Compare key to registry; if novel append with name. | Writes to separate static/dynamic registries. | **Complete** |

### `src/knowledge/narrative_registry.py`

| Function | Purpose | Alignment with goal | Status |
|----------|---------|---------------------|--------|
| `grow_narrative_from_spec()` | Spec + instruction to ensure_narrative_in_registry (genre, mood, plots, settings, themes, scene_type). | **Narrative:** From spec; novel entries named. | **Complete** |

### `src/knowledge/growth.py` (legacy)

| Function | Purpose | Alignment with goal | Status |
|----------|---------|---------------------|--------|
| `grow_from_extract()` / `grow_from_analysis()` | One extract/analysis per video to add_learned_* and record blend. | One summary per video; single registry. | **Legacy** |

---

## 4. Knowledge: Registry (persistence and add_learned_*)

### `src/knowledge/registry.py`

| Function | Purpose | Alignment with goal | Status |
|----------|---------|---------------------|--------|
| `get_registry_dir()` | Path to knowledge directory. | Correct. | **Complete** |
| `load_registry()` / `save_registry()` | Load/save JSON registry by name. | Correct. | **Complete** |
| `load_registry_manifest()` / `_refresh_manifest_from_disk()` / `_update_manifest()` | Single manifest of domain counts. | Correct for single registry. | **Complete**; **Needs work** when splitting into static vs dynamic (two manifests or one with spectrum). |
| `list_documented_blends()` / `list_all_registry_values()` | List stored values. | Correct. | **Complete** |
| `_color_key()` | Quantize RGB to key (tolerance bucket). | Reduces near-duplicates; correct. | **Complete** |
| `is_color_novel()` | True if color not in learned registry. | Correct. | **Complete** |
| `add_learned_color()` | Add one color; use name from reserve if novel; record blend. | Uses name-generator (reserve take). **But:** one color per call; pipeline only passes one dominant per video. | **Complete** for “add one color + name”; **Needs work** for “every instance per frame” (call site must iterate frames). |
| `add_learned_motion_profile()` | Add one motion profile; name if novel. | Uses name-generator. One profile per call; pipeline passes one per video. | **Complete** for “add one motion + name”; **Needs work** if we want per–combined-frames groups. |
| `add_learned_lighting_profile()` | Add one lighting profile; name if novel. | Uses name-generator. | **Complete** |
| `add_learned_composition_profile()` | Add one composition profile; name if novel. | Uses name-generator. | **Complete** |
| `add_learned_graphics_profile()` | Add one graphics profile; name if novel. | Uses name-generator. | **Complete** |
| `add_learned_temporal_profile()` | Add one temporal profile; name if novel. | Uses name-generator. | **Complete** |
| `add_learned_technical_profile()` | Add one technical profile; name if novel. | Uses name-generator. | **Complete** |
| `_record_blend()` | Append to learned_blends with name and primitive_depths. | Correct. | **Complete** |
| `extract_and_record_full_blend()` | Record full blend of all domains with one name. | Uses name-generator. One full blend per video. | **Complete** for current design; **Needs work** when splitting static vs dynamic (full blend may span both). |

**Registry design:** All domains (color, motion, lighting, composition, graphics, temporal, technical, blends) live in a **single** registry. Goal is **separate static** (color, sound) and **dynamic** (time, motion, blends, audio semantic) registries.  
**Status:** **Needs work** — Implement separate static vs dynamic registry and wire growth to the correct one.

---

## 5. Knowledge: Name-generator

### `src/knowledge/name_reserve.py`

| Function | Purpose | Alignment with goal | Status |
|----------|---------|---------------------|--------|
| `_generate_batch()` | Generate batch of unique English-like names (same algo as `blend_names._invent_word`). | Sensible names; no character soup. | **Complete** |
| `refill()` | Refill pool to target size. | Correct. | **Complete** |
| `take()` | Consume one name from pool; refill if low; fallback to `generate_blend_name` if empty. | Used for all novel learned values. Sensible names. | **Complete** |
| `reserve_status()` / `ensure_reserve()` | Status and ensure min pool size. | Correct. | **Complete** |

### `src/knowledge/blend_names.py`

| Function | Purpose | Alignment with goal | Status |
|----------|---------|---------------------|--------|
| `_invent_word()` | English-like word from seed (2–3 syllables). | Sensible, pronounceable. | **Complete** |
| `_words_from_prompt()` / `_combine_words()` | Prompt words → combined candidate. | Sensible. | **Complete** |
| `generate_blend_name()` | Unique name: try prompt words, then invented word, then domain + invented. | Used when reserve is empty; produces sensible names. | **Complete** |

---

## 6. Knowledge: Domain extraction and blend depth

### `src/knowledge/domain_extraction.py`

| Function | Purpose | Alignment with goal | Status |
|----------|---------|---------------------|--------|
| `extract_to_domains()` | Map `BaseKnowledgeExtract` → per-domain dicts. | One summary per video; no per-frame or per–combined-frames. | **Complete** for current schema; **Needs work** when extraction becomes “every instance” (structure must carry per-frame/per-group data). |
| `analysis_dict_to_domains()` | Map analysis dict → per-domain dicts. | Same. | **Complete** for current; **Needs work** with new schema. |

### `src/knowledge/blend_depth.py`

| Function | Purpose | Alignment with goal | Status |
|----------|---------|---------------------|--------|
| `compute_color_depth()` | Primitive depths for one RGB. | Correct. | **Complete** |
| `compute_motion_depth()` | Primitive depths for motion level/trend. | Correct. | **Complete** |
| `compute_lighting_depth()` / `compute_composition_depth()` / `compute_graphics_depth()` / `compute_temporal_depth()` / `compute_technical_depth()` | Primitive depths per domain. | Correct. | **Complete** |
| `compute_full_blend_depths()` | Full blend depths from domain dicts. | Correct. | **Complete** |

---

## 7. Knowledge: Remote sync (API)

### `src/knowledge/remote_sync.py`

| Function | Purpose | Alignment with goal | Status |
|----------|---------|---------------------|--------|
| `post_discoveries()` | POST discoveries to /api/knowledge/discoveries. | Sends one batch per video (one color, one motion, etc.). Names are empty; API may generate. | **Complete** for current contract; **Needs work** when we send “every instance” and/or separate static vs dynamic; ensure API or client assigns sensible names. |
| `grow_and_sync_to_api()` | Build discoveries from analysis (+ spec); POST. | Builds one discovery per domain per video; no per-frame or per–combined-frames. Uses `analysis_dict_to_domains` and blend_depth. | **Needs work** — Must support “every instance” and separate static/dynamic when implemented. |

---

## 8. Analysis (entry point for “interpret a video”)

### `src/analysis/analyzer.py`

| Function | Purpose | Alignment with goal | Status |
|----------|---------|---------------------|--------|
| `analyze_video()` | Call `extract_from_video()`; convert to `OutputAnalysis`. | Same as extractor: one summary per video. | **Needs work** — When extraction is per-frame/per–combined-frames, analysis entry point must expose or aggregate those instances appropriately. |
| `_extract_to_output_analysis()` | BaseKnowledgeExtract → OutputAnalysis. | Faithful conversion. | **Complete** |
| `OutputAnalysis` | Backward-compat struct (dominant color, motion, etc.). | Matches current extraction. | **Complete** for current; **Needs work** if we add per-frame/per-group fields. |

---

## 9. Pipeline and creation

### `src/pipeline.py`

| Function | Purpose | Alignment with goal | Status |
|----------|---------|---------------------|--------|
| `generate_full_video()` | One prompt → one video file; optional segments + concat; add audio. | Produces the output that is later extracted. Does not perform extraction or growth. | **Complete** |
| `_add_audio()` | Add procedural audio to MP4. | Ensures audio track exists. | **Complete** |

### `src/creation/builder.py`

| Function | Purpose | Alignment with goal | Status |
|----------|---------|---------------------|--------|
| `build_spec_from_instruction()` | InterpretedInstruction + optional knowledge → SceneSpec. | Builds spec for renderer; uses blending and learned values. | **Complete** for creation; not responsible for “every instance” recording. |
| `_build_palette_from_blending()` / `_build_motion_from_blending()` / etc. | Blend primitives + learned per domain. | Correct for creation. | **Complete** |

---

## 10. Scripts (loop and one-off)

| Script / path | Purpose | Alignment with goal | Status |
|---------------|---------|---------------------|--------|
| `scripts/automate_loop.py` | Loop: pick prompt → generate → extract_from_video → grow_and_sync_to_api. | Uses one extract per video; syncs one batch of discoveries. No per-frame or per–combined-frames iteration. | **Needs work** — When extraction and growth support “every instance,” loop must call them in a way that records per-frame static and per–combined-frames dynamic. |
| `scripts/generate_bridge.py` | Process API jobs: generate → upload → analyze_video → grow_and_sync_to_api. | Same as above. | **Needs work** — Same as automate_loop. |
| `scripts/generate.py` | One-off generate → analyze_video → log_run → grow_from_analysis. | Same: one analysis, one growth. | **Needs work** — Same as above. |
| `scripts/automate.py` | Interval-based automation; analyze_video → POST learning. | Does not call growth; only learning log. | **Complete** for its scope; add “every instance” growth when available. |

---

## 10.1 Aspect coverage matrix (every aspect and sub-aspect)

Ensures **no element goes unnoticed**: every registry aspect has extraction → ensure in registry → used in loop → synced to API.

| Spectrum | Aspect | Sub-aspects | Extracted? | Ensure in registry? | In grow_from_video? | In automate_loop? | In generate_bridge --learn? | API accepts? |
|----------|--------|-------------|------------|---------------------|----------------------|------------------|-----------------------------|---------------|
| **Static** | Color | blending, opacity, chroma, luminance, hue, saturation, brightness, contrast | ✅ per frame | ✅ ensure_static_color_in_registry | ✅ | ✅ | ✅ | ✅ static_colors |
| **Static** | Sound | weight, tone, timbre, amplitude | ✅ Decoded per-frame (RMS + tone from FFT); spec-derived fallback | ✅ ensure_static_sound_in_registry | ✅ | ✅ | ✅ | ✅ static_sound |
| **Dynamic** | Time | duration, rate, sync | ✅ per window | ✅ ensure_dynamic_time_in_registry | ✅ | ✅ | ✅ | ✅ time (learned_time) |
| **Dynamic** | Motion | speed, direction, rhythm, dimensional | ✅ per window | ✅ ensure_dynamic_motion_in_registry | ✅ | ✅ | ✅ | ✅ motion |
| **Dynamic** | Blends | color_blends, sound_mixes, transitions | Whole-video only (grow_and_sync) | N/A (blends table) | N/A | ✅ | ✅ | ✅ blends |
| **Dynamic** | Audio (semantic) | music, melody, dialogue, sfx | Spec-derived (presence → role) | ✅ ensure_dynamic_audio_semantic_in_registry | ✅ | ✅ | ✅ | ✅ audio_semantic (learned_audio_semantic) |
| **Dynamic** | Lighting | brightness, contrast, saturation | ✅ per window | ✅ ensure_dynamic_lighting_in_registry | ✅ | ✅ | ✅ | ✅ lighting |
| **Dynamic** | Composition | center_of_mass, balance, luminance_balance | ✅ per window | ✅ ensure_dynamic_composition_in_registry | ✅ | ✅ | ✅ | ✅ composition |
| **Dynamic** | Graphics | edge_density, spatial_variance, busyness | ✅ per window | ✅ ensure_dynamic_graphics_in_registry | ✅ | ✅ | ✅ | ✅ graphics |
| **Dynamic** | Temporal | pacing, motion_trend | ✅ per window | ✅ ensure_dynamic_temporal_in_registry | ✅ | ✅ | ✅ | ✅ temporal |
| **Dynamic** | Technical | width, height, fps | ✅ per window | ✅ ensure_dynamic_technical_in_registry | ✅ | ✅ | ✅ | ✅ technical |
| **Narrative** | Narrative | genre, mood, plots, settings, themes, scene_type | ✅ from spec | ✅ ensure_narrative_in_registry | N/A (separate grow_narrative) | ✅ | ✅ | ✅ narrative |

**All aspects implemented:** Static sound uses decoded per-frame audio (RMS amplitude, tone from FFT) with spec-derived fallback when no track; dynamic time is synced to D1 via `learned_time`.

---

## 10.2 Loop & API integration checklist

| Step | automate_loop | generate_bridge --learn | API |
|------|----------------|-------------------------|-----|
| Generate video | ✅ generate_full_video | ✅ generate_full_video | — |
| Upload | ✅ POST /api/jobs/{id}/upload | ✅ | ✅ |
| Extract whole-video (analysis) | ✅ extract_from_video → to_dict | ✅ analyze_video → to_dict | — |
| Per-frame static (color, sound) | ✅ grow_from_video + post_static_discoveries | ✅ grow_from_video + post_static_discoveries | ✅ static_colors, static_sound |
| Per-window dynamic (motion, …) | ✅ grow_dynamic_from_video + post_dynamic_discoveries | ✅ grow_dynamic_from_video + post_dynamic_discoveries | ✅ motion, lighting, composition, graphics, temporal, technical |
| Narrative from spec | ✅ grow_narrative_from_spec + post_narrative_discoveries | ✅ grow_narrative_from_spec + post_narrative_discoveries | ✅ narrative |
| Whole-video discoveries (blends, etc.) | ✅ grow_and_sync_to_api(analysis, spec) | ✅ grow_and_sync_to_api(analysis, spec) | ✅ colors, blends, motion, lighting, … |
| Learning log | ✅ POST /api/learning | ✅ | ✅ |

**Goal:** All workflows (explorer, main, exploiter) use the same pipeline so every aspect is learned and synced; no element unnoticed; API utilized to the maximum.

---

## 11. Summary: What is complete vs needs work

**Alignment with current workflow:** Per-frame static extraction (`extract_static_per_frame`), per-window dynamic extraction (`extract_dynamic_per_window`), and three-registry growth (`grow_from_video`, `grow_dynamic_from_video`, `grow_narrative_from_spec`) are implemented and used in `automate_loop.py` and `generate_bridge.py`. For a full audit of every algorithm and function, see **[ALGORITHMS_AND_FUNCTIONS_AUDIT.md](ALGORITHMS_AND_FUNCTIONS_AUDIT.md)**.

### Complete (flawless for current scope)

- **Per-instance extraction:** `extractor_per_instance.py` — extract_static_per_frame, extract_dynamic_per_window (color, sound per frame; motion, time, lighting, composition, graphics, temporal, technical, audio_semantic per window).
- **Per-instance growth:** `growth_per_instance.py` — grow_from_video, grow_dynamic_from_video; `narrative_registry.py` — grow_narrative_from_spec; all use generate_sensible_name for novel entries.
- **Three registries:** static_registry (color, sound), dynamic_registry (time, motion, lighting, composition, graphics, temporal, technical, audio_semantic), narrative_registry (genre, mood, plots, settings, themes, scene_type).
- **Name-generator:** `name_reserve` (take, refill, ensure_reserve), `blend_names` (_invent_word, generate_sensible_name, generate_blend_name) — sensible, consistent names.
- **Per-frame metrics:** `metrics.py` — color_histogram, dominant_colors, frame_difference, brightness_and_contrast, saturation_and_hue, edge_density, spatial_variance, gradient_strength, center_of_mass, color_variance.
- **Registry CRUD:** load/save static, dynamic, narrative; legacy load_registry, save_registry, manifest, list_*, is_color_novel, _color_key.
- **Add-one and record blend (legacy):** add_learned_color, add_learned_motion_profile, etc., _record_blend, extract_and_record_full_blend — used by grow_and_sync_to_api.
- **Blend depth:** All compute_*_depth and compute_full_blend_depths.
- **Creation:** build_spec_from_instruction and blending helpers.
- **Pipeline:** generate_full_video, _add_audio.

### Optional / legacy

1. **generate.py:** Uses legacy grow_from_analysis (one summary per video). For full three-registry growth on one-off runs, call grow_from_video, grow_dynamic_from_video, grow_narrative_from_spec and post_*_discoveries.
2. **Legacy extraction/growth:** extract_from_video, grow_from_extract, grow_from_analysis remain for analysis dict and whole-video API payload (grow_and_sync_to_api).

---

## 12. Reference: Project goals (from registry docs)

- **STATIC_ELEMENTS_REGISTRY:** Record every instance of static elements (color, sound) **per frame**; use name-generator when unnamed.
- **DYNAMIC_ELEMENTS_REGISTRY:** Record every instance of dynamic elements (motion, blends, semantic audio) **per combined frames**; use name-generator when unnamed.
- **Two registries:** Static (color, sound) vs dynamic (time, motion, blends, audio semantic). Name-generator: sensible, human-readable, consistent names only.

Use this audit when implementing “every instance” extraction, separate static/dynamic registries, and name-generator for all novel values.

---

## 13. Canonical MP4 aspect coverage (100% accuracy)

For a single source of truth on **every aspect of a complete MP4** and how each is extracted, stored, and synced (no aspect left out or misread), see **[MP4_ASPECT_COVERAGE.md](MP4_ASPECT_COVERAGE.md)**. It maps container, video track, and audio track to static/dynamic registries and documents every sub-aspect (e.g. color: luminance, chroma, opacity; motion: direction, rhythm; time: rate).
