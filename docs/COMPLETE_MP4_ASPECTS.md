# Complete MP4 aspects — nothing left out

This document lists **every aspect** that can be part of a complete MP4 video. There is a **distinct separation** between **static** (per frame/sample), **dynamic** (static elements combined over time), and **narrative** (themes, plots, settings — film aspects that are not physical but are present in videos).

---

## 0. Frame and window model

Each generated video is:

1. **Divided into frames** — Each frame is one instant (one image, one moment of sound). These are the **static** instances: color and sound per frame.
2. **Divided into windows** — A **window** is a group of **combined frames** over a fixed duration (e.g. **1 second**). That duration is **time**: a certain number of frames combined. Over that window we get **dynamic** instances: motion, color palettes over time, music, dialogue, SFX, speed, lighting over time, etc.

So: **static elements live inside each frame; dynamic elements are what appear when those frames are merged/combined over time.** Time is the duration that consists of those combined frames.

---

## 1. Container / file level

| Aspect | Description | Where we record |
|--------|-------------|------------------|
| **Duration** | Total length in time (seconds). | Dynamic (time), whole-video analysis. |
| **Format** | Container format (e.g. MP4). | Technical metadata; not in registry. |
| **Video codec** | e.g. H.264, VP9. | Technical; not in registry. |
| **Audio codec** | e.g. AAC. | Technical; not in registry. |
| **Bitrate** | Video/audio bitrate. | Technical; optional in registry. |
| **Keyframes** | Keyframe positions (seek points). | Temporal; could be dynamic. |
| **Chapters** | Chapter markers (if any). | Metadata; optional. |
| **Metadata** | Title, author, creation time. | Not in registry. |

---

## 2. Video track — per frame (static)

Single frame = one instance. These are the **static** aspects.

| Aspect | Sub-aspects | Description | Registry |
|--------|-------------|-------------|----------|
| **Color** | R, G, B, alpha, luminance, saturation, hue, brightness, contrast, variance | Pixel-level color. | **Static (color)** |
| **Opacity / alpha** | Per-pixel or frame-level transparency | Transparency. | Under color (static). |
| **Chroma** | Chrominance values | Color without luminance. | Under color. |
| **Luminance** | Light value (derived from color). | Under color. |

---

## 3. Video track — over time (dynamic)

Combined frames = one instance (e.g. 1 second). **Dynamic** aspects are **static elements merged/combined with one another** over that duration: color palettes over time, motion, speed, lighting over the window, etc. **Time** is the duration (e.g. 1 second) that consists of a certain amount of frames combined; that combination is what creates these dynamic elements.

| Aspect | Sub-aspects | Description | Registry |
|--------|-------------|-------------|----------|
| **Motion** | Speed, direction, rhythm, dimensionality | Change from frame to frame. | **Dynamic (motion)** |
| **Time (measurement)** | Duration, rate (fps), sync | How time is measured over the window. | **Dynamic (time)** |
| **Blends** | Color blends over time, color palettes over time, transitions, sound mixes | Mixtures across frames/samples. | **Dynamic (blends)** |
| **Lighting** | Brightness, contrast, saturation over window | Light character over the window. | **Dynamic (lighting)** |
| **Composition** | Center of mass, balance, luminance balance | Spatial balance over the window. | **Dynamic (composition)** |
| **Graphics / texture** | Edge density, spatial variance, busyness | Visual texture over the window. | **Dynamic (graphics)** |
| **Temporal** | Pacing, motion trend, shot length, cut frequency | Rhythm and editing. | **Dynamic (temporal)** |
| **Technical** | Width, height, fps for the window | Resolution and frame rate. | **Dynamic (technical)** |
| **Transitions** | Cut, fade, dissolve, wipe | How segments join. | Under blends or temporal. |
| **Cuts / edit points** | Where cuts occur | Edit structure. | Temporal. |
| **Color palettes over time** | Dominant colors across the window | Palette evolution. | **Dynamic (blends)** |

---

## 4. Audio track — per sample (static)

Single sample (or very short segment) = one instance. These are **static** sound.

| Aspect | Sub-aspects | Description | Registry |
|--------|-------------|-------------|----------|
| **Sound** | Amplitude, weight, tone, timbre | Sample-level audio. | **Static (sound)** |
| **Amplitude** | Level at one instant | Loudness at a point. | Under sound. |
| **Weight** | Perceived heaviness of the sample | Subjective level. | Under sound. |
| **Tone** | Pitch / tonal character | Under sound. |
| **Timbre** | Tonal color (e.g. bright, warm) | Under sound. |

---

## 5. Audio track — over time (dynamic)

Combined samples / segment = one instance. These are **dynamic** audio.

| Aspect | Sub-aspects | Description | Registry |
|--------|-------------|-------------|----------|
| **Audio (semantic)** | Music, melody, dialogue, SFX, silence, noise, ambience | Role/type of audio in the segment. | **Dynamic (audio_semantic)** |
| **Music** | Instrumental, vocal, genre hints | Musical content. | Under audio_semantic. |
| **Melody** | Melodic contour | Under audio_semantic. |
| **Dialogue** | Speech | Under audio_semantic. |
| **SFX** | Sound effects | Under audio_semantic. |
| **Silence** | Absence of sound | Under audio_semantic. |
| **Noise** | Unstructured sound (hiss, rumble) | Under audio_semantic. |
| **Sample rate / channels** | Technical audio spec | Technical; optional. |

---

## 6. Spatial / visual (frame or window)

| Aspect | Description | Static or dynamic |
|--------|-------------|-------------------|
| **Position** | Where things are in frame | Composition (dynamic). |
| **Scale** | Size of elements | Composition/graphics. |
| **Depth / perspective** | Z-order, parallax | Composition; future. |
| **Rule of thirds / balance** | Composition rules | Composition (dynamic). |
| **Center of mass** | Visual center | Composition (dynamic). |
| **Luminance balance** | Light distribution | Composition (dynamic). |

---

## 7. Narrative / film aspects (themes, plots, settings)

These are **not physical** (not a single pixel or sample) but are **present in the video** as film/story elements. They are recorded in a **separate registry** so they stay distinct from static (physical per frame) and dynamic (physical over time).

| Aspect | Sub-aspects | Description | Registry |
|--------|-------------|-------------|----------|
| **Themes** | Subject, idea, motif | What the video is “about” (e.g. nature, loss, hope). | **Narrative** |
| **Plots** | Arc, beat, tension | Story structure (e.g. rise, climax, resolution). | **Narrative** |
| **Settings** | Place, era, environment | Where/when the video is set (e.g. city, night, forest). | **Narrative** |
| **Genre** | Category (e.g. drama, documentary) | Narrative genre. | **Narrative** |
| **Mood** | Emotional tone (e.g. calm, tense) | Mood over the video or segment. | **Narrative** |
| **Scene type** | Indoor, outdoor, abstract | Kind of scene. | **Narrative** |

Same process as static and dynamic: if a value is not in the narrative registry → add it; if it has no name → use the name-generator (or its already-public name). See [NARRATIVE_REGISTRY.md](NARRATIVE_REGISTRY.md).

---

## 8. Summary: three registries

- **Static (one frame / one sample):** Color, Sound. Physical at a single instant.  
  → `knowledge/static/` (JSON) and D1 `static_colors`, `static_sound`.

- **Dynamic (combined frames / segment):** Time, Motion, Blends, Audio (semantic), Lighting, Composition, Graphics, Temporal, Technical. Physical elements merged over time (color palettes, songs, dialogue, motion, speed, etc.).  
  → `knowledge/dynamic/` (JSON) and D1 `learned_*`.

- **Narrative (themes, plots, settings):** Themes, plots, settings, genre, mood, scene type. Film aspects that are not physical but are present in the video.  
  → `knowledge/narrative/` (JSON) and (when implemented) D1 narrative tables.

Same process for all: **if value not in respective registry → add it; if unnamed → use name-generator or existing public name.**
