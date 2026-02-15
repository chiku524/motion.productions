# Workflows and registries — full picture

This doc clarifies: (1) **colors and audio in both STATIC and DYNAMIC**; (2) that **no workflow is “static-only” or “dynamic-only”** — all workflows run the same pipeline and grow all three registries; (3) the **details and entirety** of each of the three workflows.

---

## 1. Colors and audio in both STATIC and DYNAMIC

**Yes — colors and audio exist in both registries and in all workflows.**

| Registry | Color | Audio / sound |
|----------|--------|----------------|
| **STATIC** (pure, per-frame) | **static_colors** — one dominant color (and related metrics) per frame. Grown by `grow_all_from_video()` → per-frame extraction → compare → add novel with name. Synced to D1 `static_colors`. | **static_sound** — per-frame or per-sample sound (amplitude, tone, timbre). Grown by `grow_all_from_video()`; when per-frame audio extraction is not yet available, spec-derived static sound (audio_tempo, audio_mood, audio_presence) is still recorded. Synced to D1 `static_sound`. |
| **DYNAMIC** (non-pure, multi-frame / whole-video) | **learned_colors** — whole-video dominant color (and aggregates). Grown by `grow_and_sync_to_api()` from analysis → D1 `learned_colors`. Used in creation (palette blending). | **Audio as non-pure** — tempo, mood, presence per run stored as blends (domain `audio`) in `learned_blends`. Shown in registries UI under Dynamic → Sound. Creation uses `learned_audio` from API. |

So every run can add both **static** (per-frame color + sound) and **dynamic** (whole-video color + audio blends, plus motion, lighting, etc.). There is no workflow that only feeds static or only dynamic; all three workflows use the same growth path and thus feed both.

---

## 2. Is there a workflow solely for static or solely for dynamic?

**No.** There is no workflow dedicated only to static values and none only to dynamic values.

- All three workers (Explorer, Exploiter, Main) run the **same** script: `scripts/automate_loop.py`.
- Every run does the **same** pipeline: pick prompt → interpret → create → render → extract → **grow (static + dynamic + narrative)** → sync.
- So every run grows **all three registries** (static, dynamic, narrative). The only thing that changes between the three is **how the next prompt is chosen** (exploit vs explore), not which registries are updated.

Static vs dynamic is a **registry classification** (pure per-frame vs non-pure multi-frame), not a workflow type.

---

## 3. The three workflows — details and entirety

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
12. **Update state** — If outcome is “good”, add prompt to good_prompts; always append to recent_prompts; increment run_count; save state to API (KV).
13. **Wait** — Sleep `delay_seconds`, then go to step 1.

### Explorer (Workflow B — discovery focus)

- **Env:** `LOOP_EXPLOIT_RATIO_OVERRIDE=0`, `LOOP_WORKFLOW_TYPE=explorer`.
- **Prompt selection:** **100% explore.** Never uses good_prompts; always picks a **new** procedural prompt (from `generate_procedural_prompt(avoid=recent, knowledge=knowledge)`). So each run stresses **discovery** — new combos, new colors, new motion, new audio in both static and dynamic registries.
- **Same pipeline as above.** Every run still does static + dynamic + narrative growth. No “dynamic-only” or “static-only” behavior.
- **Goal:** Maximize growth across all three registries by always trying new prompts.

### Exploiter (Workflow A — interpretation focus)

- **Env:** `LOOP_EXPLOIT_RATIO_OVERRIDE=1`, `LOOP_WORKFLOW_TYPE=exploiter`.
- **Prompt selection:** **100% exploit.** Always picks from **good_prompts** (prompts that already produced a “good” outcome). So each run refines interpretation and creation on **known-good** prompts; fewer brand-new combos, more repetition of successful patterns.
- **Same pipeline as above.** Every run still does static + dynamic + narrative growth.
- **Goal:** Keep the system sharp on user-like prompts and reliable outcomes; registries still grow from every run (same extraction and growth code).

### Main / Balanced (adjustable)

- **Env:** No `LOOP_EXPLOIT_RATIO_OVERRIDE` (or `LOOP_WORKFLOW_TYPE=main`). Exploit ratio comes from the **webapp** (e.g. 70% exploit / 30% explore).
- **Prompt selection:** With probability **exploit_ratio** use good_prompts; otherwise pick a new procedural prompt. So you get a **mix** of exploit and explore (e.g. 70/30).
- **Same pipeline as above.** Every run still does static + dynamic + narrative growth.
- **Goal:** Balance discovery (new prompts) and refinement (good prompts) in one worker; you control the mix via the UI.

### Interpretation (Workflow D — no create/render)

- **Script:** `scripts/interpret_loop.py` (fourth Railway service).
- **What it does:** Polls `GET /api/interpret/queue` for pending prompts; runs `interpret_user_prompt(prompt)`; stores the result with `PATCH /api/interpret/:id`. Optionally backfills prompts from the jobs table that don’t yet have an interpretation and stores them via `POST /api/interpretations`.
- **Storage:** User prompts and full instruction payloads (palette, motion, gradient, camera, audio, etc.) are stored in **D1** (`interpretations` table). No R2 (no video). KV is used for loop config/state as for other workers.
- **Integration with main pipeline:** `GET /api/knowledge/for-creation` returns `interpretation_prompts` (list of `{ prompt, instruction }`). The main loop’s `pick_prompt()` uses `knowledge["interpretation_prompts"]` when exploring: with 35% probability it picks one of these pre-interpreted user prompts so the creation phase has more user-like prompts to work with.

---

## 4. Summary

| Question | Answer |
|----------|--------|
| Colors in both static and dynamic? | Yes. Static = per-frame (static_colors). Dynamic = whole-video/aggregate (learned_colors). |
| Audio in both static and dynamic? | Yes. Static = per-frame sound (static_sound). Dynamic = audio as blends (tempo/mood/presence in learned_blends). |
| A workflow only for dynamic? | No. All three workflows run the same pipeline and grow static + dynamic + narrative. |
| A workflow only for static? | No. Same as above. |
| What actually differs between the three? | Only **prompt choice**: Explorer = 100% new prompts; Exploiter = 100% good prompts; Main = adjustable % (e.g. 70% good / 30% new). |
| Fourth workflow (Interpretation)? | Yes. **Interpretation** runs `interpret_loop.py`; no create/render; stores prompt + instruction in D1; main loop uses `interpretation_prompts` from for-creation when picking prompts. |

For config and env details, see `config/workflows.yaml` and [RAILWAY_CONFIG.md](RAILWAY_CONFIG.md).

---

## 5. Audio in the loop — every video has an audio track

Every generated video goes through the same pipeline and **gets procedural audio added** before upload.

| Step | What happens |
|------|----------------|
| **Pipeline** | `generate_full_video()` always calls **`_add_audio(output_path, config, prompt)`** after the visual clip is created (single-clip and multi-segment). |
| **No silent skip** | If pydub or ffmpeg is missing, `_add_audio` **raises**; the job fails. We do not upload a video without an audio track. |
| **Procedural audio** | `mix_audio_to_video()` generates audio from **mood**, **tempo**, **presence** (spec: audio_mood, audio_tempo, audio_presence). Muxed into the MP4 with ffmpeg (`-c:a aac`). |
| **Dependencies** | `requirements.txt`: pydub; **Dockerfile**: `apt-get install ffmpeg`. Railway/Render workers have both; every loop run produces an MP4 with an audio track. |

The **audio icon is enabled** in the browser when the source has a track; the `<video>` element uses `controls` and is not muted by the app (browsers may show muted by default until user interaction).

---

## 6. Static sound extraction (learning from audio) — not yet

We **add** audio to every video. We do **not yet extract** per-frame or per-segment sound from the generated file to fill the **static sound registry**:

- **`extract_static_per_frame()`** returns `"sound": {}` as a placeholder.
- **`extract_dynamic_per_window()`** returns `"audio_semantic": {}` as a placeholder.

Learning from **spec/intended** audio (mood, tempo, presence) is already recorded via remote_sync and narrative; learning from **actual** decoded audio is future work.

---

## 7. Production: audio, visual variety, and API errors

### Audio appears disabled

- **Browser autoplay:** Many browsers show the speaker **muted by default** until the user interacts. **Fix:** Click the speaker icon to unmute. The site includes a hint: “Videos include procedural audio — use the speaker control on the player to unmute if needed.”
- **Older videos:** Files generated before audio was mandatory may be video-only. **Check:** `ffprobe -v error -show_streams -select_streams a <file.mp4>` — if you see stream info, the file has an audio track.
- **Speaker greyed out:** If the browser detects **no audio track**, the file was produced without an audio stream. The pipeline now **verifies** after adding audio (`_verify_audio_track`) and raises if the file has no audio stream, so **new** videos always have a track.

### Same pattern (motion + colors) in every video

- **Cause:** High exploit ratio reuses `good_prompts` → same keywords → same palette/motion. Defaults (DEFAULT_PALETTE, DEFAULT_MOTION) and low learned weight also reduce variety.
- **Actions:** (1) Lower **exploit %** in Loop controls (e.g. 30–50%) so the loop picks new prompts more often. (2) Run both **Explorer** (100% explore) and **Exploiter** (100% exploit) workers; both feed the same library. (3) Creation uses registry-first for gradient/motion/camera and increased learned color/motion blend weights — ensure latest `builder.py` is deployed.

### "Unexpected token '<'... is not valid JSON" when saving Exploit/Explore ratio

- The loop config API returned **HTML** instead of JSON (e.g. static host serving `index.html` for all paths, or Worker throw returning an HTML error page).
- **Fixes:** Worker GET/POST `/api/loop/config` and GET `/api/loop/status` return **JSON** `{ error, details }` on failure (no HTML). Frontend checks `text.trimStart().startsWith('<')` and shows a friendly message. Ensure **Worker** is bound to your domain so `/api/*` is handled by the Worker, not a static SPA fallback.
