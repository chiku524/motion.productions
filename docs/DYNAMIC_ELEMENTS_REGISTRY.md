# Dynamic Elements Registry

**Combined frames = one instance (e.g. 1 second).** The dynamic registry holds **lenient non-pure blends** — time-bound products that form as blending happens over a time-frame: time, motion, audio_semantic (music, ambience, etc.), lighting, composition, graphics, temporal, technical. **Blends is not a category here**; purely blended single-value results go to the static registry (color or sound). This document defines every such instance per window. For the definitive mapping, see [REGISTRY_TAXONOMY.md](REGISTRY_TAXONOMY.md). For the static registry (pure + purely blended single-value), see [STATIC_ELEMENTS_REGISTRY.md](STATIC_ELEMENTS_REGISTRY.md). For a short overview, see [REGISTRY_README.md](REGISTRY_README.md).

**Accuracy vs precision:** Registries must be **100% accurate** (what we record). Algorithms and functions live in **scripts and code** and must be **100% precise**; they are not stored in the registries.

---

## 0. Project goal: record every instance & utilize the name-generator

**Goal:** Record **every instance** of **dynamic** (lenient non-pure) elements that appear inside **every instance of combined frames** (e.g. 1 full second of frame instances).

- **Per window (combined frames):** If a dynamic value (motion, music, ambience, lighting, etc.) is not in the registry → **record it**. If it has no official name → use the **name-generator** so names are **sensible** (readable, consistent).

**Dynamic registry:** Time, Motion, Audio (semantic), Lighting, Composition, Graphics, Temporal, Technical. No "blends" category. Record novel values; use name-generator when unnamed.

**Name-generator:** Same as static — produces sensible, human-readable names (e.g. `motion_softdrift`, `audio_sfx_impact`). Implemented in `src/knowledge/blend_names.py`.

---

## 1. Static vs dynamic (different goals, same process)

| Registry | Unit | Goal |
|----------|------|------|
| **Static** | **One frame** | Record every **color** and **sound** instance per frame. |
| **Dynamic** | **Combined frames** (e.g. 1 second) | Record every **motion**, **music**, **SFX**, **color palettes over time**, etc. per window. |

Process is almost identical: **if value not in registry → add it; if unnamed → name-generator.** Only the **unit** (frame vs window) and the **aspects** (static vs dynamic list) differ.

---

## 2. Registry organization (easy to read)

- **Location:** `knowledge/dynamic/`
- **Files:** `dynamic_time.json`, `dynamic_motion.json`, `dynamic_audio_semantic.json`, `dynamic_lighting.json`, `dynamic_composition.json`, `dynamic_graphics.json`, `dynamic_temporal.json`, `dynamic_technical.json`
- **Format:** Each file has:
  - `_meta` — registry type, goal, aspect description, sub-aspects (for readers)
  - `entries` — list of recorded values; each entry includes key, value, name, count, sources
  - `count` — number of entries

**Default window:** 1 second of combined frames (configurable via `DEFAULT_DYNAMIC_WINDOW_SECONDS` in `src/knowledge/dynamic_registry.py` and extraction calls).

Code: `src/knowledge/dynamic_registry.py` — `load_dynamic_registry()`, `save_dynamic_registry()`, `DYNAMIC_ASPECTS`.

---

## 3. Complete list of aspects (dynamic only)

Every aspect of a complete video that belongs in the **dynamic** registry (combined frames) is listed below. All must be recorded.

| Aspect | Sub-aspects | Description |
|--------|-------------|-------------|
| **Time** | duration, rate, sync | Measurement over the window (segment length, fps, sync). |
| **Motion** | speed, direction, rhythm, dimensional | Change from frame to frame (motion level, trend, flow). |
| **Audio (semantic)** | music, ambience, melody, dialogue, sfx | Role/type of audio: music, ambience, melody, dialogue, SFX. |
| **Lighting** | brightness, contrast, saturation | Lighting over the window (derived from frames). |
| **Composition** | center_of_mass, balance, luminance_balance | Composition over the window. |
| **Graphics** | edge_density, spatial_variance, busyness | Graphics/texture over the window. |
| **Temporal** | pacing, motion_trend, shot_length, cut_frequency | Temporal pacing and trend. |
| **Technical** | width, height, fps | Resolution and fps for the window. |

**Static** covers only **color** and **sound** per frame. Everything above is **dynamic** (per combined frames).

---

## 4. Extraction process

Target **every window of combined frames** (e.g. 1 second). For each window:

1. Extract motion (level, std, trend), time (duration, fps), lighting, composition, graphics, temporal, technical.
2. Extract audio semantic (music, ambience, melody, dialogue, SFX) when audio extraction is implemented.
3. For each value not already in the dynamic registry → add it; if unnamed → assign a name via the name-generator.

Code: `src/knowledge/extractor_per_instance.py` — `extract_dynamic_per_window()` yields one dict per window with all dynamic aspects (audio_semantic placeholder until implemented).

---

## 5. Mapping to Code

The dynamic registry is implemented in `src/knowledge/dynamic_registry.py`. Per-window extraction is in `src/knowledge/extractor_per_instance.py`. Growth and loop wiring (compare each window to registry, add novel values, write to dynamic JSON) are the target next steps.

For an audit of every function and algorithm (complete vs needs work), see [REGISTRY_AND_LOOP_AUDIT.md](REGISTRY_AND_LOOP_AUDIT.md).
