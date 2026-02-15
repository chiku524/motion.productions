# Registries — overview, taxonomy, and where things live

All registries fit the **overall mission**: record every element of a complete video so the loop can learn and reuse discoveries.

- **Registries** must be **100% accurate** (what we record). They live in JSON/D1; they may reference algorithms but do not contain them.
- **Algorithms and functions** must be **100% precise** (how we compute). They live in **scripts and code**, not in the registries.

**Foundation:** [REGISTRY_FOUNDATION.md](REGISTRY_FOUNDATION.md) defines four registries, depth_breakdown rules, and name-generator (semantic/name-like). **100% precise & accurate.**

**Rule:** Every element fits into one of **four** registries: Pure (Static), Blended (Dynamic/Temporal), Semantic (Narrative), Interpretation (human input resolved). See [REGISTRY_FOUNDATION.md](REGISTRY_FOUNDATION.md) for **categories vs elements** (categories are what elements fit into; elements are the named entries with depth_breakdown).

---

## 1. The four registries (Pure, Blended, Semantic, Interpretation)

| Registry | Role | What it holds |
|----------|------|----------------|
| **STATIC** | **Pure elements only** — single frame, single pixel/sample. | **Color** (R, G, B, **opacity** — each opaqueness level gets a **name**). **Sound** = **actual sound noises** (named); **low/mid/high** are **measurements** (frequency band), not primitive names; each entry has **name** + **strength_pct** + **depth_breakdown**. Kick, snare, bass, melody, etc. are **not** here — they are Blended. |
| **DYNAMIC** (Blended) | **Non-pure** — time (frames) and/or **distance** (e.g. gradient). | **Categories** (role, mood, tempo, gradient_type, motion_type, …) that **elements** fit into. **Elements** = time, motion, gradient, camera, audio_semantic (kick, snare, bass, ambient, …), lighting, composition, graphics, temporal, technical, transition, depth. Each element has **name** + **depth_breakdown**. |
| **NARRATIVE** (Semantic) | Same idea as Blended: **blends** in **categories** (plot, setting, dialogue, …) using time/distance. | **Categories**: genre, mood, themes, plots, settings, style, scene type. **Elements** = named entries with **depth_breakdown** where applicable. |
| **Interpretation** | Program deals with **unknown** until user sends input; this registry prepares for **everything and anything**. | Prompt → instruction (palette, motion, gradient, camera, mood, etc.). D1 `interpretations`; already-known interpretations. |

---

## 2. Where things live

- **Static registry** → `knowledge/static/`  
  - `static_colors.json`, `static_sound.json` (local); D1 `static_colors`, `static_sound`.
- **Dynamic registry** → `knowledge/dynamic/`  
  - `dynamic_time.json`, `dynamic_motion.json`, `dynamic_audio_semantic.json`, `dynamic_lighting.json`, `dynamic_composition.json`, `dynamic_graphics.json`, `dynamic_temporal.json`, `dynamic_technical.json` (local); D1 `learned_*` tables and `learned_blends`.
- **Narrative registry** → `knowledge/narrative/`  
  - Themes, plots, settings, genre, mood, style, scene type (local); D1 `narrative_entries`.
- **Interpretation registry** → D1 table `interpretations` (prompt, instruction_json, status). Human input resolved into elements; referenced by GET /api/knowledge/for-creation as `interpretation_prompts`.

Each file is **human-readable JSON**: `_meta` describes the registry and aspect; `entries` holds the recorded values; `count` is the number of entries.

**D1 migrations:** From repo root run `python scripts/run_d1_migrations.py` (or `bash scripts/run_d1_migrations.sh`). See [DEPLOY_CLOUDFLARE.md](DEPLOY_CLOUDFLARE.md).

---

## 3. Pure vs non-pure and depth

**Pure → STATIC:** Single frame, single pixel (or single sample). One frame cannot output gradient or motion as a single pixel.

- **Static registry** holds **pure** discoveries only: per-frame color (R, G, B, opacity) and per-frame **actual sound noises** (named; **strength_pct** recorded; low/mid/high are **measurements**, not primitive names). **Brightness, luminance, contrast, saturation** are **not** static — they live in **dynamic (lighting)**. Kick, snare, bass, melody, speech, etc. are **Blended** (dynamic) elements, not pure.
- **Primitives (origin values)** are the starting point. **Static**: full color set (black, white, red, green, blue, …); sound = **silence** + noise types (e.g. rumble, tone, hiss). **Dynamic**: gradient, camera, transition origins; **elements** (including kick, snare, bass, ambient, etc.) fit into **categories** (role, mood, tempo, …). **Narrative**: categories (genre, plot, setting, dialogue, …); elements are named entries.

**Non-pure → DYNAMIC + NARRATIVE:** Multi-frame or imaginable blends. Gradient, motion, camera, lighting, transition, depth, audio_semantic (mood/tempo) live in dynamic. Narrative holds themes, plots, settings, genre, mood, style, scene_type.

**Depth %:** Pure blends store **depth_breakdown** = weights/densities of other pure elements. Dynamic entries use `primitive_depths` where available.

**Discovery every run:** Every loop run calls `grow_all_from_video()` (static + dynamic in one pass: primitives seeded, then per-frame color + sound, per-window motion, time, **gradient**, **camera**, lighting, composition, graphics, temporal, technical, **audio_semantic**, transition, depth) and `grow_narrative_from_spec()` (narrative: primitives seeded, then spec/prompt values). New non-pure blends (e.g. new gradient type or camera motion from a window) are recorded whenever the window extraction produces a novel key.

---

## 4. Exhaustive category list per registry

### STATIC — pure elements only (no brightness/contrast/saturation; those are dynamic)

| Category | Sub-aspects | What is recorded |
|----------|-------------|-------------------|
| **Color** | R, G, B, opacity, depth_breakdown | Pure color per frame (dominant RGB). Pure blends record depth % = weights of other pure colors. **Every color primitive** is seeded: black, white, red, green, blue, yellow, cyan, magenta, orange, purple, pink, aqua, brown, navy, teal, lime, olive, maroon, coral, gold, violet, indigo, salmon, crimson, beige, tan, ivory, silver, gray, etc. |
| **Sound** | noise, strength_pct, amplitude, tone, timbre, depth_breakdown | **Actual sound noises** (named). **low/mid/high** are **measurements** (frequency band); **strength_pct** is recorded per entry. Primitives = silence + rumble, tone, hiss. Kick, snare, bass, melody, etc. → **dynamic** audio_semantic. |

**Primitives:** `STATIC_COLOR_PRIMITIVES` (60+ named colors) and `STATIC_SOUND_PRIMITIVES` (silence + rumble/tone/hiss at strength bands) in `static_registry.py`; seeded at start of `grow_all_from_video()` via `ensure_static_primitives_seeded()`.

**Code:** `src/knowledge/static_registry.py`, `extract_static_per_frame()`, `ensure_static_color_in_registry()`, `ensure_static_sound_in_registry()`.

### DYNAMIC — lenient non-pure (time-bound)

| Category | Sub-aspects | What is recorded |
|----------|-------------|-------------------|
| **Time** | duration, rate, sync | Per-window duration, fps, sync; novel values added. |
| **Motion** | speed, direction, rhythm, trend | Per-window motion; novel values added. |
| **Gradient** | gradient_type, strength | Inferred from frame luminance (vertical/horizontal/angled) + strength; novel values added. |
| **Camera** | motion_type, speed | Inferred from window motion (static/pan/tilt/zoom); novel values added. |
| **Audio (semantic)** | role, mood, tempo, presence | Role (music/ambient/sfx) and **spec-derived** mood + tempo; one entry per combo (e.g. ambient_neutral_medium). |
| **Lighting** | brightness, contrast, saturation | Lighting over the window; novel values added. |
| **Composition** | center_of_mass, balance, luminance_balance | Spatial distribution over the window; novel values added. |
| **Graphics** | edge_density, spatial_variance, busyness | Texture/graphics over the window; novel values added. |
| **Temporal** | pacing, motion_trend, cut_frequency, shot_length | Pacing and trend; novel values added. |
| **Technical** | width, height, fps, aspect_ratio | Resolution and frame rate; novel values added. |
| **Transition** | type, duration | Cut, fade, dissolve, wipe between segments; novel values added. |
| **Depth** | parallax_strength, layer_count | Depth/realism over the window; novel values added. |

**Primitives:** Gradient, camera, transition, and audio_semantic (one per presence: silence, ambient, music, sfx, full) origins are seeded at start of `grow_all_from_video()` via `ensure_dynamic_primitives_seeded()`. Motion/lighting/composition/etc. are discovery-only (no discrete origin list seeded).

**Code:** `extract_dynamic_per_window()` (gradient_direction + camera inference + lighting, etc.), `grow_all_from_video()`. Whole-video composites in `learned_blends`.

### NARRATIVE — every film aspect (full prompt coverage)

| Category | What is recorded |
|----------|-------------------|
| **Genre** | Value from spec; novel → add. |
| **Mood** | Value from spec/instruction; novel → add. |
| **Plots** | Value from spec (e.g. tension_curve); novel → add. |
| **Settings** | Value from spec + prompt keywords; novel → add. |
| **Themes** | Value from spec/instruction; novel → add. |
| **Style** | Visual/narrative style (cinematic, abstract, minimal, etc.); novel → add. |
| **Scene type** | Value from spec; novel → add. |

**Primitives:** Genre, mood (tone), style, plots (tension_curve), settings, themes, scene_type from `NARRATIVE_ORIGINS` in `origins.py`; seeded via `ensure_narrative_primitives_seeded()` at start of `grow_narrative_from_spec()`.

**Code:** `src/knowledge/narrative_registry.py` — `grow_narrative_from_spec()`, `ensure_narrative_in_registry()`.

---

## 5. Verification: every element → one registry

| MP4 constituent | Registry | Category |
|------------------|----------|----------|
| Pixel value (R,G,B,A and derived); purely blended color → single value | STATIC | Color |
| Audio sample (amplitude; tone/timbre); purely blended sound → single value | STATIC | Sound |
| Duration, fps, sync over a window | DYNAMIC | Time |
| Frame-to-frame change (motion over time) | DYNAMIC | Motion |
| Music, ambience, dialogue, SFX (semantic role over window) | DYNAMIC | Audio (semantic) |
| Lighting, composition, graphics, temporal, technical over window | DYNAMIC | (respective) |
| Gradient type + strength over window (extracted) | DYNAMIC | Gradient |
| Camera motion over window (extracted) | DYNAMIC | Camera |
| Brightness, contrast, saturation over window | DYNAMIC | Lighting |
| Transition (cut, fade, dissolve, wipe) | DYNAMIC | Transition |
| Parallax, layer count over window | DYNAMIC | Depth |
| Spec-derived mood + tempo (intended audio) | DYNAMIC | Audio (semantic) |
| Genre, mood, plots, settings, themes, style, scene type (story layer) | NARRATIVE | (respective) |

---

## 6. Accuracy vs precision

| | Where it lives | Requirement |
|--|----------------|-------------|
| **Accuracy** | **Registries** (JSON, D1) | What we record must correctly reflect the category and value. Registries may **reference** algorithms but do not contain the logic. |
| **Precision** | **Algorithms and functions** (`src/`, `scripts/`) | How we extract, key, and grow must be well-defined and consistent. Logic resides in code, not in registry files. |

---

## 7. Name-generator and extraction

**Name-generator:** All new discoveries get a **sensible, short name** (e.g. `color_velvet`, `motion_drift`). See [NAME_GENERATOR.md](NAME_GENERATOR.md).

**Extraction process:**

1. **Static:** Primitives are seeded first (`ensure_static_primitives_seeded`). For each **frame**, extract color and sound (from decoded audio: amplitude, tone). For each value not in the static registry → add it and assign a name. Spec-derived sound is **not** added to static; it goes to dynamic audio_semantic.
2. **Dynamic:** Primitives (gradient, camera, transition) seeded first via `ensure_dynamic_primitives_seeded()`. For each **window**, extract motion, time, gradient, camera, **lighting** (brightness, contrast, saturation), composition, graphics, temporal, technical, transition, depth. When spec is present, add audio_semantic (role + mood + tempo). Every novel non-pure value → add with generated name when unrecognized. All via `grow_all_from_video()`.
3. **Narrative:** Primitives from NARRATIVE_ORIGINS seeded first. From spec (and prompt); `grow_narrative_from_spec()` adds genre, mood, themes, plots, settings, **style**, scene_type.

Code: `src/knowledge/extractor_per_instance.py`, `growth_per_instance.py`, `narrative_registry.py`, `static_registry.py` (STATIC_*_PRIMITIVES).

---

## See also

- **[REGISTRY_FOUNDATION.md](REGISTRY_FOUNDATION.md)** — Authoritative foundation: four registries, depth_breakdown, name-generator (semantic/name-like), 100% precise & accurate.
- **[LOOP_STANDARDS.md](LOOP_STANDARDS.md)** — Set algorithms and functions for interpretation loop (language standard) and video loop (MP4 aspects); both grow from origin/primitive + extracted values.
- [NAME_GENERATOR.md](NAME_GENERATOR.md) — Algorithm for sensible, semantic or name-like short names.
- [MP4_ASPECTS.md](MP4_ASPECTS.md) — Every aspect of a complete MP4; frame/window model.
- [WORKFLOWS_AND_REGISTRIES.md](WORKFLOWS_AND_REGISTRIES.md) — Colors and audio; workflow details.
- [ALGORITHMS_AND_FUNCTIONS_AUDIT.md](ALGORITHMS_AND_FUNCTIONS_AUDIT.md) — Audit of extraction, growth, and registry functions.
