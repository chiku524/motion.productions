# Audio in the loop & workflow verification

This doc confirms how **sound/audio** is incorporated in the loop and how to keep **all workflows** (Railway: explorer, main, exploiter) running smoothly for efficient, precise learning.

---

## 1. Audio is in the loop — every video has an audio track

**Yes.** Every generated video goes through the same pipeline and **gets procedural audio added** before upload or use.

| Step | What happens |
|------|----------------|
| **Pipeline** | `generate_full_video()` (used by generate_bridge, automate_loop, generate.py) always calls **`_add_audio(output_path, config, prompt)`** after the visual clip is created — for both single-clip and multi-segment (long) videos. |
| **No silent skip** | If pydub or ffmpeg is missing, `_add_audio` **raises**; the job fails. We do not upload a video without an audio track. |
| **Procedural audio** | `mix_audio_to_video()` generates audio from **mood**, **tempo**, **presence** (from prompt/spec: audio_mood, audio_tempo, audio_presence). The result is muxed into the MP4 with ffmpeg (`-c:a aac`). |
| **Dependencies** | `requirements.txt`: **pydub>=0.25.0**. **Dockerfile**: `apt-get install ffmpeg` + `pip install -r requirements.txt`. So Railway/Render workers have both; every loop run produces an MP4 with an audio track. |

So: **videos generated in the loop have audio**, and the **audio icon is enabled** in the browser because the `<video>` element uses `controls` and has no `muted` attribute — the browser shows volume/audio when the source has a track.

---

## 2. Static sound *extraction* (learning from audio) — not yet

We **add** audio to every video. We do **not yet extract** per-frame or per-segment sound from the generated file to fill the **static sound registry**:

- **`extract_static_per_frame()`** returns `"sound": {}` as a placeholder.
- **`extract_dynamic_per_window()`** returns `"audio_semantic": {}` as a placeholder.

So the **static registry** (color + sound) and **dynamic registry** (e.g. audio_semantic) are set up, but **sound/audio extraction** from the video file is future work. Learning from **spec/intended** audio (mood, tempo, presence) is already recorded via remote_sync and narrative; learning from **actual** decoded audio is not yet implemented.

---

## 3. Railway workflows (explorer, main, exploiter) — all use the same pipeline

All three workers use the **same code path**:

- **Same Dockerfile** → same image (Python 3.11, ffmpeg, pydub, requirements).
- **Same start command** → `python scripts/automate_loop.py`.
- **Same pipeline** → fetch job → `generate_full_video()` → `_add_audio()` → upload.

So **all three** (explorer, main, exploiter) produce **videos with audio** and the same learning flow (per-frame static color, per-window dynamic, narrative, whole-video discoveries). Different only by **exploit ratio** (env override):

| Worker | `LOOP_EXPLOIT_RATIO_OVERRIDE` | Role |
|--------|-------------------------------|------|
| Explorer | `0` | 100% explore — broad discovery |
| Main (balanced) | (none) | Uses webapp config (e.g. 70% exploit / 30% explore) |
| Exploiter | `1` | 100% exploit — refine known-good prompts |

---

## 4. Checklist for smooth, precise learning

- **Audio:** Confirmed — every video has an audio track; pipeline fails if audio cannot be added. No change needed for “audio in the loop.”
- **Duration:** Loop default is 1s (config + API); UI can set “Video duration per run.” All workers read from API loop config.
- **Registries:** Static (color; sound placeholder), dynamic (motion, time, etc.), narrative (themes, settings) — all written and synced to D1 when `api_base` is set.
- **Railway:** Ensure all three services have **API_BASE** and, for explorer/exploiter, **LOOP_EXPLOIT_RATIO_OVERRIDE**. Same repo, same Dockerfile, same CMD.
- **Verify:** After deploy, run a job from the webapp; open the result — video should play with **volume/audio control** visible and audible procedural audio.

---

## Summary

- **Sound is incorporated:** Every video gets **procedural audio** (mood, tempo, presence); the **audio icon is enabled** in the player because the MP4 has an audio track and the element is not muted.
- **Learning from decoded audio** (per-frame sound for the static registry, semantic audio for the dynamic registry) is **not yet** implemented; that is future work.
- **All workflows** (explorer, main, exploiter) use the same pipeline and dependencies, so learning runs with the same precision and efficiency across workers; use the checklist above to keep them aligned.
