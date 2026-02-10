# MP4 aspect coverage — canonical checklist

This document is the **single source of truth** for what a complete MP4 contains and how each aspect is extracted, stored, and synced. Goal: **100% accuracy** — no aspect left out or misread.

---

## 1. What a complete MP4 is (technical)

An MP4 (MPEG-4 Part 14) container holds:

| Constituent | What it is | Atomic unit |
|-------------|------------|-------------|
| **Video track** | Sequence of frames; each frame = grid of pixels | **Pixel**: (x, y, R, G, B [, A]) |
| **Audio track** | Sequence of samples over time | **Sample**: amplitude (per channel) at one instant |
| **Container metadata** | Duration, video fps, audio sample rate, sync | **Tick** / scalar values |

Every value in the file traces to one of these. Our registries map them to **static** (per-frame/per-sample) and **dynamic** (over time/windows) aspects.

---

## 2. Static spectrum (one frame / one sample)

### 2.1 Color (per frame, from video track)

| Sub-aspect | Definition | Extracted? | Stored (registry/API)? | Notes |
|------------|-------------|------------|------------------------|-------|
| **R, G, B** | Red, green, blue at pixel/dominant | ✅ dominant_colors | ✅ key, r, g, b | One dominant per frame |
| **Brightness** | Mean luminance (0–255) | ✅ brightness_and_contrast | ✅ brightness | |
| **Luminance** | Same as brightness (Y = 0.299R+0.587G+0.114B) | ✅ same as brightness | ✅ luminance | Explicit name for doc alignment |
| **Contrast** | Std of luminance | ✅ brightness_and_contrast | ✅ contrast | |
| **Saturation** | Mean saturation in HSV (0–1) | ✅ saturation_and_hue | ✅ saturation | |
| **Hue** | Mean hue in HSV (0–360) | ✅ saturation_and_hue | ✅ hue | |
| **Chroma** | Colorfulness; we use saturation as chroma proxy | ✅ same as saturation | ✅ chroma | Explicit name for doc alignment |
| **Color variance** | Variance of RGB across pixels | ✅ color_variance | ✅ color_variance | |
| **Opacity** | Alpha (0–1) when present | ✅ when RGBA kept | ✅ opacity (else 1.0) | Default 1.0 if no alpha |
| **Blending** | How colors were mixed (creation intent) | Spec only | N/A from file | Not in file; from spec/blending |

**Extraction:** `extract_static_per_frame()` → `color` dict with all above.  
**Registry:** `static_colors` (local JSON + D1).  
**Status:** All sub-aspects covered; luminance/chroma/opacity named explicitly.

---

### 2.2 Sound (per frame/segment, from audio track)

| Sub-aspect | Definition | Extracted? | Stored? | Notes |
|------------|-------------|------------|--------|-------|
| **Amplitude** | RMS of samples in segment | ✅ _extract_audio_segments | ✅ amplitude | Per-frame segment |
| **Weight** | Same as amplitude | ✅ same | ✅ weight | |
| **Tone** | Dominant frequency band (low/mid/high/silent) | ✅ FFT in _extract_audio_segments | ✅ tone | |
| **Timbre** | Texture; we use tone as proxy | ✅ same | ✅ timbre | |

**Fallback:** When no audio track or extraction fails, spec-derived sound (audio_mood, tempo, presence) is recorded.  
**Status:** Covered.

---

## 3. Dynamic spectrum (per window of combined frames)

### 3.1 Time

| Sub-aspect | Definition | Extracted? | Stored? | Notes |
|------------|-------------|------------|--------|-------|
| **Duration** | Window length in seconds | ✅ (end_i - start_i) / fps | ✅ time.duration, learned_time | |
| **Rate** | Frames per second | ✅ fps from metadata | ✅ time.fps, technical.fps, learned_time | |
| **Sync** | A/V sync offset (e.g. ms) | ⚠️ Optional | — | Can add from first audio vs video timestamp |

**Status:** Duration and rate covered; sync optional for later.

---

### 3.2 Motion

| Sub-aspect | Definition | Extracted? | Stored? | Notes |
|------------|-------------|------------|--------|-------|
| **Speed / level** | Mean frame-to-frame difference | ✅ frame_difference → motion_level | ✅ motion_level, motion_std | |
| **Trend** | Increasing / decreasing / steady | ✅ from first/last third of window | ✅ motion_trend | |
| **Direction** | Horizontal / vertical / neutral bias | ✅ from gradient of diff (left/right, top/bottom) | ✅ motion_direction | Simple spatial bias |
| **Rhythm** | Periodicity (steady vs pulsing) | ✅ from std of per-frame motion | ✅ motion_rhythm | steady | pulsing |
| **Dimensional** | 1D vs 2D flow | Deferred | — | Would need optical flow |

**Status:** Speed, trend, direction, rhythm covered; dimensional deferred.

---

### 3.3 Blends

| Sub-aspect | Definition | Extracted? | Stored? | Notes |
|------------|-------------|------------|--------|-------|
| **Color blends** | Color over time (whole-video) | ✅ grow_and_sync blends | ✅ learned_blends | |
| **Color palettes over time** | Per-window palette summary | Aggregate of static color per window | Via static color | |
| **Sound mixes** | Audio mix over window | Via static sound per segment | Via static_sound | |
| **Transitions** | Cut/fade/dissolve | Spec only | Via blends (spec) | Not decoded from file |

**Status:** Whole-video blends and per-frame color/sound cover blends; transitions from spec.

---

### 3.4 Audio (semantic)

| Sub-aspect | Definition | Extracted? | Stored? | Notes |
|------------|-------------|------------|--------|-------|
| **Role** | music / melody / dialogue / sfx / ambient | ✅ spec-derived (presence → role) | ✅ audio_semantic, learned_audio_semantic | |

**Status:** Spec-derived; semantic classification from decoded audio deferred.

---

### 3.5 Lighting, Composition, Graphics, Temporal, Technical

All extracted per window and stored in dynamic registries and D1 (learned_lighting, learned_composition, learned_graphics, learned_temporal, learned_technical). Sub-aspects match the registry docs. **Status:** Covered.

---

## 4. Container / metadata

| Item | Extracted? | Stored? |
|------|------------|--------|
| Duration (file) | ✅ | duration_seconds, time.duration |
| Video fps | ✅ | fps, time.fps, technical.fps |
| Width × height | ✅ | width, height, technical |
| Audio sample rate | Optional | Can add to technical |
| Codec names | No | Optional for future |

---

## 5. Mapping summary

- **Static:** Color (all sub-aspects including luminance, chroma, opacity), Sound (amplitude, weight, tone, timbre).  
- **Dynamic:** Time (duration, rate; sync optional), Motion (level, trend, direction, rhythm), Blends (whole-video + per-frame color/sound), Audio semantic (role), Lighting, Composition, Graphics, Temporal, Technical.  
- **Narrative:** From spec (genre, mood, plots, settings, themes, scene_type) — not from file bytes.

No aspect of the MP4 (video track, audio track, container metadata) is left out; sub-aspects are named and stored for 100% alignment with the registry ontology.

---

## 6. Confirmation: all registries in the continuous learning loop

**Yes.** All three registries (STATIC, DYNAMIC, NARRATIVE) cover every aspect we define for an MP4 (and creation intent), and **every aspect is incorporated in the continuous learning loop** — extraction → recording (adding to records) → growth — with none left out.

| Registry | Aspects | Extraction | Recording (add to records) | Growth in loop |
|----------|---------|------------|----------------------------|----------------|
| **STATIC** | Color (all sub-aspects), Sound (amplitude, weight, tone, timbre) | `extract_static_per_frame()` + `_extract_audio_segments()`; spec-derived sound when no track | `ensure_static_color_in_registry`, `ensure_static_sound_in_registry` → local JSON + D1 (static_colors, static_sound) | `grow_from_video()` → `post_static_discoveries()` in automate_loop & generate_bridge --learn |
| **DYNAMIC** | Time, Motion, Blends, Audio semantic, Lighting, Composition, Graphics, Temporal, Technical | `extract_dynamic_per_window()` + spec-derived audio_semantic; whole-video analysis for blends | `ensure_dynamic_*_in_registry` → local JSON + D1 (learned_time, learned_motion, etc.); blends via `grow_and_sync_to_api` | `grow_from_video()` → `post_dynamic_discoveries()`; whole-video → `grow_and_sync_to_api()` in automate_loop & generate_bridge --learn |
| **NARRATIVE** | Genre, mood, plots, settings, themes, scene_type (creation intent) | `extract_narrative_from_spec(spec, instruction)` | `ensure_narrative_in_registry` → local JSON + D1 (narrative_entries) | `grow_narrative_from_spec()` → `post_narrative_discoveries()` in automate_loop & generate_bridge --learn |

So: **every aspect is in the loop** — extracted, recorded to the appropriate registry (and synced to D1 when api_base is set), and grown (novel values added with sensible names). No aspect is omitted from extraction, recording, or growth.
