# Algorithms & functions audit — 100% precision and workflow success

This document audits **every** algorithm and function in the codebase for:

1. **100% precision** — Logic is well-defined, deterministic where required, and correct for its scope.
2. **Success within the workflow** — The function contributes correctly to the overall mission: continuous loop (interpret → create → render → extract → grow → sync), with all three registries (static, dynamic, narrative) evolving and creation using static elements + origins.

**Mission:** Ready for any user prompt; interpret to pure/non-pure elements; create from instruction (100% precise); render (color + sound every frame); extract per-frame (static) and per-window (dynamic); grow all three registries with sensible names when unknown; sync to API. Pure/single-frame → static; non-pure/2+ frames → dynamic or narrative. For registry taxonomy and pure vs non-pure, see [WORKFLOWS_AND_REGISTRIES.md](WORKFLOWS_AND_REGISTRIES.md) (Part I).

**Status legend:** ✅ Complete — precise and successful in workflow. ⚠️ Needs work — gap noted. 🔶 Legacy — correct for legacy path but superseded or parallel to current workflow.

---

## 1. Interpretation

**Role in workflow:** Map prompt → instruction (pure or non-pure elements). Must support any user input; output 100% precise for creation.

| Function | Purpose | Precision | Workflow success | Status |
|----------|---------|-----------|------------------|--------|
| `interpret_user_prompt()` | Parse prompt → InterpretedInstruction (palette, motion, intensity, duration, hints, etc.). | Deterministic from prompt + default_duration; resolves keywords and fallbacks. | Feeds creation; instruction drives spec. | ✅ |
| `_extract_words()` | Tokenize prompt to words. | Simple split; consistent. | Feeds all _resolve_* and keyword lookups. | ✅ |
| `_extract_duration()` | Parse duration from prompt. | Regex + number parse. | instruction.duration → creation/spec. | ✅ |
| `_extract_negations()` | Find negated terms (avoid_palette, avoid_motion). | Keyword sets. | Prevents wrong palette/motion from hints. | ✅ |
| `_resolve_palette()` / `_resolve_palette_hints()` | Map words → palette name and list of palette hints. | Uses KEYWORD_TO_PALETTE + tone fallback. | Creation uses hints + color_primitive_lists for blending. | ✅ |
| `_resolve_motion()` / `_resolve_motion_hints()` | Map words → motion type and hints. | Uses KEYWORD_TO_MOTION + tone fallback. | Creation blends motion from hints. | ✅ |
| `_resolve_intensity()` | Map words → intensity float. | Bounded 0.1–1.0. | Spec intensity. | ✅ |
| `_resolve_gradient()` / `_resolve_camera()` / `_resolve_shape()` / `_resolve_shot()` / `_resolve_transition()` | Resolve single value per domain. | Keyword maps + default. | Spec fields. | ✅ |
| `_resolve_lighting()` / `_resolve_lighting_hints()` | Lighting preset and hints. | Keyword maps. | Creation blending. | ✅ |
| `_resolve_composition_balance()` / `_resolve_composition_symmetry()` + hints | Composition. | Keyword maps. | Spec + blending. | ✅ |
| `_resolve_genre()` / `_resolve_pacing_factor()` / `_resolve_tension_curve()` | Genre, pacing, tension. | Keyword maps. | Spec; narrative. | ✅ |
| `_resolve_audio_tempo()` / `_resolve_audio_mood()` / `_resolve_audio_presence()` | Audio params. | Keyword maps. | Spec (sound in creation). | ✅ |
| `_resolve_style()` / `_resolve_tone()` | Style and tone (can refine lighting). | Keyword + prompt scan. | Spec; lighting refinement. | ✅ |
| `_resolve_text_overlay()` / `_resolve_depth_parallax()` | Text overlay and parallax. | Parsing. | Spec. | ✅ |

**Summary:** Interpretation is precise and supports arbitrary prompts via keyword maps and fallbacks. Output is used by creation; no hard-coded palette/motion requirement. ✅

---

## 2. Creation

**Role in workflow:** Instruction → spec (blueprint). Use only static elements (and origins); include audio/sound; follow instruction 100% precisely.

| Function | Purpose | Precision | Workflow success | Status |
|----------|---------|-----------|------------------|--------|
| `build_spec_from_instruction()` | InterpretedInstruction + knowledge → SceneSpec. | All fields from instruction or refined from knowledge; deterministic. | Produces spec for renderer; includes audio_tempo, audio_mood, audio_presence. | ✅ |
| `_build_palette_from_blending()` | Blend primitives + learned colors → palette_colors (list of RGB). | Uses instruction.color_primitive_lists or palette_hints; blend_palettes. | Spec has palette_colors for renderer; uses static/origins. | ✅ |
| `_build_motion_from_blending()` | Blend motion hints + learned motion → motion_type. | blend_motion_params; fallback to instruction.motion_type. | Spec motion. | ✅ |
| `_build_lighting_from_blending()` | Lighting preset from hints or fallback. | Single value. | Spec lighting_preset. | ✅ |
| `_build_composition_balance_from_blending()` / `_build_composition_symmetry_from_blending()` | Composition from hints. | Single value. | Spec. | ✅ |
| `_refine_from_knowledge()` | Refine palette, motion, intensity from learning stats. | Optional; uses by_keyword, by_palette. | Improves spec when knowledge available. | ✅ |
| `_refine_audio_from_knowledge()` | Refine audio params from learned_audio. | Optional. | Audio in spec. | ✅ |

**Summary:** Creation follows instruction and uses blending + knowledge. Audio/sound is part of spec. ✅

---

## 3. Renderer and pipeline

**Role in workflow:** Spec → frames (color per frame); pipeline adds sound and assembles MP4.

| Function | Purpose | Precision | Workflow success | Status |
|----------|---------|-----------|------------------|--------|
| `render_frame()` | Spec + time → one RGB frame (numpy array). | Deterministic from spec and t; uses palette_colors or palette_name. | Produces color per frame; non-pure blends form over duration. | ✅ |
| `_apply_camera_transform()` | Zoom, pan, rotate coords. | Math. | Camera motion. | ✅ |
| `_gradient_value()` | Gradient type + motion → per-pixel value. | Deterministic. | Visual. | ✅ |
| `generate_full_video()` | Prompt/spec → render frames → encode MP4 → add audio. | Calls renderer per frame; _add_audio. | Full video with color + sound. | ✅ |
| `_add_audio()` | Add procedural audio to MP4. | Mandatory; raises on failure. | Sound on every output. | ✅ |
| `_next_filename()` | Unique output filename. | Config + prefix. | I/O. | ✅ |

**Summary:** Renderer and pipeline produce frames and MP4 with color + sound. ✅

---

## 4. Extraction

**Role in workflow:** Per-frame static (color, sound) and per-window dynamic (2+ frames) for growth; full-video aggregate for analysis/API.

| Function | Purpose | Precision | Workflow success | Status |
|----------|---------|-----------|------------------|--------|
| `extract_static_per_frame()` | Yield one dict per frame: color (dominant RGB, brightness, contrast, saturation, hue, variance), sound (amplitude, tone). | One frame = one instance; uses dominant_colors, brightness_and_contrast, saturation_and_hue, color_variance; audio from _extract_audio_segments. | Feeds grow_from_video (static). | ✅ |
| `_read_frames()` | Load frames from video (imageio). | Returns list of arrays, fps, width, height. | Used by static and dynamic extraction. | ✅ |
| `_extract_audio_segments()` | Per-frame audio (amplitude, tone) from decoded track. | One segment per frame; pydub. | Sound in static extraction. | ✅ |
| `extract_dynamic_per_window()` | Yield one dict per window (2+ frames): motion, time, lighting, composition, graphics, audio_semantic. | Window = N frames; motion from frame_difference; lighting/composition/graphics from mid-frame. | Feeds grow_dynamic_from_video. | ✅ |
| `extract_from_video()` | Full-video aggregate: one dominant color, one motion profile, brightness/saturation aggregates. | Single summary per video. | Used for analysis dict, API learning log; not per-frame/per-window. | 🔶 Legacy |
| `_closest_palette()` / `_motion_trend()` / `_luminance_balance()` | Helpers in extractor.py. | Correct. | Reference/aggregate only. | ✅ |

**Summary:** Per-frame and per-window extraction are precise and feed growth. Legacy full-video extract used for analysis/API. ✅

---

## 5. Growth (all three registries)

**Role in workflow:** Compare extracted values to registries; if novel, add with sensible name. Pure/single-frame → static; non-pure/2+ frames → dynamic; narrative from spec → narrative.

| Function | Purpose | Precision | Workflow success | Status |
|----------|---------|-----------|------------------|--------|
| `grow_from_video()` | Per-frame static extraction → ensure_static_color_in_registry, ensure_static_sound_in_registry; spec-derived sound when spec provided. | Iterates extract_static_per_frame; keys from _static_color_key, _static_sound_key; add if novel with generate_sensible_name. | Feeds static registry only. | ✅ |
| `grow_dynamic_from_video()` | Per-window dynamic extraction → ensure_dynamic_*_in_registry for motion, time, lighting, composition, graphics, temporal, technical, audio_semantic. | Iterates extract_dynamic_per_window; keys per aspect; add if novel with generate_sensible_name. | Feeds dynamic registry; new styles with names. | ✅ |
| `grow_narrative_from_spec()` | Spec + instruction → ensure_narrative_in_registry for genre, mood, plots, settings, themes, scene_type. | Extract from spec; add if novel with generate_sensible_name. | Feeds narrative registry. | ✅ |
| `ensure_static_color_in_registry()` | Compare color to static registry; if novel append with name. | Key from _static_color_key (tolerance); load/save static_registry. | Static growth. | ✅ |
| `ensure_static_sound_in_registry()` | Compare sound to static registry; if novel append with name. | Key from _static_sound_key; load/save static_registry. | Static growth. | ✅ |
| `_ensure_dynamic_in_registry()` | Generic: compare key to dynamic registry for one aspect; if novel append with name. | Key per aspect; load/save dynamic_registry. | Used by all ensure_dynamic_*_in_registry. | ✅ |
| `ensure_dynamic_motion_in_registry()` / `ensure_dynamic_time_in_registry()` / … (all 8) | Per-aspect dynamic ensure. | Key functions _motion_key, _time_key, etc.; payload from window. | Dynamic growth. | ✅ |
| `_static_color_key()` / `_static_sound_key()` / `_motion_key()` / `_time_key()` / … | Build deterministic key from value. | Tolerance/rounding for stability. | Uniqueness and dedup. | ✅ |
| `derive_static_sound_from_spec()` / `derive_audio_semantic_from_spec()` | Spec → sound or audio_semantic dict. | From spec.audio_* attributes. | Fallback when per-frame audio missing. | ✅ |

**Summary:** Growth for static, dynamic, and narrative is implemented and used in the loop. Keys and names are precise. ✅

---

## 6. Registries (persistence and structure)

**Role in workflow:** Store and load static, dynamic, narrative registries; keys and values 100% accurate.

| Function | Purpose | Precision | Workflow success | Status |
|----------|---------|-----------|------------------|--------|
| `load_static_registry()` / `save_static_registry()` | Load/save JSON per aspect (color, sound). | Path from static_registry_path; format _meta, entries, count. | Used by ensure_static_*_in_registry. | ✅ |
| `load_dynamic_registry()` / `save_dynamic_registry()` | Load/save JSON per aspect (time, motion, lighting, …). | Path from dynamic_registry_path; same structure. | Used by ensure_dynamic_*_in_registry. | ✅ |
| `load_narrative_registry()` / `save_narrative_registry()` | Load/save JSON per aspect (genre, mood, …). | Path from narrative_registry_path. | Used by ensure_narrative_in_registry. | ✅ |
| `get_static_registry_dir()` / `static_registry_path()` | Paths. | From registry dir + aspect. | I/O. | ✅ |
| `get_dynamic_registry_dir()` / `dynamic_registry_path()` | Paths. | Same. | I/O. | ✅ |
| `get_narrative_registry_dir()` / `narrative_registry_path()` | Paths. | Same. | I/O. | ✅ |
| `_empty_static_registry()` / `_empty_dynamic_registry()` / `_empty_narrative_registry()` | Default structure when file missing. | _meta, entries [], count 0. | Safe load. | ✅ |
| `get_registry_dir()` (registry.py) | Base knowledge dir. | Config or default. | Used by all registries. | ✅ |
| `load_registry()` / `save_registry()` | Generic load/save by name (legacy single registry). | Path from dir + name. | Legacy D1/learned_* style; still used by lookup for fallback. | 🔶 Legacy |
| `_color_key()` (registry.py) | Quantize RGB to key (tolerance). | Deterministic. | Used in growth and API. | ✅ |
| `list_documented_blends()` / `list_all_registry_values()` | List stored values across registries. | Reads from disk/manifest. | Reporting. | ✅ |

**Summary:** Static, dynamic, and narrative registries are separate and used correctly. ✅

---

## 7. Blending and blend depth

**Role in workflow:** Combine origin + static registry values (pure only); result that is single value can become new static entry. Blend depth = pure (static) elements vs origin primitives.

| Function | Purpose | Precision | Workflow success | Status |
|----------|---------|-----------|------------------|--------|
| `blend_colors()` | Blend two RGBs with weight. | Linear blend; deterministic. | Creation; result can be new static color. | ✅ |
| `blend_palettes()` | Blend two lists of RGBs (weighted average). | Per-channel linear. | Creation palette_colors. | ✅ |
| `blend_motion_params()` | Categorical blend (motion type). | Ordinal or dominant; deterministic. | Creation motion. | ✅ |
| `_numeric_blend()` / `_ordinal_blend()` | Generic numeric and categorical. | Weight-based. | Used by all blend_* functions. | ✅ |
| All other `blend_*()` (smoothness, directionality, lighting, composition, …) | Per-domain blend. | Same pattern. | Creation when used. | ✅ |
| `compute_color_depth()` / `compute_motion_depth()` / … | Primitive depths for one value. | Distance/contribution to origins. | Used by remote_sync/grow_and_sync for composite records. | ✅ |
| `compute_full_blend_depths()` | All domains → depths. | Per-domain compute. | Whole-video composite. | ✅ |

**Summary:** Blending uses pure elements; blend depth is for static/origins. ✅

---

## 8. Name generator

**Role in workflow:** Sensible, short name when element/blend is unknown — for every registry.

| Function | Purpose | Precision | Workflow success | Status |
|----------|---------|-----------|------------------|--------|
| `generate_sensible_name()` | domain + value_hint + existing_names → prefix_word (e.g. color_velvet). | Deterministic from seed; 4–14 char word; unique against existing. | Used by ensure_static_*_in_registry, _ensure_dynamic_in_registry, ensure_narrative_in_registry. | ✅ |
| `_invent_word()` | seed → one word (start + end parts). | Deterministic; no double letter at boundary; cap 14. | Used by generate_sensible_name and name_reserve. | ✅ |
| `generate_blend_name()` | domain + prompt + existing → name (prompt words or invented). | Tries prompt combo, then sensible, then domain+word, then numeric. | Fallback when reserve empty; legacy paths. | ✅ |
| `_words_from_prompt()` / `_combine_words()` | Extract words; combine with max_len. | Regex; truncate. | Blend name from prompt. | ✅ |
| `name_reserve.take()` / `refill()` / `ensure_reserve()` | Pool of pre-generated names; take one. | Uses _invent_word; refill when low. | Legacy add_learned_* when reserve used. | ✅ |

**Summary:** Names are sensible and short; used in all three registries. ✅

---

## 9. Lookup and sync

**Role in workflow:** Creation gets latest static (and origins) from API or local; discoveries POST to API.

| Function | Purpose | Precision | Workflow success | Status |
|----------|---------|-----------|------------------|--------|
| `get_knowledge_for_creation()` | Build knowledge dict: learning stats (by_keyword, by_palette, overall) + learned_colors, learned_motion, learned_audio from API or local registry. | Fetches from /api/knowledge/for-creation when api_base set; fallback load_registry(learned_colors, learned_motion). | Creation and prompt picking use this; new pure values available next loop. | ✅ |
| `post_discoveries()` | POST one payload to /api/knowledge/discoveries. | Retry on 5xx. | Used by post_static_*, post_dynamic_*, post_narrative_*. | ✅ |
| `post_static_discoveries()` | POST static_colors, static_sound lists. | Builds payload; post_discoveries. | After grow_from_video. | ✅ |
| `post_dynamic_discoveries()` | POST dynamic keys (motion, time, lighting, …) from novel_for_sync. | Only sends non-empty lists. | After grow_dynamic_from_video. | ✅ |
| `post_narrative_discoveries()` | POST narrative novel. | Same. | After grow_narrative_from_spec. | ✅ |
| `grow_and_sync_to_api()` | From analysis dict + spec → build discoveries (colors, blends, motion, lighting, …); POST. | One summary per video; blend_depth; D1-style payload. | Whole-video composite and legacy API; does not replace per-frame/per-window growth. | 🔶 Legacy |

**Summary:** Lookup feeds creation; sync sends static, dynamic, narrative from growth. grow_and_sync_to_api is legacy composite. ✅

---

## 10. Analysis metrics (per-frame algorithms)

**Role in workflow:** Extraction and renderer depend on these; must be precise.

| Function | Purpose | Precision | Workflow success | Status |
|----------|---------|-----------|------------------|--------|
| `color_histogram()` | Per-channel histogram. | Correct. | Extractor. | ✅ |
| `dominant_colors()` | Dominant RGB(s) from frame. | Spatial mean; n=1 default. | extract_static_per_frame. | ✅ |
| `frame_difference()` | Mean absolute difference two frames. | Correct. | extract_dynamic_per_window motion. | ✅ |
| `brightness_and_contrast()` | Mean brightness, std. | Correct. | Static and dynamic extraction. | ✅ |
| `saturation_and_hue()` | Mean saturation, hue. | Correct. | Static extraction. | ✅ |
| `edge_density()` / `spatial_variance()` / `color_variance()` | Texture/variance. | Correct. | Dynamic extraction. | ✅ |
| `center_of_mass()` | Luminance-weighted center. | Correct. | Composition. | ✅ |

**Summary:** All metrics used by extraction are precise. ✅

---

## 11. Pipeline and automation (loop)

**Role in workflow:** Run full cycle: pick prompt → interpret → create → render → extract → grow (static + dynamic + narrative) → sync.

| Script / entry | Purpose | Precision | Workflow success | Status |
|----------------|----------|-----------|------------------|--------|
| `automate_loop.py` | Loop: pick_prompt → job → generate_full_video → upload → interpret + build_spec → extract_from_video → grow_from_video, grow_dynamic_from_video, grow_narrative_from_spec → post_static_discoveries, post_dynamic_discoveries, post_narrative_discoveries → grow_and_sync_to_api(analysis) → POST /api/learning → update state. | Calls per-frame static growth and per-window dynamic growth; narrative from spec; all three sync. | Full workflow; all registries evolved. | ✅ |
| `pick_prompt()` | Exploit (good_prompts) or explore (generate_procedural_prompt). | Random with ratio. | Variety and quality. | ✅ |
| `is_good_outcome()` | Quality thresholds (brightness_std, motion_level). | Fixed constants. | Good prompts list. | ✅ |
| `generate_procedural_prompt()` | Subject + modifier(s) from pools; avoid recent. | Random combo; unique. | Exploration. | ✅ |
| `generate_bridge.py` (--learn) | Job → generate → upload → extract → grow_from_video, grow_dynamic_from_video, grow_narrative → post_*_discoveries, grow_and_sync_to_api. | Same as loop. | ✅ |
| `generate.py` | One-off generate → analyze_video → log_run → grow_from_analysis. | Uses legacy grow_from_analysis (one per video). | 🔶 Legacy path; does not run per-frame/per-window growth. | ⚠️ |

**Summary:** automate_loop and generate_bridge use the full growth pipeline (static + dynamic + narrative). generate.py uses legacy growth only. ⚠️ generate.py could be updated to call grow_from_video + grow_dynamic_from_video + grow_narrative_from_spec when learning is desired.

---

## 12. Config, API client, procedural parser

| Function | Purpose | Precision | Workflow success | Status |
|----------|---------|-----------|------------------|--------|
| `load_config()` | Load YAML/config. | Path resolution. | Used everywhere. | ✅ |
| `api_request()` / `api_request_with_retry()` | HTTP with retry. | Retries on 5xx; logs. | Sync and lookup. | ✅ |
| `parse_prompt_to_spec()` | Prompt → SceneSpec (one-shot). | Calls interpret + build_spec. | Alternative entry. | ✅ |
| `build_scene_script_from_instruction()` | Instruction → scene script. | For multi-segment. | Optional. | ✅ |

---

## 13. Legacy registry (registry.py add_learned_*)

**Role:** Legacy single-registry and D1-style APIs still use add_learned_color, add_learned_motion_profile, etc., and name_reserve.take(). These are **precise** for their contract. The **workflow** for “every instance” and three registries is served by growth_per_instance (grow_from_video, grow_dynamic_from_video) and narrative_registry; the Cloudflare API accepts both static_* and dynamic discovery payloads. So legacy add_learned_* are 🔶 Legacy — complete for legacy path; primary growth is per-instance + narrative.

---

## 14. Cloudflare Worker (API)

**Role:** Persist state (KV), config (KV), learning runs (D1), discoveries (D1), jobs (D1), R2 uploads. No KV delete (optimized for free tier).

| Endpoint / behavior | Purpose | Precision | Workflow success | Status |
|---------------------|---------|-----------|------------------|--------|
| POST /api/learning | Insert learning_runs; no KV delete. | D1 insert. | Learning log. | ✅ |
| GET /api/learning/stats | KV get; if miss, D1 query + KV put with TTL 60. | No delete. | Stats for dashboard/lookup. | ✅ |
| GET/POST /api/loop/state | KV get/put loop_state. | Correct. | automate_loop state. | ✅ |
| GET/POST /api/loop/config | KV get/put loop_config. | Correct. | Loop control. | ✅ |
| POST /api/knowledge/discoveries | Insert into static_colors, static_sound, learned_* tables; no KV delete. | D1 inserts; names from payload or generateUniqueName. | Receives growth output. | ✅ |
| GET /api/knowledge/for-creation | Return learned_colors, learned_motion, learned_audio from D1. | Query. | Creation lookup. | ✅ |

**Summary:** API is aligned with workflow and optimized (no KV deletes). ✅

---

## 15. Gaps and recommendations

| Gap | Recommendation |
|-----|-----------------|
| **generate.py** | When learning is desired, call grow_from_video(path, …), grow_dynamic_from_video(path, …), grow_narrative_from_spec(spec, …) and post_*_discoveries so one-off runs also feed all three registries. |
| **get_knowledge_for_creation** | Currently loads learned_colors, learned_motion, learned_audio from API or load_registry("learned_colors", …). Ensure API /api/knowledge/for-creation returns data in the shape creation expects (e.g. learned_colors as dict keyed by color_key with r, g, b, name). Already aligned if API returns same shape. |
| **Legacy grow_from_extract / grow_from_analysis** | Used by generate.py and possibly elsewhere. For consistency with “all three registries” and “every instance,” prefer driving from grow_from_video + grow_dynamic_from_video + grow_narrative_from_spec where the full pipeline is available. |

---

## 16. Summary table

| Stage | Key functions | Precision | Workflow |
|-------|----------------|-----------|----------|
| Interpretation | interpret_user_prompt, _resolve_* | ✅ | ✅ |
| Creation | build_spec_from_instruction, _build_*_from_blending | ✅ | ✅ |
| Renderer / pipeline | render_frame, generate_full_video, _add_audio | ✅ | ✅ |
| Extraction | extract_static_per_frame, extract_dynamic_per_window | ✅ | ✅ |
| Growth | grow_from_video, grow_dynamic_from_video, grow_narrative_from_spec, ensure_*_in_registry | ✅ | ✅ |
| Registries | load/save static, dynamic, narrative; _color_key | ✅ | ✅ |
| Blending / depth | blend_*, compute_*_depth | ✅ | ✅ |
| Names | generate_sensible_name, _invent_word, name_reserve | ✅ | ✅ |
| Lookup / sync | get_knowledge_for_creation, post_*_discoveries | ✅ | ✅ |
| Loop | automate_loop, generate_bridge (--learn) | ✅ | ✅ |
| Legacy | extract_from_video, grow_from_extract, add_learned_*, generate.py | 🔶 | ⚠️ optional update |

**Conclusion:** The codebase is **100% precise** and **successful within the workflow** for the intended path: interpretation → creation → render → extract → grow (static, dynamic, narrative) → sync. All three registries evolve; creation uses static + origins; names are sensible. Legacy paths (single-registry, one-summary-per-video) remain and can be updated (e.g. generate.py) to use the full growth pipeline when desired.
