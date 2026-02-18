# Workflows and registries — full picture

This document covers: (1) **registry taxonomy** and where things live (Part I); (2) **colors and audio** in both STATIC and DYNAMIC; (3) **extraction focus** (frame vs window) and the **details of each workflow** (Part II).

---

# Part I — Registries

## 1. The four registries (Pure, Blended, Semantic, Interpretation)

All registries fit the **overall mission**: record every element of a complete video so the loop can learn and reuse discoveries.

- **Registries** must be **100% accurate** (what we record). They live in JSON/D1; they may reference algorithms but do not contain them.
- **Algorithms and functions** must be **100% precise** (how we compute). They live in **scripts and code**, not in the registries.

**Foundation:** [REGISTRY_FOUNDATION.md](REGISTRY_FOUNDATION.md) defines four registries, depth_breakdown rules, and name-generator (semantic/name-like). **100% precise & accurate.**

**Rule:** Every element fits into one of **four** registries: Pure (Static), Blended (Dynamic/Temporal), Semantic (Narrative), Interpretation (human input resolved). See [REGISTRY_FOUNDATION.md](REGISTRY_FOUNDATION.md) for **categories vs elements** (categories are what elements fit into; elements are the named entries with depth_breakdown).

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

- **Pure sound** = any form of noise within **a single frame** (one instant, not a 1-second window). There are **origin/primitive sound values** (silence, rumble, tone, hiss). The **mesh** is the `static_sound` registry: it holds the primitives plus discovered entries. Primitives and discovered values **blend together** in the mesh (each new discovery is a blend of primitives for one instant frame, with `depth_breakdown` = weights of origin noises). New discoveries are recorded in the registry; the mesh grows each loop run and is used on the next run for creation and further discovery.
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
| **Sound** | noise, strength_pct, amplitude, tone, timbre, depth_breakdown | **Origin/primitive** values = silence, rumble, tone, hiss. The **mesh** (this registry) holds primitives + discovered blends. Each discovery for one instant frame is a **blend of primitives** (depth_breakdown = origin_noises weights); recorded in the registry. low/mid/high are measurements. Kick, snare, melody, etc. → **dynamic** audio_semantic. |

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

# Part II — Workflows

## 8. Colors and audio in both STATIC and DYNAMIC

**Yes — colors and audio exist in both registries and in all workflows.**

| Registry | Color | Audio / sound |
|----------|--------|----------------|
| **STATIC** (pure, per-frame) | **static_colors** — one dominant color (and related metrics) per frame. Grown by `grow_all_from_video()` → per-frame extraction → compare → add novel with name. Synced to D1 `static_colors`. | **static_sound** — **pure sound** = any noise in **one frame (one instant)**; amplitude, tone, timbre measured and recorded per instant. New values are blended into the **mesh** (this registry); the mesh grows each loop and is synced to D1 `static_sound`. |
| **DYNAMIC** (non-pure, multi-frame / whole-video) | **learned_colors** — whole-video dominant color (and aggregates). Grown by `grow_and_sync_to_api()` from analysis → D1 `learned_colors`. Used in creation (palette blending). | **Audio as non-pure** — tempo, mood, presence per run stored as blends (domain `audio`) in `learned_blends`. Shown in registries UI under Dynamic → Sound. Creation uses `learned_audio` from API. |

So every run can add both **static** (per-frame color + sound) and **dynamic** (whole-video color + audio blends, plus motion, lighting, etc.). With **LOOP_EXTRACTION_FOCUS** you can run 2 workers that feed only static (frame) and 1 that feeds only dynamic + narrative (window), or leave it unset to feed both.

---

## 9. Extraction focus: frame vs window (three workflows)

**Yes.** You run **2 workflows** dedicated to **extraction + discovery within an individual frame** (pure/static) and **1 workflow** dedicated to **discovering + extracting blends within windows of frames** (blended/dynamic).

- All run the **same** script: `scripts/automate_loop.py`.
- **LOOP_EXTRACTION_FOCUS** (env) controls what is extracted and grown:
  - **frame** — Per-frame only: extract static (color, sound) per frame, grow only the **static** registry, post only static discoveries. Every new value gets a **newly created (authentic) name**. Use on **2 workers** (e.g. one with explore, one with exploit for prompt choice).
  - **window** — Per-window only: extract dynamic (motion, gradient, camera, lighting, etc.) over windows of frames, grow **dynamic** and **narrative** registries, post dynamic + narrative discoveries and whole-video aggregates (learned_colors, learned_motion, learned_blends). Use on **1 worker**.
  - **Unset** — **all**: current behaviour (both per-frame and per-window growth and sync).

So: **2 workers** with `LOOP_EXTRACTION_FOCUS=frame`, **1 worker** with `LOOP_EXTRACTION_FOCUS=window`. Prompt choice (explorer / exploiter / main) is independent and set via **LOOP_EXPLOIT_RATIO_OVERRIDE** and **LOOP_WORKFLOW_TYPE**.

---

## 10. The workflows — details and entirety

Each workflow is one **continuous loop** that repeats the same steps. Only **prompt selection** differs.

### Single run (same for all three)

1. **Load config** — Loop enabled, delay, duration, exploit ratio (from API or env).
2. **Pick prompt** — Depends on workflow (see below).
3. **Create job** — `POST /api/jobs` with prompt, duration, `workflow_type` (explorer | exploiter | main).
4. **Interpret** — `interpret_user_prompt(prompt)` → instruction (palette, motion, gradient, camera, audio, etc.).
5. **Create spec** — `build_spec_from_instruction(instruction, knowledge)` → SceneSpec (no fixed lists; registry + origins only).
6. **Render** — `generate_full_video(...)` → frames + procedural audio → MP4.
7. **Upload** — `POST /api/jobs/{id}/upload` with the MP4.
8. **Extract** — From video: per-frame static (color, sound), per-window dynamic (motion, lighting, composition, etc.); whole-video analysis for learning.
9. **Grow**  
   - **Static + Dynamic:** `grow_all_from_video()` → static_colors, static_sound (per-frame) and motion, time, gradient, camera, lighting, composition, graphics, temporal, technical, audio_semantic, transition, depth (per-window).  
   - **Narrative:** `grow_narrative_from_spec()` → genre, mood, themes, plots, settings, scene_type.  
   - **Sync:** `post_all_discoveries()` (or `post_static_discoveries()` + `post_dynamic_discoveries()` + `post_narrative_discoveries()`); `grow_and_sync_to_api()` → learned_colors, learned_motion, learned_blends (whole-video aggregates) to D1.
10. **Post discoveries** — Static → `post_static_discoveries()`; dynamic → `post_dynamic_discoveries()`; narrative → `post_narrative_discoveries()`.
11. **Log learning** — `POST /api/learning` with job_id, prompt, spec slice, analysis.
12. **Update state** — If outcome is "good", add prompt to good_prompts; always append to recent_prompts; increment run_count; save state to API (KV).
13. **Wait** — Sleep `delay_seconds`, then go to step 1.

### Explorer (Workflow B — discovery focus)

- **Env:** `LOOP_EXPLOIT_RATIO_OVERRIDE=0`, `LOOP_WORKFLOW_TYPE=explorer`.
- **Prompt selection:** **100% explore.** Never uses good_prompts; always picks a **new** procedural prompt (from `generate_procedural_prompt(avoid=recent, knowledge=knowledge)`). So each run stresses **discovery** — new combos, new colors, new motion, new audio in both static and dynamic registries.
- **Same pipeline as above.** Every run still does static + dynamic + narrative growth. No "dynamic-only" or "static-only" behavior.
- **Goal:** Maximize growth across all three registries by always trying new prompts.

### Exploiter (Workflow A — interpretation focus)

- **Env:** `LOOP_EXPLOIT_RATIO_OVERRIDE=1`, `LOOP_WORKFLOW_TYPE=exploiter`.
- **Prompt selection:** **100% exploit.** Always picks from **good_prompts** (prompts that already produced a "good" outcome). So each run refines interpretation and creation on **known-good** prompts; fewer brand-new combos, more repetition of successful patterns.
- **Same pipeline as above.** Every run still does static + dynamic + narrative growth.
- **Goal:** Keep the system sharp on user-like prompts and reliable outcomes; registries still grow from every run (same extraction and growth code).

### Main / Balanced (adjustable)

- **Env:** No `LOOP_EXPLOIT_RATIO_OVERRIDE` (or `LOOP_WORKFLOW_TYPE=main`). Exploit ratio comes from the **webapp** (e.g. 70% exploit / 30% explore).
- **Prompt selection:** With probability **exploit_ratio** use good_prompts; otherwise pick a new procedural prompt. So you get a **mix** of exploit and explore (e.g. 70/30).
- **Same pipeline as above.** Every run still does static + dynamic + narrative growth.
- **Goal:** Balance discovery (new prompts) and refinement (good prompts) in one worker; you control the mix via the UI.

### Interpretation (Workflow D — no create/render)

- **Script:** `scripts/interpret_loop.py` (fourth Railway service).
- **What it does:** Polls `GET /api/interpret/queue` for pending prompts; runs `interpret_user_prompt(prompt)`; stores the result with `PATCH /api/interpret/:id`. Optionally backfills prompts from the jobs table that don't yet have an interpretation and stores them via `POST /api/interpretations`.
- **Storage:** User prompts and full instruction payloads (palette, motion, gradient, camera, audio, etc.) are stored in **D1** (`interpretations` table). No R2 (no video). KV is used for loop config/state as for other workers.
- **Integration with main pipeline:** `GET /api/knowledge/for-creation` returns `interpretation_prompts` (list of `{ prompt, instruction }`). The main loop's `pick_prompt()` uses `knowledge["interpretation_prompts"]` when exploring: with 35% probability it picks one of these pre-interpreted user prompts so the creation phase has more user-like prompts to work with.

### Sound-only (Workflow E — pure sound discovery, no video)

- **Script:** `scripts/sound_loop.py` (fifth Railway service; optional).
- **Pure sound** = any form of noise within **one frame (one instant)** — not a 1-second window. Each instant is measured (amplitude, tone, timbre) and recorded; new values are **blended into the mesh** (the static_sound registry). The mesh grows each cycle and is used on the next run for creation and further discovery.
- **What it does:** Does **not** create or render video. Each cycle: fetches knowledge (for-creation); picks mood/tempo/presence (from `learned_audio` or keyword origins); generates procedural audio to a WAV; extracts **per-frame (per-instant)** sound with `read_audio_segments_only()`; grows the **mesh** with `grow_static_sound_from_audio_segments()`; POSTs novel discoveries to `/api/knowledge/discoveries`.
- **Goal:** Discovery of new pure (per-instant) sounds on par with the system. Frame workers handle pure colors + pure sounds from video; window worker handles blended + semantic within 1-second windows.
- **Env:** `API_BASE`, `SOUND_LOOP_DELAY_SECONDS` (default 15), `SOUND_LOOP_DURATION_SECONDS` (default 2.5). No job creation; no video upload.

---

## 11. Summary

| Question | Answer |
|----------|--------|
| Colors in both static and dynamic? | Yes. Static = per-frame (static_colors). Dynamic = whole-video/aggregate (learned_colors). |
| Audio in both static and dynamic? | Yes. Static = per-frame sound (static_sound). Dynamic = audio as blends (tempo/mood/presence in learned_blends). |
| A workflow only for dynamic? | Yes. **1 worker** with `LOOP_EXTRACTION_FOCUS=window` grows only dynamic + narrative (blends over 1s windows). |
| A workflow only for static? | Yes. **2 workers** with `LOOP_EXTRACTION_FOCUS=frame` grow only static (per-frame color + sound; authentic names). |
| A workflow only for pure sound? | Yes. **Sound-only** runs `sound_loop.py`; no video; generates audio → extract → grow static_sound → sync. |
| What actually differs? | **Extraction focus**: frame (per-frame only) vs window (per-window only) vs all. **Prompt choice** (explorer/exploiter/main) is independent. **Sound-only** is a separate loop (no video). |
| Fourth workflow (Interpretation)? | Yes. **Interpretation** runs `interpret_loop.py`; no create/render; stores prompt + instruction in D1; main loop uses `interpretation_prompts` from for-creation when picking prompts. |
| Fifth workflow (Sound-only)? | Yes. **Sound-only** runs `sound_loop.py`; no create/render; grows static_sound only; uses knowledge (learned_audio) for next-cycle discovery. |

For config and env details, see `config/workflows.yaml` and [RAILWAY_CONFIG.md](RAILWAY_CONFIG.md).

---

## 12. Audio in the loop — every video has an audio track

Every generated video goes through the same pipeline and **gets procedural audio added** before upload.

| Step | What happens |
|------|----------------|
| **Pipeline** | `generate_full_video()` always calls **`_add_audio(output_path, config, prompt)`** after the visual clip is created (single-clip and multi-segment). |
| **No silent skip** | If pydub or ffmpeg is missing, `_add_audio` **raises**; the job fails. We do not upload a video without an audio track. |
| **Procedural audio** | `mix_audio_to_video()` generates audio from **mood**, **tempo**, **presence** (spec: audio_mood, audio_tempo, audio_presence). Muxed into the MP4 with ffmpeg (`-c:a aac`). |
| **Dependencies** | `requirements.txt`: pydub; **Dockerfile**: `apt-get install ffmpeg`. Railway/Render workers have both; every loop run produces an MP4 with an audio track. |

The **audio icon is enabled** in the browser when the source has a track; the `<video>` element uses `controls` and is not muted by the app (browsers may show muted by default until user interaction).

---

## 13. Static sound extraction (learning from audio) — not yet

We **add** audio to every video. We do **not yet extract** per-frame or per-segment sound from the generated file to fill the **static sound registry**:

- **`extract_static_per_frame()`** returns `"sound": {}` as a placeholder.
- **`extract_dynamic_per_window()`** returns `"audio_semantic": {}` as a placeholder.

Learning from **spec/intended** audio (mood, tempo, presence) is already recorded via remote_sync and narrative; learning from **actual** decoded audio is future work.

---

## 14. Production: audio, visual variety, and API errors

### Audio appears disabled

- **Browser autoplay:** Many browsers show the speaker **muted by default** until the user interacts. **Fix:** Click the speaker icon to unmute. The site includes a hint: "Videos include procedural audio — use the speaker control on the player to unmute if needed."
- **Older videos:** Files generated before audio was mandatory may be video-only. **Check:** `ffprobe -v error -show_streams -select_streams a <file.mp4>` — if you see stream info, the file has an audio track.
- **Speaker greyed out:** If the browser detects **no audio track**, the file was produced without an audio stream. The pipeline now **verifies** after adding audio (`_verify_audio_track`) and raises if the file has no audio stream, so **new** videos always have a track.

### Same pattern (motion + colors) in every video

- **Cause:** High exploit ratio reuses `good_prompts` → same keywords → same palette/motion. Defaults (DEFAULT_PALETTE, DEFAULT_MOTION) and low learned weight also reduce variety.
- **Actions:** (1) Lower **exploit %** in Loop controls (e.g. 30–50%) so the loop picks new prompts more often. (2) Run both **Explorer** (100% explore) and **Exploiter** (100% exploit) workers; both feed the same library. (3) Creation uses registry-first for gradient/motion/camera and increased learned color/motion blend weights — ensure latest `builder.py` is deployed.

### "Unexpected token '<'... is not valid JSON" when saving Exploit/Explore ratio

- The loop config API returned **HTML** instead of JSON (e.g. static host serving `index.html` for all paths, or Worker throw returning an HTML error page).
- **Fixes:** Worker GET/POST `/api/loop/config` and GET `/api/loop/status` return **JSON** `{ error, details }` on failure (no HTML). Frontend checks `text.trimStart().startsWith('<')` and shows a friendly message. Ensure **Worker** is bound to your domain so `/api/*` is handled by the Worker, not a static SPA fallback.

---

## 15. Workflow comparison: Interpret worker and intended vs actual

### Interpret worker vs the 3 video workers

| Worker | Script | Creates/renders video? | Writes to interpretation table? | Writes to static/dynamic/narrative? |
|--------|--------|------------------------|----------------------------------|-------------------------------------|
| **Explorer** | `automate_loop.py` | Yes | Yes (source `loop`) | Static only (frame focus) |
| **Exploiter** | `automate_loop.py` | Yes | Yes (source `loop`) | Static only (frame focus) |
| **Balanced** | `automate_loop.py` | Yes | Yes (source `loop`) | Dynamic + narrative (window focus) |
| **Interpret** | `interpret_loop.py` | **No** | Yes (queue + backfill + generate) | No |

Interpret is a separate 4th worker: it processes the interpret queue, backfills prompts from jobs, and generates slot-based prompts and interprets them. The interpretation registry is filled by the Interpret worker and by each of the 3 video workers (every run POSTs with `source: "loop"`). So the interpretation table still grows even if the Interpret worker is not running.

### Why prompts look generic

Exploiter always picks from good_prompts → same motion/sound/color. Balanced with high exploit ratio does the same. Explorer picks new prompts but slot pools come from keywords + learned registries; if the API returns few or repetitive learned names, variety is limited. interpretation_prompts are used when exploring; if that table is stale, prompts are similar. **To get more variety:** lower exploit on Balanced, ensure Explorer has diverse knowledge, and let interpretation_prompts diversify as the loop runs.

### Intended vs actual workflow

- **Per-video:** One prompt → one spec per video (one palette, one motion, one gradient, one camera, one audio for the whole video). Variety across videos comes from different prompts, not from randomizing the spec every frame.
- **Per-frame / per-pixel (pure):** In **pure_per_frame** mode we place different pure colors at different pixels (hash of x, y, t), but the **set** of colors and the **motion** are fixed for the video. So there is per-pixel variation within a single spec.
- **Blends:** New blends are **extracted** from the rendered video (dominant color per frame, aggregates per window) and recorded. They are not computed as "particles combining" during render. **Strict (→ new pure):** per-frame dominant color/sound and per-window temporal blend (mean RGB over 1s) → static. **Lenient (→ dynamic + semantic):** motion, lighting, gradient, camera, etc. over window → dynamic and narrative.

---

## See also

- **[REGISTRY_FOUNDATION.md](REGISTRY_FOUNDATION.md)** — Authoritative foundation: four registries, depth_breakdown, name-generator (semantic/name-like), 100% precise & accurate.
- **[LOOP_STANDARDS.md](LOOP_STANDARDS.md)** — Set algorithms and functions for interpretation loop (language standard) and video loop (MP4 aspects); both grow from origin/primitive + extracted values.
- [NAME_GENERATOR.md](NAME_GENERATOR.md) — Algorithm for sensible, semantic or name-like short names.
- [MP4_ASPECTS.md](MP4_ASPECTS.md) — Every aspect of a complete MP4; frame/window model.
- [RAILWAY_CONFIG.md](RAILWAY_CONFIG.md) — Service config, env vars, deploy steps for Explorer, Exploiter, Balanced, Interpretation, Sound.
- [ALGORITHMS_AND_FUNCTIONS_AUDIT.md](ALGORITHMS_AND_FUNCTIONS_AUDIT.md) — Audit of extraction, growth, and registry functions.
