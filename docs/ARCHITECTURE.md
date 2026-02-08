# Architecture: Procedural Engine and Learning

This document describes how Motion implements the [core foundation](FOUNDATION.md): base knowledge of video aspects, continuous extraction via the loop, and video creation from user prompts. We use only our own algorithms and data — no external models.

---

## Foundation (Summary)

- **Base knowledge** — Everything in video files: colors, graphics, resolutions, motion, etc.
- **Extraction** — The loop extracts every aspect from base knowledge as it runs.
- **Creation** — Software produces videos from user text/script/prompt, informed by extracted knowledge.

See [docs/FOUNDATION.md](FOUNDATION.md) for the full statement.

---

## 1. Full Video from a Single Prompt

### User-facing behavior

- **Input:** A single text prompt (and optional duration, style, tone).
- **Output:** One video file. No scene list or manual combining.
- **Public API:** `generate(prompt, duration_seconds, ...) → path_to_video`.

### Pipeline layout

```
User: one prompt + optional duration/style
         │
         ▼
┌─────────────────────────────────────────┐
│  Prompt enrichment (optional)           │
│  Output: one enhanced prompt / config   │
└─────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│  Video generator                        │
│  • If duration ≤ one clip: 1 call → 1 file
│  • If duration > one clip: segments with temporal continuation
│    → concat → one file                  │
└─────────────────────────────────────────┘
         │
         ▼
One output video file
```

### Long-form (temporal continuation)

For durations longer than one model call, we generate segments that continue from each other, then concatenate into one file. The user never sees or manages separate clips.

---

## 2. No External Model

We do **not** use Runway, Replicate, PyTorch, diffusers, transformers, or any pre-trained neural nets. We build a **procedural engine** that uses only:

- **Our scripts and algorithms** — math, logic, procedural generation.
- **Our data** — palettes, keywords, motion curves, rules we define.
- **One exception:** Minimal encoding (imageio + FFmpeg) to write frames to MP4.

### Procedural pipeline

1. **Prompt → parameters (our parser)**  
   Keywords and rules map text → palette, motion type, intensity, gradient type, camera motion, shape overlay. No neural network.

2. **Parameters → pixels (our renderer)**  
   For each frame: gradients (vertical/radial/angled/horizontal), noise, motion curves, camera transforms (zoom/pan/rotate), shape overlays — our algorithms and data only.

3. **Frames → video file**  
   imageio + FFmpeg to encode. Content is 100% our code and data.

### Output

Procedural / generative (abstract, geometric, mood-based) — not photorealistic. Within that space we achieve polished, prompt-responsive output.

---

## 3. Extraction, Interpretation, and Creation

### 1. Extraction (base knowledge)

`src/knowledge/` extracts **every aspect** within video files:

- **Metadata:** width, height, fps, duration, num_frames
- **Color:** brightness, contrast, saturation, hue, dominant colors, histograms, color variance, palette match
- **Graphics:** edge density, spatial variance, gradient strength, busyness
- **Motion:** level, std, trend (increasing/decreasing/steady), per-frame motion
- **Composition:** center of mass, luminance balance
- **Consistency:** brightness_std_over_time, color_std_over_time

Output: `BaseKnowledgeExtract` — comprehensive schema consumed by the loop.

### 2. Interpretation (user instructions)

`src/interpretation/` precisely interprets what the user is instructing:

- **Palette, motion, intensity** from keywords (multi-keyword, first match)
- **Duration** from prompt (e.g. "5 seconds", "2 min")
- **Style/tone** hints (cinematic, dreamy, etc.)
- **Negations** ("not calm", "avoid fast") — avoids unwanted parameters

Output: `InterpretedInstruction` — exact representation of user intent.

### 3. Creation (build from extracted knowledge)

`src/creation/` builds output from interpretation + optional knowledge:

- Converts `InterpretedInstruction` → `SceneSpec` for rendering
- Optionally refines palette/motion/intensity from accumulated knowledge (by_keyword, by_palette)
- Procedural renderer produces frames from spec

### Learning (scripts, not models)

1. **Logging:** For each generation, store prompt, spec (palette, motion, intensity), and analysis.
2. **Aggregation:** Summarize by keyword/palette — patterns from past outputs.
3. **Suggestions (optional):** Algorithms that suggest palette or intensity tweaks based on aggregates.
4. **Integration:** After `generate_full_video()` we call `analyze_video(path)` then log the run to the API.

Implementation: `src/analysis/` (analyzer, metrics), `src/learning/` (log, aggregate, suggest).

---

## 4. Roadmap

See [docs/ROADMAP.md](ROADMAP.md) for the 7-phase plan toward industry-level video generation:

- **Phase 1** (Done): Gradient types, camera motion, shape overlays
- **Phase 2**: Cinematography and scene structure
- **Phase 3**: Lighting and color
- **Phase 4**: Text and graphics
- **Phase 5**: Narrative and genre
- **Phase 6**: Sound
- **Phase 7**: Higher realism

---

## 5. Summary

| Goal                        | How we do it                                                       |
|-----------------------------|--------------------------------------------------------------------|
| Base knowledge              | Palettes, motion, resolution, etc. — full vocabulary of video aspects. |
| Extraction                  | Loop analyzes each output; knowledge grows over time.              |
| Video from prompt           | User prompt → parameters from knowledge → one video file.          |
| No external model           | Procedural engine: parser + renderer + FFmpeg only.                |
| Interpret output            | `analyze_video()` → OutputAnalysis (color, motion, consistency).   |
| Visual variety              | Gradient types, camera motion, shape overlays (Phase 1).           |
| Learn from output           | Log runs → aggregate → suggestions → refine base knowledge.        |
