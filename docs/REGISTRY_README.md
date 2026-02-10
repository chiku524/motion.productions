# Registry overview — for readers and users

All registries fit the **overall mission** of this project: record every element of a complete video so the loop can learn and reuse discoveries.

- **Registries** must be **100% accurate** (what we record). They live in JSON/D1; they may reference algorithms but do not contain them.
- **Algorithms and functions** must be **100% precise** (how we compute). They live in **scripts and code**, not in the registries.

- **Static:** **Pure elements** and **purely blended elements that become a single value** — **color** and **sound** only. One frame = one instance; every pixel is color, every sample is sound. When blending yields one new color or one new sound, that result is recorded here with a name if unnamed.
- **Dynamic:** **Lenient non-pure blends** over time (time-bound): time, motion, music/ambience (audio_semantic), lighting, composition, graphics, temporal, technical. **Blends is not a category** here; successful single-value blends go to static.
- **Narrative:** **Non-pure imaginable blends** for time-frames: plot, setting, theme, mood, genre, scene type (and script via source_prompt).

**Definitive taxonomy:** Every element of a complete MP4 fits into one of these three. See **[REGISTRY_TAXONOMY.md](REGISTRY_TAXONOMY.md)** for the exhaustive category list and mapping.

---

## The three registries

| Registry | Target | Goal |
|----------|--------|------|
| **Static** | **Pure + purely blended single-value** — one frame = one instance | Exactly **2 categories:** **color** and **sound**. Record every pure instance and every purely blended result that becomes a single value; add novel; name when unnamed. See [REGISTRY_TAXONOMY.md](REGISTRY_TAXONOMY.md). |
| **Dynamic** | **Lenient non-pure** — combined frames = one instance | **Time**, **motion**, **audio (semantic)**, **lighting**, **composition**, **graphics**, **temporal**, **technical**. No "blends" category; single-value blends → static. Same process: add novel, name when unnamed. See [REGISTRY_TAXONOMY.md](REGISTRY_TAXONOMY.md). |
| **Narrative** | **Imaginable non-pure** for time-frames | **Genre**, **mood**, **plots**, **settings**, **themes**, **scene_type** (and script via source_prompt). Story/creative layer. Same process. See [NARRATIVE_REGISTRY.md](NARRATIVE_REGISTRY.md) and [REGISTRY_TAXONOMY.md](REGISTRY_TAXONOMY.md). |

---

## Where things live

- **Static registry** → `knowledge/static/`  
  - `static_colors.json` — color entries (per frame)  
  - `static_sound.json` — sound entries (per frame)  

- **Dynamic registry** → `knowledge/dynamic/`  
  - `dynamic_time.json`, `dynamic_motion.json`, `dynamic_audio_semantic.json`, `dynamic_lighting.json`, `dynamic_composition.json`, `dynamic_graphics.json`, `dynamic_temporal.json`, `dynamic_technical.json`  

- **Narrative registry** → `knowledge/narrative/` (when implemented)  
  - Themes, plots, settings, genre, mood, scene type — see [NARRATIVE_REGISTRY.md](NARRATIVE_REGISTRY.md).

Each file is **human-readable JSON**: `_meta` describes the registry and aspect; `entries` holds the recorded values; `count` is the number of entries.

**D1 migrations:** From repo root run `python scripts/run_d1_migrations.py` (or `bash scripts/run_d1_migrations.sh`). This applies all current and future migrations. See [DEPLOY_CLOUDFLARE.md](DEPLOY_CLOUDFLARE.md).

---

## Full list of aspects (complete video)

**Static (one frame):**

- **Color** — blending, opacity, chroma, luminance, hue, saturation, brightness, contrast  
- **Sound** — weight (amplitude), tone, timbre  

**Dynamic (combined frames — lenient non-pure only; no "blends" category):**

- **Time** — duration, rate, sync  
- **Motion** — speed, direction, rhythm, dimensional  
- **Audio (semantic)** — music, ambience, melody, dialogue, SFX  
- **Lighting** — brightness, contrast, saturation over the window  
- **Composition** — center of mass, balance, luminance balance  
- **Graphics** — edge density, spatial variance, busyness  
- **Temporal** — pacing, motion trend  
- **Technical** — width, height, fps  

---

## Name-generator

All new discoveries get a **sensible, short name** (e.g. `color_velvet`, `motion_drift`). Names resemble authentic words, are pleasant to the eye and ear, and are never lengthy or nonsensical. For the algorithm and functions, see **[NAME_GENERATOR.md](NAME_GENERATOR.md)**. See also [STATIC_ELEMENTS_REGISTRY.md](STATIC_ELEMENTS_REGISTRY.md) and [DYNAMIC_ELEMENTS_REGISTRY.md](DYNAMIC_ELEMENTS_REGISTRY.md).

---

## Extraction process

1. **Static:** For each **frame** of a video, extract color (and sound when available). For each value not in the static registry → add it and assign a name.  
2. **Dynamic:** For each **window** of combined frames (e.g. 1 second), extract motion, time, lighting, composition, graphics, etc. For each value not in the dynamic registry → add it and assign a name.

Code: `src/knowledge/extractor_per_instance.py` — `extract_static_per_frame()`, `extract_dynamic_per_window()`.

---

## Docs

- [NAME_GENERATOR.md](NAME_GENERATOR.md) — Name generator: algorithm, functions, and reserve (sensible short names for all registries).  
- [STATIC_ELEMENTS_REGISTRY.md](STATIC_ELEMENTS_REGISTRY.md) — Static registry: goal, scope, full aspect list, organization.  
- [DYNAMIC_ELEMENTS_REGISTRY.md](DYNAMIC_ELEMENTS_REGISTRY.md) — Dynamic registry: goal, scope, full aspect list, organization.  
- [NARRATIVE_REGISTRY.md](NARRATIVE_REGISTRY.md) — Narrative registry: themes, plots, settings (film aspects; distinct from static/dynamic).  
- [COMPLETE_MP4_ASPECTS.md](COMPLETE_MP4_ASPECTS.md) — Every aspect of a complete MP4; frame/window model; static vs dynamic vs narrative.  
- [REGISTRY_AND_LOOP_AUDIT.md](REGISTRY_AND_LOOP_AUDIT.md) — Audit of functions and algorithms (complete vs needs work).
