# Architecture: Procedural Engine and Learning

This document describes how Motion implements the [core foundation and loop](INTENDED_LOOP.md): base knowledge of video aspects, continuous extraction via the loop, and video creation from user prompts. We use only our own algorithms and data — no external models.

---

## Mission and goal

**Registry mission:** Exhaustively record **colors**, **sounds**, **semantics (narratives)**, and **interpretations (linguistics)** in the four registries (Pure / Blended / Semantic / Interpretation). Each registry is seeded with **primitives (origins)**; as loops continue, novel combinations are stored under **non-gibberish names** so creation can reuse them.

**Product goal:** A **photoreal engine** that generates any sort of video from arbitrary user instruction, **resorting to the registries** for the values the prompt controls. The current shipped path is **procedural** (parser → renderer → FFmpeg) on that same foundation; photoreal is the destination, not a separate catalog of fixed templates.

See [INTENDED_LOOP.md](INTENDED_LOOP.md) and [WORKFLOWS_AND_REGISTRIES.md](WORKFLOWS_AND_REGISTRIES.md).

---

## Foundation (Summary)

- **Origins** — Primitives of every film/video aspect form base knowledge (`src/knowledge/origins.py`).
- **Interpretation** — Maps any user prompt → parameters (incl. linguistics); ready for arbitrary input.
- **Creation** — Software produces videos using origins + learned registry values the prompt selects.
- **Extraction** — The loop extracts every aspect from output as it runs.
- **Growth** — Novel colors, sounds, narratives, interpretations get sensible names and are added to registries.

See [docs/INTENDED_LOOP.md](INTENDED_LOOP.md) for the full design (foundation + loop).

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

## 4. Project layout (codebase structure)

Clean organization: every file is in its respective directory.

**Repository root**

| Path | Purpose |
|------|--------|
| `config/` | YAML config: `default.yaml`, `workflows.yaml`. |
| `docs/` | All documentation (architecture, registries, deployment, roadmap). |
| `knowledge/` | **Local registry cache/export** (not code): `static/`, `dynamic/`, `narrative/`. **Source of truth = D1.** |
| `output/` | Default video output directory (configurable). |
| `scripts/` | Entrypoints (see below). |
| `cloudflare/` | Worker API (D1, R2, KV), migrations, static app. |
| `video-ai/` | Node FFmpeg recipe render service (`fly.toml`). |
| `docker-compose.local.yml` | Local Docker fleet (webjobs, procedural-render, optional loops). |
| `Dockerfile`, `Procfile`, `fly.loop-*.toml`, `fly.procedural-render.toml` | Deployment (Fly.io Python workers). |

**`scripts/` — entrypoints**

| Script | Purpose |
|--------|--------|
| `worker_start.py` | Fly/Docker dispatcher; `WORKER_START_SCRIPT` selects role. |
| `automate_loop.py` | Learning loop (explorer / exploiter / balanced). |
| `generate_bridge.py` | Pending jobs → generate → upload. |
| `interpret_loop.py` | Interpretation / linguistics worker (no render). |
| `sound_loop.py` | Pure sound discovery worker (no render). |
| `procedural_render_server.py` | HTTP `POST /render` for Video AI `engine=procedural`. |
| `generate.py` | CLI one-shot generate. |
| `automate.py` | Interval-based local automation. |
| `learn_from_api.py`, `learn_report.py` | Learning report / API suggestions. |
| `run_d1_migrations.py` | D1 migrations with 7429 retry. |
| `color_sweep.py`, `registry_*.py`, `seed_*.py`, `backfill_*.py`, … | Registry ops and seeding. |

**`src/` — Python package**

| Path | Purpose |
|------|--------|
| `src/config.py` | Load YAML config; output dir, video params. |
| `src/pipeline.py` | One prompt → one video file; uses concat, prompt, video_generator. |
| `src/concat.py` | Concatenate segment clips into one file (FFmpeg). |
| `src/prompt.py` | Prompt enrichment (optional style/tone suffix). |
| `src/api_client.py` | HTTP client for Cloudflare API (jobs, upload, learning, knowledge). |
| `src/analysis/` | Video analysis: metrics, analyzer (extract_from_video → analysis dict). |
| `src/interpretation/` | Parse user prompt → InterpretedInstruction (parser, schema, linguistics). |
| `src/creation/` | Build SceneSpec from instruction; scene_script, narrative_script. |
| `src/procedural/` | Procedural video engine: generator, motion, parser, renderer; data/keywords, data/palettes. |
| `src/video_generator/` | Base VideoGenerator interface; pipeline uses it. |
| `src/knowledge/` | Origins, static/dynamic/narrative registries, extraction, `grow_all_from_video`, blending, naming, lookup, remote_sync. |
| `src/learning/` | Log runs (JSONL), aggregate, suggest updates (local learning). |
| `src/audio/` | Sound generation (incl. music helpers). |
| `src/automation/` | Prompt generation for loops (prompt_gen). |
| `src/cinematography/` | Shot types, transitions, schema. |
| `src/depth/` | Parallax, layers, assets. |
| `src/graphics/` | Primitives, templates, text. |
| `src/lighting/` | Grading. |
| `src/narrative/` | Genre rules, story (narrative/film logic). |

**`cloudflare/`**

| Path | Purpose |
|------|--------|
| `cloudflare/src/index.ts` | Thin Worker entry: health, auth gate, route dispatch, assets. |
| `cloudflare/src/db.ts` | D1 helpers (incl. `ensureLearnedDynamicMetaTable` runtime DDL). |
| `cloudflare/src/routes/` | Modular API: jobs, loop, knowledge, registries, interpretation. |
| `cloudflare/src/videoAiApi.ts` | Video AI lab: plan/render; `engine=procedural` → `PROCEDURAL_RENDER_URL`. |
| `cloudflare/migrations/` | D1 migrations: jobs, learning_runs, learned_*, static_*, narrative, video_ai_jobs, … |
| `cloudflare/public/` | Static app (HTML/CSS/JS), registries browser, video-ai lab. |
| `cloudflare/wrangler.jsonc` | Wrangler config (D1, R2, KV). |

**Data vs code:** Code = `src/`, `cloudflare/src/`, `scripts/`. **Source of truth for registries = D1** (local `knowledge/` JSON is export/cache only). Config = `config/`. Docs = `docs/`.

**Video AI merge path:** Recipe JSON with `meta.engine`: `recipe` (Node FFmpeg) or `procedural` (Python `generate_full_video` via Fly). See `video-ai/README.md`.

---

## 5. Roadmap

See [docs/ROADMAP.md](ROADMAP.md) for the 7-phase plan toward industry-level (including photoreal) video generation:

- **Phase 1** (Done): Gradient types, camera motion, shape overlays
- **Phase 2**: Cinematography and scene structure
- **Phase 3**: Lighting and color
- **Phase 4**: Text and graphics
- **Phase 5**: Narrative and genre
- **Phase 6**: Sound
- **Phase 7**: Higher realism / photoreal path on the same registries

---

## 6. Summary

| Goal | How we do it |
|------|--------------|
| Exhaustive registries | Colors, sounds, narratives, interpretations — primitives first, then named discoveries. |
| Non-gibberish names | Name-generator + name reserve; backfill replaces numeric/gibberish labels. |
| Prompt-controlled values | Interpretation maps input → registry elements; creation uses those values. |
| Video from prompt | User prompt → instruction → spec from registries → one video file. |
| No external model (today) | Procedural engine: parser + renderer + FFmpeg only. |
| Photoreal (destination) | Same registry-backed instruction path; higher-realism renderer later. |
| Learn from output | Extract → `grow_all_from_video` (+ narrative / interpretation sync) → D1. |
