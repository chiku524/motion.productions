# INTENDED_LOOP: Functions & Algorithms Reference

This document lists every function and algorithm used in the [INTENDED_LOOP](INTENDED_LOOP.md) workflow, with a brief summary of what each does. Use this to trace the flow from prompt → output → extraction → growth.

---

## Continuous Loop: Step-by-Step Summary

What actually happens on each run of the loop (e.g. on Railway):

| Step | What happens | Where things can go wrong |
|------|--------------|---------------------------|
| **1. Pick prompt** | 70% of the time: choose randomly from `good_prompts` (prompts that passed quality check). 30%: generate a new prompt via `generate_procedural_prompt`. | Same good prompts are reused often → same keywords → same colors/motion. |
| **2. Load knowledge** | Call `get_knowledge_for_creation(config)` → fetch learned_colors, learned_motion, learned_audio from API. | API failure → knowledge is `{}` → no learned influence on creation. |
| **3. Create job** | POST /api/jobs with prompt and duration. Get `job_id`. | — |
| **4. Generate video** | `generate_full_video(prompt, duration, generator, seed=run_seed, config)`. Inside: (a) generator interprets prompt, fetches knowledge, builds spec, renders frames to mp4; (b) pipeline calls `_add_audio`. | See steps 4a–4b below. |
| **4a. Interpretation** | `interpret_user_prompt` → palette, motion, intensity, palette_hints, motion_hints, etc. from keywords. | First keyword wins for primary values; hints collect all matches. Same prompts → same hints. |
| **4b. Creation** | `build_spec_from_instruction` → blends palette_hints + learned_colors → `palette_colors`; blends motion_hints + learned_motion → `motion_type`. | **Motion bug:** `blend_motion_params` expects speed (static/slow/medium/fast) but receives flow/wave/pulse → all default to `"slow"` → same motion every time. |
| **4c. Render** | For each frame: `render_frame(spec, t, w, h, seed)` uses `palette_colors` (or palette_name) and `get_motion_func(motion_type)`. | Only 5 motion types (slow, wave, flow, fast, pulse). With bug, we almost always get "slow". |
| **4d. Add audio** | `_add_audio` always runs (no config gate). Calls `mix_audio_to_video` (pydub + ffmpeg). | Missing pydub/ffmpeg or mix errors are logged and re-raised; run fails explicitly. |
| **5. Upload** | POST video bytes to /api/jobs/{id}/upload. | — |
| **6. Extraction** | `extract_from_video(path)` → dominant color, motion_level, motion_std, etc. | — |
| **7. Growth** | `grow_and_sync_to_api(analysis, prompt, spec)` → POST discoveries (colors, motion, blends) to API. | Discoveries are stored but creation doesn’t use them effectively due to motion bug and 70% exploit. |
| **8. Learning log** | POST /api/learning with job_id, prompt, spec, analysis. | — |
| **9. Update state** | If `is_good_outcome(analysis)` → add prompt to `good_prompts`. Increment run_count, save state to API. | — |

**Why videos look similar:**

- **Motion:** `blend_motion_params` is given flow/wave/pulse but only understands static/slow/medium/fast → everything collapses to `"slow"` → same motion curve.
- **Colors:** Palette blending works, but 70% exploit reuses the same prompts (same keywords), and learned_colors have limited effect (≈15% weight).
- **Audio:** `_add_audio` always runs; missing pydub/ffmpeg or mix failures are logged and re-raised (no silent skip).

---

## 1. ORIGINS (Base Knowledge)

**File:** `src/knowledge/origins.py`

| Function | What it does |
|----------|--------------|
| `get_all_origins()` | Returns the full registry of primitives per domain (color, motion, lighting, composition, etc.) |
| `get_origin_domains()` | Returns list of domain names: color, lighting, motion, camera, composition, temporal, transition, graphics, audio, narrative, technical, depth |

**Constants:** `COLOR_ORIGINS`, `MOTION_ORIGINS`, `LIGHTING_ORIGINS`, etc. — primitive value sets for each domain.

---

## 2. INTERPRETATION (Prompt → Parameters)

**File:** `src/interpretation/parser.py`

| Function | What it does |
|----------|--------------|
| `interpret_user_prompt()` | Main entry: parses prompt into `InterpretedInstruction`. Calls all `_resolve_*` and `_extract_*` functions. |
| `_extract_words()` | Extracts lowercase alphabetic words from prompt. |
| `_extract_duration()` | Parses duration from prompt (e.g. "5 seconds", "2 min") → float seconds. |
| `_extract_negations()` | Finds "not X", "no X", "avoid X" → returns (avoid_motion, avoid_palette) lists. |
| `_resolve_palette()` | First matching keyword → palette name. Fallback: tone → palette. |
| `_resolve_palette_hints()` | **All** matching keywords → list of palette names (for blending). |
| `_resolve_motion()` | First matching keyword → motion type. Fallback: tone → motion. |
| `_resolve_motion_hints()` | **All** matching keywords → list of motion types (for blending). |
| `_resolve_intensity()` | Keyword → intensity 0–1. Fallback: tone. |
| `_resolve_gradient()` | Keyword → gradient type (vertical, horizontal, radial, angled). |
| `_resolve_camera()` | Keyword → camera motion (static, zoom, pan, etc.). |
| `_resolve_shape()` | Keyword → shape overlay (none, circle, rect). |
| `_resolve_shot()` | Keyword → shot type (wide, medium, close, pov). |
| `_resolve_transition()` | Keyword → transition (cut, fade, dissolve, wipe). |
| `_resolve_lighting()` | Keyword → lighting preset (neutral, noir, neon, etc.). |
| `_resolve_genre()` | Keyword → genre (general, documentary, thriller, etc.). |
| `_resolve_composition_balance()` | Keyword → balance (left_heavy, balanced, right_heavy, etc.). |
| `_resolve_composition_symmetry()` | Keyword → symmetry (asymmetric, slight, bilateral). |
| `_resolve_pacing_factor()` | Keyword → pacing 0.5–2.0. |
| `_resolve_tension_curve()` | Keyword → tension (flat, slow_build, standard, immediate). |
| `_resolve_audio_tempo()` | Keyword → tempo (slow, medium, fast). |
| `_resolve_audio_mood()` | Keyword → mood (neutral, calm, tense, uplifting, dark). |
| `_resolve_audio_presence()` | Keyword → presence (silence, ambient, music, sfx, full). |
| `_resolve_depth_parallax()` | Keyword → bool for 2.5D parallax. |
| `_resolve_text_overlay()` | Parses text overlay, position, educational template. |
| `_resolve_style()` | Keyword → style (cinematic, anime, abstract, etc.). |
| `_resolve_tone()` | Keyword → tone (dreamy, dark, bright, calm, etc.). |

**Data:** `src/procedural/data/keywords.py` — `KEYWORD_TO_PALETTE`, `KEYWORD_TO_MOTION`, etc. map words to values.

---

## 3. CREATION (Blend Primitives → SceneSpec)

**File:** `src/creation/builder.py`

| Function | What it does |
|----------|--------------|
| `build_spec_from_instruction()` | Main entry: instruction + knowledge → SceneSpec. Uses blending + refinement. |
| `_build_palette_from_blending()` | Blends palette_hints with `blend_palettes`; optionally blends in learned_colors (15% learned). Outputs list of RGB tuples. |
| `_build_motion_from_blending()` | Blends motion_hints with `blend_motion_params`; optionally blends in learned_motion (20% learned). Outputs motion_type string. |
| `_refine_from_knowledge()` | Refines palette/motion/intensity from by_keyword, by_palette stats (good-outcome thresholds). |
| `_refine_audio_from_knowledge()` | Refines audio tempo/mood/presence from learned_audio (most common values). |

**File:** `src/creation/scene_script.py`

| Function | What it does |
|----------|--------------|
| `build_scene_script_from_instruction()` | Builds SceneScript (shots with durations) from instruction. |
| `_resolve_pacing()` | Pacing factor → shot duration scaling. |
| `spec_from_shot()` | Maps shot config to SceneSpec per shot. |

**File:** `src/knowledge/lookup.py`

| Function | What it does |
|----------|--------------|
| `get_knowledge_for_creation()` | Fetches learned_colors, learned_motion, learned_audio from API (or local). Returns knowledge dict for creation. |

---

## 4. BLENDING (Primitive Combination)

**File:** `src/knowledge/blending.py`

| Function | What it does |
|----------|--------------|
| `blend_colors()` | Linear (or other) blend of two RGB tuples → single RGB. |
| `blend_palettes()` | Blend two palettes color-by-color → new palette. |
| `blend_motion_params()` | **Blends speed only:** static, slow, medium, fast. Uses ordinal index interpolation. |
| `blend_rhythm()` | Blends rhythm: steady, pulsing, wave, random. |
| `blend_smoothness()` | Blends smoothness: jerky, rough, smooth, fluid. |
| `blend_directionality()` | Blends directionality: none, horizontal, vertical, diagonal, radial. |
| `blend_intensity()` | Numeric blend of intensity 0–1. |
| `blend_lighting_presets()` | Blends lighting presets. |
| `blend_camera()` | Blends camera motion types. |
| `blend_audio_tempo()` | Blends tempo (slow, medium, fast). |
| `blend_audio_mood()` | Blends mood (neutral, calm, tense, etc.). |
| `blend_audio_presence()` | Blends presence (silence, ambient, music, sfx, full). |
| … | (Additional blend_* for composition, temporal, graphics, etc.) |

**Blend approaches:** `linear`, `average`, `dominant`, `geometric`, `additive`, `min_max`, `alternating`.

---

## 5. OUTPUT (Render Frames → Video)

**File:** `src/pipeline.py`

| Function | What it does |
|----------|--------------|
| `generate_full_video()` | Main entry: prompt, duration, generator → video path. Single clip or segmented + concat. |
| `_add_audio()` | Always mixes procedural audio into video (mood, tempo, presence). Failures logged and re-raised. |
| `_next_filename()` | Generates timestamped output filename. |

**File:** `src/procedural/generator.py`

| Function | What it does |
|----------|--------------|
| `ProceduralVideoGenerator.generate_clip()` | prompt → interpret → build_spec → scene_script → render each frame → imageio writer → mp4. |
| `render_frame()` | Called per frame (see below). |

**File:** `src/procedural/renderer.py`

| Function | What it does |
|----------|--------------|
| `render_frame()` | spec + t + width + height + seed → RGB frame. Uses palette (or palette_colors), motion_fn, gradient, camera, lighting. |
| `_apply_camera_transform()` | Zoom, pan, rotate applied to coord grid. |
| `_gradient_value()` | Gradient type + motion_val → per-pixel 0–1 value (vertical, horizontal, radial, angled). |

**File:** `src/procedural/motion.py`

| Function | What it does |
|----------|--------------|
| `get_motion_func()` | **Maps motion_type string → time→value function.** Only supports: slow, wave, flow, fast, pulse. Default: flow. |
| `flow()` | Linear drift: (t * speed) % 1.0. |
| `wave()` | Sinusoidal wave. |
| `pulse()` | 0.5 + 0.5 * sin(2π freq t). |
| `ease_in_out()` | Smoothstep. |
| `get_camera_params()` | camera_motion + t → (zoom, pan_x, pan_y, rotate). |

**Critical:** `get_motion_func()` expects `"slow"`, `"wave"`, `"flow"`, `"fast"`, `"pulse"`. It does **not** accept `"static"`, `"medium"`, or rhythm values like `"steady"`, `"pulsing"`.

---

## 6. EXTRACTION (Output → Analysis)

**File:** `src/knowledge/extractor.py`

| Function | What it does |
|----------|--------------|
| `extract_from_video()` | Video path → BaseKnowledgeExtract. Dominant color, motion level/std/trend, brightness, contrast, composition, etc. |
| `_closest_palette()` | RGB → closest palette name + distance. |
| `_motion_trend()` | Per-frame motion list → "steady" | "pulsing" | "wave". |
| `_luminance_balance()` | Frame → 0–1 balance value. |

**File:** `src/knowledge/domain_extraction.py`

| Function | What it does |
|----------|--------------|
| `extract_to_domains()` | BaseKnowledgeExtract → dict of domain→params. |
| `analysis_dict_to_domains()` | Analysis dict → same structure. |

---

## 7. GROWTH (Extraction → Learned Registry)

**File:** `src/knowledge/growth.py`

| Function | What it does |
|----------|--------------|
| `grow_from_extract()` | Extract → add_learned_color, add_learned_motion_profile, add_learned_lighting_profile, etc. |
| `grow_from_analysis()` | Analysis dict → same additions. |

**File:** `src/knowledge/remote_sync.py`

| Function | What it does |
|----------|--------------|
| `grow_and_sync_to_api()` | Analysis + spec → discoveries (colors, motion, lighting, blends, etc.) → POST to /api/knowledge/discoveries. |
| `post_discoveries()` | HTTP POST discoveries to API. |

**File:** `src/knowledge/registry.py`

| Function | What it does |
|----------|--------------|
| `add_learned_color()` | Novel RGB → learned_colors registry. |
| `add_learned_motion_profile()` | motion_level, motion_std, motion_trend → learned_motion. |
| `add_learned_lighting_profile()` | brightness, contrast, saturation → learned_lighting. |
| `extract_and_record_full_blend()` | Domains → full blend with primitive depths. |
| `is_color_novel()` | Check if RGB is novel vs existing learned colors. |

**File:** `src/knowledge/blend_depth.py`

| Function | What it does |
|----------|--------------|
| `compute_color_depth()` | RGB → primitive depths (closest palette weights). |
| `compute_motion_depth()` | motion_level, motion_trend → primitive depths (static/slow/medium/fast). |
| `compute_full_blend_depths()` | Domains dict → per-domain primitive depths. |

---

## 8. AUDIO

**File:** `src/audio/sound.py`

| Function | What it does |
|----------|--------------|
| `mix_audio_to_video()` | Video + optional audio file → mux with procedural audio. Writes to temp then replace (avoids ffmpeg in-place). |
| `_generate_procedural_audio()` | mood, tempo, presence → pydub AudioSegment (sine tones, silence). |

---

## Why Motion Still Looks the Same

**Root cause:** `_build_motion_from_blending()` uses `blend_motion_params()`, which expects **speed** values: `"static"`, `"slow"`, `"medium"`, `"fast"`. But keywords and hints produce **motion types**: `"flow"`, `"wave"`, `"pulse"`, `"slow"`, `"fast"`. When `"flow"` or `"pulse"` is passed, it is not in the speed list, so it defaults to index 1 (`"slow"`). The blend therefore almost always returns `"slow"` or another speed value, and the renderer ends up with the same motion behavior.

**Renderer expectation:** `get_motion_func()` accepts `"slow"`, `"wave"`, `"flow"`, `"fast"`, `"pulse"`. It does **not** use rhythm values (`"steady"`, `"pulsing"`, `"wave"` in blend_rhythm's sense).

**Fix needed:** Use `blend_rhythm()` (steady, pulsing, wave, random) for flow/wave/pulse, and map the result to a motion_type the renderer understands. Or introduce a dedicated blend for motion_type (flow, wave, pulse, slow, fast) so blending produces the correct renderer inputs.

---

## Why Palettes May Look Similar

- **Exploit ratio:** ~70% of runs reuse "good" prompts, so the same prompts (and thus similar palette_hints) are used repeatedly.
- **Limited hint diversity:** Many prompts share the same few keywords (e.g. "cinematic", "dreamy", "gentle") and map to the same palettes.
- **Learned color influence:** Learned color blending is only ~15%; the rest comes from palette hints, so impact is modest until many discoveries accumulate.
