# MP4 aspects — complete coverage and frame/window model

This document is the **single source of truth** for what a complete MP4 contains, how each aspect is extracted and stored, and how static vs dynamic vs narrative are separated. Goal: **100% accuracy** — no aspect left out or misread.

---

## 1. Frame and window model

Each generated video is:

1. **Divided into frames** — Each frame is one instant (one image, one moment of sound). These are the **static** instances: color and sound per frame.
2. **Divided into windows** — A **window** is a group of **combined frames** over a fixed duration (e.g. **1 second**). Over that window we get **dynamic** instances: motion, color palettes over time, music, dialogue, SFX, speed, lighting over time, etc.

So: **static elements live inside each frame; dynamic elements are what appear when those frames are merged/combined over time.**

---

## 2. What a complete MP4 is (technical)

An MP4 (MPEG-4 Part 14) container holds:

| Constituent | What it is | Atomic unit |
|-------------|------------|-------------|
| **Video track** | Sequence of frames; each frame = grid of pixels | **Pixel**: (x, y, R, G, B [, A]) |
| **Audio track** | Sequence of samples over time | **Sample**: amplitude (per channel) at one instant |
| **Container metadata** | Duration, video fps, audio sample rate, sync | **Tick** / scalar values |

Every value in the file traces to one of these. Our registries map them to **static** (per-frame/per-sample), **dynamic** (over time/windows), and **narrative** (film/story aspects from spec).

---

## 3. Static spectrum (one frame / one sample)

### 3.1 Color (per frame, from video track)

**Static holds pure elements only.** R, G, B, opacity are stored in the static registry. Brightness, luminance, contrast, saturation, hue, chroma are **not** static categories — they are **dynamic (lighting)** or used only for depth computation.

| Sub-aspect | Definition | Extracted? | Stored in STATIC? | Notes |
|------------|-------------|------------|-------------------|-------|
| **R, G, B** | Red, green, blue at pixel/dominant | ✅ dominant_colors | ✅ key, r, g, b | One dominant per frame; pure only |
| **Opacity** | Alpha (0–1) when present | ✅ when RGBA kept | ✅ opacity (else 1.0) | |
| **Brightness, Luminance, Contrast, Saturation, Hue, Chroma** | Derived from frame | ✅ brightness_and_contrast, saturation_and_hue | ❌ → **DYNAMIC (lighting)** | Not static; per-window lighting stored in dynamic |

**Extraction:** `extract_static_per_frame()` → `color` dict (extractor still computes brightness/saturation for downstream use). **Registry:** `static_colors` stores only key, r, g, b, opacity, name, count, sources (local JSON + D1).

### 3.2 Sound (per frame/segment, from audio track — pure at sample/beat level)

| Sub-aspect | Definition | Extracted? | Stored in STATIC? | Notes |
|------------|-------------|------------|-------------------|-------|
| **Amplitude, Weight** | RMS of samples in segment | ✅ _extract_audio_segments | ✅ amplitude, weight | Per-frame segment |
| **Tone, Timbre** | Dominant frequency band / texture | ✅ FFT in _extract_audio_segments | ✅ tone, timbre | Beat-level primitives (kick, snare, bass, etc.) seeded in static |

**Spec-derived** (audio_mood, tempo, presence) is **non-pure** and is recorded in **dynamic (audio_semantic)**, not static. **Registry:** `static_sound` (pure only); primitives include silence, kick, snare, hihat, clap, bass, pad, lead, pluck, noise, pulse, sustain, melody, chord, vocal, speech, ambient, music, sfx, mood variants.

---

## 4. Dynamic spectrum (per window of combined frames)

### 4.1 Time

| Sub-aspect | Definition | Extracted? | Stored? |
|------------|-------------|------------|--------|
| **Duration** | Window length in seconds | ✅ (end_i - start_i) / fps | ✅ time.duration, learned_time |
| **Rate** | Frames per second | ✅ fps from metadata | ✅ time.fps, technical.fps |
| **Sync** | A/V sync offset | ⚠️ Optional | — |

### 4.2 Motion

| Sub-aspect | Definition | Extracted? | Stored? |
|------------|-------------|------------|--------|
| **Speed / level** | Mean frame-to-frame difference | ✅ frame_difference → motion_level | ✅ motion_level, motion_std |
| **Trend** | Increasing / decreasing / steady | ✅ from first/last third of window | ✅ motion_trend |
| **Direction** | Horizontal / vertical / neutral bias | ✅ from gradient of diff | ✅ motion_direction |
| **Rhythm** | Periodicity (steady vs pulsing) | ✅ from std of per-frame motion | ✅ motion_rhythm |

### 4.3 Full dynamic coverage: lighting, composition, graphics, temporal, technical, transition, depth

- **Lighting:** Brightness, contrast, saturation (and key_intensity, color_temperature) over the window — **not** static; stored in dynamic (learned_lighting).
- **Audio (semantic):** Role, mood, tempo, presence; spec-derived and user-facing (gradient backgrounds, melodies, duration); stored in audio_semantic. Unrecognized values get a generated name.
- **Composition, Graphics, Temporal, Technical:** Extracted per window; stored in dynamic registries and D1.
- **Transition:** Cut, fade, dissolve, wipe (type + duration); stored in dynamic when present.
- **Depth:** Parallax strength, layer count; stored in dynamic when present.

Sub-aspects and categories match [REGISTRIES.md](REGISTRIES.md). Every category is present so the program is prepared for any prompt and new dynamic blends.

---

## 5. Container / metadata

| Item | Extracted? | Stored? |
|------|------------|--------|
| Duration (file) | ✅ | duration_seconds, time.duration |
| Video fps | ✅ | fps, time.fps, technical.fps |
| Width × height | ✅ | width, height, technical |
| Audio sample rate | Optional | Can add to technical |
| Format, codec, bitrate, keyframes, chapters | No / optional | Technical metadata; not in registry |

---

## 6. Narrative (film aspects — from spec)

Themes, plots, settings, genre, mood, scene type are **not physical** (not a single pixel or sample) but are **present in the video** as film/story elements. They are recorded in the **narrative** registry from **spec** (and prompt), not from file bytes.

| Aspect | Description | Registry |
|--------|-------------|----------|
| **Themes** | What the video is “about” (e.g. nature, hope) | **Narrative** |
| **Plots** | Story structure (arc, beat, tension) | **Narrative** |
| **Settings** | Where/when (place, era, environment) | **Narrative** |
| **Genre** | Category (e.g. drama, documentary) | **Narrative** |
| **Mood** | Emotional tone (e.g. calm, tense) | **Narrative** |
| **Scene type** | Indoor, outdoor, abstract | **Narrative** |

Same process: if value not in registry → add it; if unnamed → name-generator or existing public name. See [REGISTRIES.md](REGISTRIES.md).

---

## 7. Mapping summary and loop confirmation

- **Static:** Color (all sub-aspects), Sound (amplitude, weight, tone, timbre).  
- **Dynamic:** Time (duration, rate; sync optional), Motion (level, trend, direction, rhythm), Blends (whole-video + per-frame color/sound), Audio semantic (role), Lighting, Composition, Graphics, Temporal, Technical.  
- **Narrative:** From spec (genre, mood, plots, settings, themes, scene_type) — not from file bytes.

**All three registries are incorporated in the continuous learning loop** — extraction → recording → growth — with none left out.

| Registry | Extraction | Recording | Growth in loop |
|----------|------------|-----------|----------------|
| **STATIC** | `extract_static_per_frame()` + `_extract_audio_segments()`; spec-derived sound when no track | `ensure_static_color_in_registry`, `ensure_static_sound_in_registry` → local JSON + D1 | `grow_from_video()` → `post_static_discoveries()` |
| **DYNAMIC** | `extract_dynamic_per_window()` + spec-derived audio_semantic; whole-video analysis for blends | `ensure_dynamic_*_in_registry` → local JSON + D1; blends via `grow_and_sync_to_api` | `grow_dynamic_from_video()` → `post_dynamic_discoveries()`; whole-video → `grow_and_sync_to_api()` |
| **NARRATIVE** | `extract_narrative_from_spec(spec, instruction)` | `ensure_narrative_in_registry` → local JSON + D1 | `grow_narrative_from_spec()` → `post_narrative_discoveries()` |

See also [REGISTRIES.md](REGISTRIES.md), [WORKFLOWS_AND_REGISTRIES.md](WORKFLOWS_AND_REGISTRIES.md).
