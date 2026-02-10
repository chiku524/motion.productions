# Registry taxonomy — every element of a complete MP4

This document is the **definitive mapping** of every element a fully complete MP4 video consists of into the three registries.

- **Registries** must be **100% accurate** (what we record). They reside in the registry store (JSON, D1); they can reference algorithms and functions but do not contain them.
- **Algorithms and functions** must be **100% precise** (how we compute). They reside in **scripts and code**, not in the registries.

---

## 1. The three registries and their roles

| Registry | Role | What it holds |
|----------|------|----------------|
| **STATIC** | **Pure elements** and **purely blended elements that become a single value**. | **2 categories only:** **color** and **sound**. Every pixel is color; every audio sample is sound. When blending (within any category) produces a **single value** (e.g. one new RGB, one new sound profile), that result is a **newly discovered pure element** and is recorded here under color or sound, with a generated name if unnamed. |
| **DYNAMIC** | **Lenient non-pure blends** — products that form as blending happens **over time**, within a time-frame (or entire duration). | Time, motion, music/ambience (audio_semantic), lighting, composition, graphics, temporal, technical. These are **non-pure** blends: they are time-bound and do not reduce to a single color or single sound. **Blends is not a category here**; successful single-value blends go to static. |
| **NARRATIVE** | **Non-pure imaginable blends** — story/creative aspects for time-frames. | Plot, setting, theme, mood, genre, scene type (and script via source_prompt). Imaginable rather than purely measurable. |

**Rule:** Every element of a complete MP4 fits into exactly one of these three. Purely blended single-value results → static (color or sound). Lenient time-bound non-pure → dynamic. Imaginable non-pure → narrative.

---

## 2. Exhaustive category list per registry

### 2.1 STATIC registry — pure elements and purely blended single-value elements

**Two categories only: color, sound.** Both **pure** instances (per frame/sample) and **purely blended** results that become a single value are recorded here. If a blend yields one new color or one new sound profile, it is added to the static registry under the appropriate category and given a name if unnamed.

| Category | Sub-aspects | What is recorded |
|----------|-------------|-------------------|
| **Color** | R, G, B, brightness, luminance, contrast, saturation, chroma, hue, color_variance, opacity | Pure colors per frame and **purely blended colors that resolve to a single value** (new discovery). Every instance not already in the registry is added; unnamed → name-generator. |
| **Sound** | amplitude, weight, tone, timbre | Pure sound per frame/segment and **purely blended sound that resolves to a single value** (new discovery). Every instance not already in the registry is added; unnamed → name-generator. |

**Files:** `static_colors.json`, `static_sound.json` (local); D1 `static_colors`, `static_sound`.  
**Code (precision):** Extraction and growth algorithms live in `src/knowledge/` (e.g. `extract_static_per_frame()`, `ensure_static_color_in_registry()`, `ensure_static_sound_in_registry()`). Registries only store the resulting values; they do not contain the algorithms.

---

### 2.2 DYNAMIC registry — lenient non-pure blends (time-bound)

**No “blends” category.** Categories here are **lenient** non-pure products that form over a time-frame (e.g. one second or the full duration): motion, music, ambience, lighting over the window, composition, graphics, temporal pacing, technical. These are not single color/sound values; they are time-bound phenomena.

| Category | Sub-aspects | What is recorded |
|----------|-------------|-------------------|
| **Time** | duration, rate, sync | Per-window duration, fps (rate), optionally sync; novel values added. |
| **Motion** | speed (level), direction, rhythm, trend | Per-window motion (non-pure, time-bound); novel values added. |
| **Audio (semantic)** | music, ambience, melody, dialogue, sfx | Role of audio over the window (music, ambience, etc.); novel values added. |
| **Lighting** | brightness, contrast, saturation | Lighting over the window (non-pure, time-bound); novel values added. |
| **Composition** | center_of_mass, balance, luminance_balance | Spatial distribution over the window; novel values added. |
| **Graphics** | edge_density, spatial_variance, busyness | Texture/graphics over the window; novel values added. |
| **Temporal** | pacing, motion_trend | Pacing and trend over the window; novel values added. |
| **Technical** | width, height, fps | Resolution and frame rate for the window; novel values added. |

**Files:** `dynamic_time.json`, `dynamic_motion.json`, `dynamic_audio_semantic.json`, `dynamic_lighting.json`, `dynamic_composition.json`, `dynamic_graphics.json`, `dynamic_temporal.json`, `dynamic_technical.json` (local); D1 `learned_time`, `learned_motion`, `learned_audio_semantic`, `learned_lighting`, `learned_composition`, `learned_graphics`, `learned_temporal`, `learned_technical`.  
**Code (precision):** Extraction in `extract_dynamic_per_window()`; growth in `ensure_dynamic_*_in_registry()`. Registries store values only.

**Composite records (not a registry category):** Whole-video composite records (e.g. “this run had color X + motion Y”) are stored in `learned_blends` (D1) for loop use. These are **not** a dynamic registry category; they are references/composites used by the workflow.

---

### 2.3 NARRATIVE registry — non-pure imaginable blends

Aspects that pertain to **time-frames** and are **imaginable** (plot, setting, theme, mood): the story/creative layer.

| Category | What is recorded |
|----------|-------------------|
| **Genre** | Value from spec; novel → add. |
| **Mood** | Value from spec/instruction; novel → add. |
| **Plots** | Value from spec (e.g. tension_curve); novel → add. |
| **Settings** | Value from spec + prompt keywords; novel → add. |
| **Themes** | Value from spec/instruction; novel → add. |
| **Scene type** | Value from spec; novel → add. |

**Script:** Narrative text (prompt/script) is recorded as `source_prompt` on registry entries. Registries can reference this; precise handling is in code.

**Files:** `knowledge/narrative/` per aspect (local); D1 `narrative_entries`.  
**Code (precision):** `extract_narrative_from_spec()`, `ensure_narrative_in_registry()` in `src/knowledge/narrative_registry.py`.

---

## 3. Accuracy vs precision

| | Where it lives | Requirement |
|--|----------------|--------------|
| **Accuracy** | **Registries** (JSON files, D1 tables) | 100% accurate. What we record must correctly reflect the category and value. Registries may **reference** algorithms and functions but do not contain the logic. |
| **Precision** | **Algorithms and functions** (scripts and code under `src/`, `scripts/`) | 100% precise. How we extract, key, and grow must be well-defined and consistent. This logic resides in code, not in the registry files. |

---

## 4. Verification: every element → one registry

| MP4 constituent | Registry | Category |
|-----------------|----------|----------|
| Pixel value (R,G,B,A and derived); purely blended color → single value | STATIC | Color |
| Audio sample (amplitude; tone/timbre); purely blended sound → single value | STATIC | Sound |
| Duration, fps, sync over a window | DYNAMIC | Time |
| Frame-to-frame change (motion over time) | DYNAMIC | Motion |
| Music, ambience, dialogue, SFX (semantic role over window) | DYNAMIC | Audio (semantic) |
| Lighting over window | DYNAMIC | Lighting |
| Composition over window | DYNAMIC | Composition |
| Graphics over window | DYNAMIC | Graphics |
| Temporal pacing over window | DYNAMIC | Temporal |
| Width, height, fps of the stream | DYNAMIC | Technical |
| Genre, mood, plots, settings, themes, scene type (story layer) | NARRATIVE | Genre, Mood, Plots, Settings, Themes, Scene type |

Every element of a fully complete MP4 fits into one of these categories. Successful single-value blends → static (color or sound). Lenient time-bound non-pure → dynamic. Imaginable non-pure → narrative.
