# Production: video audio and visual variety

This doc explains why videos on motion.productions might appear to have **audio disabled**, why the **Exploit/Explore ratio save** can show "Unexpected token '<'... is not valid JSON", and how to fix or improve these and **visual variety**.

---

## 1. Audio appears disabled

### What the pipeline does

- Every generated video goes through **`_add_audio()`** in `src/pipeline.py`: procedural audio (mood, tempo, presence) is mixed into the MP4 with ffmpeg. There is no code path that uploads a video without calling `_add_audio`; if audio fails, the run fails and the job is not marked completed.
- **Railway workers** use the same pipeline (`generate_full_video` → `_add_audio` → upload). The Dockerfile installs **ffmpeg** and **pydub**; without them, generation would error.

### Why it might look “disabled” in the browser

1. **Browser autoplay policy**  
   Many browsers show the video control bar with the **speaker muted by default** until the user interacts with the page. That can look like “audio is disabled” even when the file has an audio track.
   - **Fix:** Click the speaker icon on the video player to unmute. The site now includes a short hint: “Videos include procedural audio — use the speaker control on the player to unmute if needed.”
   - The frontend does **not** set `muted` on the `<video>` element and explicitly sets `videoPlayer.muted = false` when showing a result.

2. **Older videos in the library**  
   If some videos were generated and uploaded **before** audio was mandatory (or before a deploy that fixed it), those files might be video-only. New runs should all have audio.
   - **Check:** Download a **recent** video from the library, then run:  
     `ffprobe -v error -show_streams -select_streams a <file.mp4>`  
     If you see stream info, the file has an audio track.

3. **Deploy / environment**  
   If the Railway (or other) worker is not built from the current repo, it might be missing ffmpeg or the latest pipeline. Ensure:
   - Dockerfile includes: `RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg`
   - Start command is `python scripts/automate_loop.py` (or the same pipeline that calls `generate_full_video`).

### Procedural audio level

- Procedural audio levels have been increased (e.g. neutral from -32 dB to -22 dB) so that when unmuted, the track is clearly audible. See `src/audio/sound.py` → `_generate_procedural_audio`.

### Audio icon disabled (un-toggable)

- If the **speaker control is greyed out or unclickable**, the browser has detected **no audio track** in the MP4. That means the file was produced without an audio stream (e.g. by an older pipeline or a path that skipped `_add_audio`).
- **Fix:** The pipeline now **verifies** after adding audio (`_verify_audio_track` in `src/pipeline.py`): it runs `ffprobe` and **raises** if the file has no audio stream, so we never upload a video-only file. After deploying this change, **new** videos will have an audio track; the speaker will be toggable and unmuting will play sound.
- **Existing** library videos that were generated before this fix may still be video-only; only new runs are guaranteed to have audio.

---

## 2. Same pattern (motion + colors) in every video

### Why this happens

1. **Exploit ratio and good_prompts**  
   The loop uses **exploit_ratio** (e.g. 70% default): that fraction of the time it **reuses a prompt from `good_prompts`** (prompts that already produced a “good” outcome). So many runs use the **same or very similar prompts** → same keywords → same palette/motion resolution → similar look.

2. **Keyword → single palette/motion**  
   Interpretation maps prompt words to **one** palette name and **one** motion type (plus hints for blending). If prompts share the same keywords, you get the same resolved palette and motion.

3. **Defaults**  
   When the prompt does not match many keywords, interpretation falls back to **DEFAULT_PALETTE** and **DEFAULT_MOTION**. So generic or exploratory prompts can still converge to the same default look.

4. **Learned values used lightly**  
   Creation blends in **learned_colors** and **learned_motion** from the API, but with a small weight. So new names in the registries (from growth) only slightly change the output until the weights were increased (see below).

### What was changed to improve variety

- **Registry-driven + truly random when interpretation uses defaults**  
  We do **not** use seed-based variety. When the prompt doesn’t match gradient/motion/camera keywords, interpretation falls back to defaults. **Creation** then uses: (1) **registry** when available (e.g. a random entry from `learned_motion` for motion type); (2) **truly random** choice from primitive options (gradient, motion, camera) otherwise. So each run gets real variety from the three registries (static/dynamic) and from `random.choice`, not from a deterministic seed. The main workflow uses **strictly pure elements/blends [STATIC]** — no template-based creation.

- **Stronger use of learned color and motion in creation**  
  In `src/creation/builder.py`, when knowledge is present:
  - Learned color blend weight increased (e.g. center 0.15 → 0.28, edges 0.08 → 0.15) and more learned entries considered (5 → 8).
  - Learned motion blend weight increased (0.2 → 0.35) and more entries considered (10 → 15).
  So as the static and dynamic registries grow, new colors and motion styles should be more visible in the next generations.

- **Lower exploit ratio for more exploration**  
  In the **Loop controls** on the site (or via API `POST /api/loop/config`), set **exploit** to a lower value (e.g. **30–50%**). That makes the loop pick **new** procedural prompts more often, so you get more palette/motion combinations and less repetition of the same “good” prompts.

- **Run both Explorer and Exploiter workers**  
  The **Explorer** worker uses `LOOP_EXPLOIT_RATIO_OVERRIDE=0` (100% explore); the **Exploiter** uses `=1` (100% exploit). Both upload to the same API; **both workflow outputs appear in the same library** on motion.productions. Each job stores a **workflow_type** (`explorer` | `exploiter` | `main` | `web`). The site shows an **Explore** / **Exploit** (or **Web**) badge per video and in “Recent activity” so you can see progress from both workflows. See `config/workflows.yaml` and `docs/INTENDED_LOOP.md`. Run the DB migration `0009_workflow_type.sql` so new jobs can store `workflow_type`.

### Summary

| Issue | Cause | Action |
|-------|--------|--------|
| Audio “disabled” | Browser shows muted by default; or old file has no track | Unmute in player; verify recent file with ffprobe; ensure deploy has ffmpeg + latest code |
| Same pattern | High exploit ratio, same good_prompts, defaults, low learned weight | Lower exploit % in loop config; run Explorer; use latest builder (higher learned weight) |

After deploying the latest code and optionally lowering exploit or adding an Explorer worker, new videos should show more variety and audio should be clearly audible when unmuted.

---

## 3. "Unexpected token '<', \"<!DOCTYPE \"... is not valid JSON\" when saving Exploit/Explore ratio

- This happens when the **loop config API** returns **HTML** (e.g. a fallback page) instead of JSON. Common causes: (1) the request hits a static host (e.g. Cloudflare Pages) that serves `index.html` for all paths, so `/api/loop/config` never reaches the Worker; (2) the Worker throws (e.g. KV unavailable) and the runtime returns an HTML error page.
- **Fixes applied:**
  - **Worker:** GET and POST `/api/loop/config` and GET `/api/loop/status` are wrapped in try/catch; on failure they return **JSON** `{ error: "...", details: "..." }` with status 500, so the API never returns HTML.
  - **Frontend:** Before parsing the response as JSON, we check `text.trimStart().startsWith('<')`; if true, we show a friendly message: *"Server returned a page instead of data. The API may be misconfigured or the loop config endpoint is not available."* so you no longer see the raw parse error.
- **Deployment:** Ensure the **Worker** is bound to your domain (e.g. `motion.productions/*`) so that `/api/*` requests are handled by the Worker, not by a static SPA fallback. In Cloudflare, use Workers Routes so that requests to `motion.productions/api/...` go to the motion-productions Worker.
