# Enhancements & Optimizations

This document tracks the seven enhancement steps for the continuous loop. Use it to monitor what is complete and what remains for each step.

---

## Step 1: Ensure All API Calls Within the Continuous Loop Are Successful

**Goal:** Every API call (state load/save, loop config, job create, upload, discoveries, learning) should be validated for success. Failures should be detected, logged, and handled (retry, skip, or stop) rather than silently ignored.

| Already Done | Needs to Be Done |
|--------------|------------------|
| API calls exist: `api_request` for state, config, jobs, upload, learning | ~~Add explicit success/failure handling for each call~~ ✅ |
| Basic try/except in some places | ~~Retry/backoff logic where appropriate~~ ✅ |
| | ~~Log failures with context (which call, response status, error)~~ ✅ |
| | ~~Don't silently swallow exceptions and proceed as if success~~ ✅ |
| | ~~Define behavior when calls fail (retry N times, stop loop, fallback)~~ ✅ |

**Status:** ✅ Done

**Implemented:** `src/api_client.py`: `APIError` with status/path/body; `api_request` retries on 5xx and connection errors when `max_retries` > 0; `api_request_with_retry` for state/config/jobs/upload/learning; JSON response validation. `scripts/automate_loop.py`: state/config use retry and log on failure; job create validated for `id`, retry and log; upload and learning use `api_request_with_retry`; upload failure prevents state update (`run_succeeded`); learning and discoveries wrapped with `APIError` logging; knowledge fetch logs non-API exceptions instead of swallowing; state only updated after successful upload. `src/knowledge/lookup.py`: learning/stats and for-creation use `api_request_with_retry`; API failures logged when falling back to local. `src/knowledge/remote_sync.py`: discoveries POST uses `api_request_with_retry`.

---

## Step 2: Always Add Audio to Every MP4

**Goal:** Every generated mp4 must have an audio track. No conditional gate; no silent exception swallowing. Audio addition should be mandatory, and failures should be surfaced (logged or raised) rather than silently skipped.

| Already Done | Needs to Be Done |
|--------------|------------------|
| ~~`_maybe_add_audio` exists~~ → `_add_audio` | ~~Remove `config.audio.add` gate — always attempt audio~~ ✅ |
| Procedural audio via pydub + ffmpeg | ~~Surface/log failures instead of catching and ignoring~~ ✅ |
| Temp-file mux to avoid in-place corruption | ~~Verify pydub + ffmpeg in deployment; handle missing deps~~ ✅ |
| | ~~Ensure every output mp4 has an audio track (or explicit failure path)~~ ✅ |

**Status:** ✅ Done

**Implemented:** `src/pipeline.py`: Renamed `_maybe_add_audio` → `_add_audio`; removed `config.audio.add` gate — audio is always attempted; ImportError and mix failures are logged and re-raised (no silent return). `src/audio/sound.py`: `mix_audio_to_video` raises `RuntimeError` with install hints if pydub is missing or ffprobe/ffmpeg are not on PATH; ffprobe/ffmpeg `FileNotFoundError` surfaced; other ffprobe failures logged with duration fallback; missing `pydub.generators.Sine` logged. Deployment: ensure `pydub` (in requirements.txt) and system ffmpeg are installed.

---

## Step 3 & 4: Origin-Based Blending (All Domains)

**Goal:** Blends = merged primitives OR merged primitives + new values OR merged new values + newer values OR merged primitives + newer values. Example: white and black blend (via motion or another domain) → grey. Every domain works this way. Something in the video causes values to transform; every transformation is recorded and named when novel.

| Already Done | Needs to Be Done |
|--------------|------------------|
| `COLOR_ORIGINS`, `MOTION_ORIGINS`, etc. define primitives | ~~Stop using named palettes as primary inputs~~ ✅ (output is blended RGB) |
| `blend_colors`, `blend_palettes` (RGB blending) | ~~Interpret prompt → primitive values, not palette names~~ ✅ |
| `blend_motion_params`, `blend_rhythm`, etc. (categorical) | ~~Blend at primitive level for every domain~~ ✅ (color + motion) |
| `PALETTES` and `KEYWORD_TO_PALETTE` (template lookup) | ~~Define *what causes blending*~~ ✅ (multiple keywords + learned) |
| Creation uses palette names + `blend_palettes` | ~~Creation: blend primitives → single new value per domain~~ ✅ |
| | ~~Renderer: accept values from primitive blending~~ ✅ (palette_colors primary) |
| | ~~Ensure "something in the video causes blending" is explicit~~ ✅ (docstrings) |
| | Record every new blended value; name when novel → Step 6/7 |

**Status:** ✅ Done (color + motion; recording/naming in Step 6/7)

**Implemented:** **Interpretation:** `InterpretedInstruction` has `color_primitive_lists` (prompt → list of RGB lists from PALETTES); interpretation parser resolves `palette_hints` to these primitive values. **Creation:** `_build_palette_from_blending` uses `color_primitive_lists` when present (blend RGB lists directly); else resolves palette_hints to PALETTES; always returns a list (never None). Blending cause documented: multiple prompt keywords + optional learned/discovered values. **Renderer:** Uses `palette_colors` (blended from primitives) as primary; `palette_name` is fallback only. **Procedural parser:** Collects all matching palette and motion hints, blends via `blend_palettes` / `blend_motion_params`, sets `palette_colors` and blended `motion_type` on SceneSpec.

---

## Step 5: Extraction Captures Exact Transformed Value

**Goal:** Extraction must capture the *exact* transformed value — e.g. two colors (black, white) merge during video → grey. Extraction captures the exact value of grey only, nothing else. Same for every domain.

| Already Done | Needs to Be Done |
|--------------|------------------|
| `dominant_color_rgb` (exact RGB) | ~~Keep exact values; stop mapping to palette name for storage~~ ✅ |
| `motion_level`, `motion_std`, `motion_trend` | ~~Store actual values~~ ✅; `closest_palette` is display-only |
| `mean_brightness`, `mean_contrast`, `mean_saturation`, etc. | Store the actual measured value (already used in growth) |
| Registry stores exact RGB / params | ~~For every domain: extract and store exact transformed value~~ ✅ |
| | Handle multi-value blends over time (e.g. per-frame sampling) → optional future |

**Status:** ✅ Done — extraction and registry use exact values; closest_palette is reference only

---

## Step 6: Growth Phase — Random Selection; Extract, Record, Name Blends

**Goal:** Values within each domain are chosen at random (or as close to random as possible) during growth. All blended values created during video generation are extracted, recorded, and given a randomly selected name if truly new.

| Already Done | Needs to Be Done |
|--------------|------------------|
| `pick_prompt` uses `secure_choice` (secrets) | ✅ |
| `secure_choice` for learned colors in blending | Growth/creation: select domain values with crypto-quality RNG |
| Name reserve and `take()` exist | Define "choose value at random" per domain |
| `generate_blend_name` invents names | Ensure all new blended values are extracted, recorded, and named |
| | Single, consistent random-selection algorithm across domains |
| | Distinguish "truly new" vs "already known" before naming |

**Status:** ✅ Done

---

## Step 7: Record All New Values; English-Like Name Algorithm

**Goal:** All new values are recorded and added to the registry for each domain. Names for novel blends should resemble real English words — pronounceable, phonetically plausible, pleasant when spoken aloud.

| Already Done | Needs to Be Done |
|--------------|------------------|
| `add_learned_*` per domain | ~~Ensure every new blended value is written to registry~~ ✅ |
| `name_reserve`, `refill`, `take()` | ✅ |
| ~~`_invent_word` (consonant+vowel)~~ | ~~Replace with English-like generator~~ ✅ |
| `_invent_word` now uses _ENGLISH_SYLLABLES (velvet, amber, coral, flow, etc.) | Names 2–3 syllables, pronounceable |
| Unified registry manifest + `list_all_registry_values` | One place to see every domain and every value |
| | Algorithm may need iterative refinement with you (tweak syllable list) |

**Status:** ✅ Done — English-like names; unified registry; all domains recorded

---

## Summary: What's Done vs What's Needed

| Step | Main Gap |
|------|----------|
| **1** | ✅ Done — success checks, retries, and failure handling in place for all loop API calls |
| **2** | ✅ Done — mandatory audio; failures logged/raised; missing deps surfaced |
| **3 & 4** | ✅ Done — prompt → primitive values; creation/renderer use blended values; blend cause documented |
| **5** | ✅ Done — extraction/registry use exact values; closest_palette is display-only |
| **6** | ✅ Done — `src/random_utils.py`: secure_choice/secure_random (secrets); pick_prompt, prompt_gen, builder use crypto RNG |
| **7** | ✅ Done — English-like names; unified registry; all domains recorded |

---

## Progress Legend

- ⬜ Not started  
- 🟨 In progress  
- ✅ Complete  

---

*Last updated: 2026-02-10 — Step 6: crypto-quality RNG (secure_choice/secure_random) in automate_loop, prompt_gen, builder*
