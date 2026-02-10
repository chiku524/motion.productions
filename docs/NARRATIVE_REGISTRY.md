# Narrative registry — themes, plots, settings

**Non-pure imaginable blends for time-frames within the video.** This registry holds aspects that pertain to **time-frames** and are **imaginable** (plot, setting, theme, mood, genre, scene type, script) — the story/creative layer. It is distinct from the static registry (pure + purely blended single-value color/sound) and the dynamic registry (lenient non-pure time-bound: motion, music, lighting, etc.). For the definitive mapping of every MP4 element into the three registries, see [REGISTRY_TAXONOMY.md](REGISTRY_TAXONOMY.md).

**Accuracy vs precision:** Registries must be **100% accurate** (what we record). Algorithms and functions live in **scripts and code** and must be **100% precise**; they are not stored in the registries.

---

## 0. Goal

Record every instance of **narrative** elements that appear in a video (or in a segment/window):

- **Themes** — what the video is “about” (e.g. nature, loss, hope).
- **Plots** — story structure (arc, beat, tension, e.g. rise, climax, resolution).
- **Settings** — where/when (place, era, environment: e.g. city, night, forest).
- **Genre** — category (e.g. drama, documentary).
- **Mood** — emotional tone (e.g. calm, tense).
- **Scene type** — kind of scene (e.g. indoor, outdoor, abstract).

Same process as static and dynamic: **if value not in registry → add it; if unnamed → use the name-generator (or its already-public name).**

---

## 1. Separation from static and dynamic

| Registry   | What it holds |
|-----------|----------------|
| **Static**   | Pure + purely blended single-value per frame: color, sound (one frame = one instance). |
| **Dynamic** | Lenient non-pure over time: motion, music, ambience, lighting, composition, etc. (combined frames = one instance). |
| **Narrative** | Non-pure imaginable film aspects: themes, plots, settings, genre, mood, scene type. |

Static and dynamic are about **measurable** pixels/samples and their combination over time. Narrative is about **meaning** and **story** — things that are present in the video but not defined by a single pixel or sample.

---

## 2. Registry organization (easy to read)

- **Location:** `knowledge/narrative/`
- **Files:** `narrative_themes.json`, `narrative_plots.json`, `narrative_settings.json`, `narrative_genre.json`, `narrative_mood.json`, `narrative_scene_type.json`
- **Format:** Same pattern as static/dynamic: `_meta` (goal, aspect, description), `entries`, `count`.

Code: `src/knowledge/narrative_registry.py` — `load_narrative_registry()`, `save_narrative_registry()`, `NARRATIVE_ASPECTS`. “Add if not found” and extraction (from prompt/spec or future semantic analysis) to be wired when we add narrative discovery to the loop.

---

## 3. Extraction

Narrative aspects are not derived from per-frame or per-window pixel/audio metrics alone. They can come from:

- **User prompt / spec** — e.g. “serene forest at dusk” → theme, setting.
- **Downstream analysis** — e.g. scene classification, mood detection (when we add it).
- **Manual or curated tags** — when we support tagging.

So extraction for the narrative registry is **separate** from `extract_static_per_frame` and `extract_dynamic_per_window`; it will plug in once we have prompt/spec parsing or semantic analysis.

---

## 4. Summary

The narrative registry gives a **distinct place** for themes, plots, settings, and related film aspects. Same add-if-not-found and name-generator process; different content (non-physical, story/meaning) and different extraction source (prompt, spec, or future semantic tools).

---

## 5. How to fill the narrative registry

### Sources

1. **User prompt + parsed instruction (InterpretedInstruction)** — Palette hints, style, tone, keywords.
2. **Creation spec (SceneSpec)** — After building from instruction: `genre`, `tension_curve`, `audio_mood`, `lighting_preset`, `shot_type`, `camera_motion`, `transition_in`/`out`.
3. **Future:** Semantic analysis (scene type, mood from pixels/audio), manual tags.

### Elements to focus (priority)

| Aspect       | Source (current)                    | Example values                          |
|-------------|--------------------------------------|-----------------------------------------|
| **Genre**   | `spec.genre` / instruction           | general, documentary, thriller, ad, tutorial, educational |
| **Mood**    | `spec.audio_mood`, instruction.tone/style | neutral, calm, tense, uplifting, dark, dreamy, moody |
| **Plots**   | `spec.tension_curve`                 | flat, slow_build, standard, immediate   |
| **Settings**| Prompt keywords + `lighting_preset`, `shot_type` | forest, city, night, golden_hour, indoor, outdoor |
| **Themes**  | Prompt keywords, palette_hints       | nature, ocean, abstract, minimal        |
| **Scene type** | Inferred from shot_type / keywords | indoor, outdoor, abstract                |

### Flow

1. After each video is created we have a **spec** (and the **prompt**). Run **extract_narrative_from_spec(spec, prompt)** to get a dict: `{ "genre": ["documentary"], "mood": ["calm"], "plots": ["standard"], "settings": ["golden_hour"], "themes": ["nature"], "scene_type": ["outdoor"] }` (or similar).
2. For each aspect and each value: **ensure_narrative_in_registry(aspect, value, source_prompt=prompt)**. If the value is not in that aspect’s registry → add it; if unnamed → assign a name via the name-generator (or keep the existing public name, e.g. `documentary`, `calm`).
3. Optionally sync narrative discoveries to the API (D1) when `api_base` is set, same pattern as static/dynamic.

Code: `src/knowledge/narrative_registry.py` — `extract_narrative_from_spec(spec, prompt=..., instruction=...)`, `ensure_narrative_in_registry(aspect, value, ...)`, `grow_narrative_from_spec(spec, prompt=..., config=..., instruction=...)`. Wired in the learn path: `scripts/generate_bridge.py --learn` calls `grow_narrative_from_spec(spec, prompt=prompt, config=config, instruction=instruction)` after each video so every generated video feeds the narrative registry.

---

## 6. Mission alignment

The narrative registry fits the same **mission** as static and dynamic: record every relevant element of a complete video. Static = every color and sound per frame; dynamic = every motion, music, SFX, color palettes, etc. per window; **narrative** = every theme, plot, setting, genre, mood, scene type present in the video. Same process: **novel → add; unnamed → name-generator (or existing public name).**
