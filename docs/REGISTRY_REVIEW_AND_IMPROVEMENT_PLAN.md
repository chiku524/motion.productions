# Registry review and improvement plan

**Based on:** `json registry exports/motion-registries-2026-02-15.json` and full codebase review.

**Mission:** Acquire all possible data from MP4 (video) files and from user prompts; interpret prompts in a standard of English (including dialects/slang); achieve 100% precision in algorithms/functions and 100% accuracy in what we record.

---

## 1. Review of the export: what has little-to-no data

### 1.1 Pure (Static)

| Category | Current state | Root cause |
|----------|---------------|------------|
| **Pure — Sound primitives (origin noises)** | Only 4: silence, rumble, tone, hiss. | Defined in `static_registry.py` / Worker `staticPrimitives.sound_primaries`. No expansion until we add more origin noise types. |
| **Pure — Sound (per-frame discoveries)** | ~10 entries; almost all map to **rumble** or **silence** in `origin_noises`. No **tone** or **hiss** discoveries. | (1) Per-frame audio extraction is a **placeholder**: `extract_static_per_frame()` returns `"sound": {}`; when spec-derived fallback is used we get mood/tempo/presence, which map to one band. (2) DOCS: *"We do not yet extract per-frame or per-segment sound from the generated file"* (WORKFLOWS_AND_REGISTRIES.md). So static sound is mostly **spec-derived** (derive_static_sound_from_spec), not decoded from the MP4. |

**Conclusion:** Pure static sound will stay sparse until we implement **actual per-frame/per-segment audio decoding** and map amplitude/frequency to primitives (silence, rumble, tone, hiss). Until then, only spec-derived combos are recorded.

### 1.2 Blended (Dynamic)

| Category | Current state | Root cause |
|----------|---------------|------------|
| **Blended — Gradient (canonical)** | Canonical list present; **discoveries: []** in export. | GET `/api/registries` builds `dynamic.gradient` **only from `learned_blends`** where `domain === "gradient"`. Per-window discoveries are sent as `body.gradient` and stored in **`learned_gradient`** table; that table is **not** read by the registries endpoint. So gradient **discoveries** from per-window extraction never appear in the export. Blends with domain `"gradient"` are only added by `grow_and_sync_to_api()` from **spec** (intended gradient_type); if that path runs, they should appear in `learned_blends` and thus in the UI. |
| **Blended — Camera** | Same: canonical present; **discoveries: []**. | Same as gradient: registries endpoint reads only **learned_blends** (domain `"camera"`). Per-window camera goes to **learned_camera** table and is not merged into the registries response. |
| **Blended — Sound** | Canonical (tempo/mood/presence) present; **discoveries: []**. | Registries endpoint builds `dynamic.sound` from **learned_blends** where `domain === "audio"`. `grow_and_sync_to_api()` does append an **audio** blend from spec (tempo, mood, presence). So either (a) very few runs have sent audio blends, or (b) they are stored but under a different shape. Per-instance **audio_semantic** discoveries go to **learned_audio_semantic** table, which is also **not** merged into GET /api/registries. |

**Conclusion:** The registries API should **merge** discovery data from:
- `learned_gradient` → `dynamic.gradient`
- `learned_camera` → `dynamic.camera`
- `learned_blends` (domain `audio`) + optionally `learned_audio_semantic` → `dynamic.sound`

so that per-window and per-run discoveries show up in the export.

---

## 2. Questionable categories: depth % vs “depth towards primitives”

### 2.1 Blended — Colors (learned)

- **Current:** Each learned color has **depth_pct** and **depth_breakdown** (e.g. black 50%, white 50%). The Worker computes these **on the fly** with `colorDepthVsPrimitives(r,g,b)` which uses **only luminance** → black/white. The **learned_colors** table does **not** store depth; the API has no `depth_breakdown` column for learned_colors.
- **Your requirement:** “There should only be one depth % which gives comparison percentages with respect to the pure (static) values.”
- **Issue:** (1) Two column labels (“Depth %” and “Depths towards primitives”) suggest two concepts; they are actually one concept (composition vs pure primitives). (2) Learned colors are currently forced to B/W-only; REGISTRY_FOUNDATION and `blend_depth.compute_color_depth()` use **all 16 color primitives** for static; learned colors should use the same for consistency.

**Recommendations:**

1. **Single depth concept:** Use one notion of “depth”: **depth vs pure (static) primitives**, shown as a single breakdown (e.g. “black 42%, white 58%” or “red 30%, orange 70%”) that sums to 100%. Optionally show one **depth_pct** as the dominant component or a scalar “purity” if useful.
2. **Store depth for learned_colors:** When POSTing to `/api/knowledge/discoveries` for `body.colors`, include **depth_breakdown** from Python’s `compute_color_depth(r,g,b)` (all 16 primitives). Add a `depth_breakdown_json` column to **learned_colors** (migration) and have the Worker store it. GET /api/registries then returns this stored breakdown instead of recomputing B/W only.
3. **UI:** Rename columns to a single “Depth (vs pure static)” that shows the primitive breakdown; remove the impression of two separate depth metrics.

### 2.2 Blended — Blends (other)

- **Current:** Blends (full_blend, lighting, composition, motion, color, etc.) have **depth_pct** and **depth_breakdown** with multi-domain primitives (e.g. color.gray, motion.slow, lighting.flat). These come from `primitive_depths` in `learned_blends`.
- **Your note:** “This category seems better; depth towards primitives is not only black & white.”
- **Conclusion:** Blends (other) are correct: one **depth_pct** and one **depth_breakdown** that express composition vs primitives across domains. No need for a second depth concept; only ensure the UI labels them as “depth vs primitives” (one concept).

---

## 3. Semantic (Narrative) registry — accuracy and source of data

### 3.1 Where narrative data comes from

- **Source:** `grow_narrative_from_spec()` + `extract_narrative_from_spec(spec, prompt=..., instruction=...)`. So narrative entries are **spec- and prompt-derived**, not extracted from the **video pixels or audio**.
- **Filled from:** genre, tension_curve (plots), audio_mood (mood), lighting_preset (settings), shot_type (scene_type), palette_name and palette_hints (themes), style, tone, plus **keyword matching on the prompt** (e.g. “forest”, “calm”, “neon”) for settings, genre, mood, themes.

So: **themes, plots, settings, genre, mood, style, scene_type** in the export are “what we **intended** for this run (spec + prompt)”, not “what we **observed** in the 1s video.”

### 3.2 Why videos don’t “show” themes/plots

- Each clip is **1 second**, single motion + single sound. There is no scene detection, no story beat extraction, no theme inference from frames. So it’s expected that **watching the video** you don’t see “themes/plots” — we never wrote code to infer them from the video; we only record what the **creation spec and prompt** said.
- So the narrative registry is **accurate for what it is**: a log of **intended** narrative/spec values per run, not a log of **observed** narrative content in the MP4.

### 3.3 Recommendations for Semantic (Narrative)

1. **Clarify in docs and UI:** Narrative registry = “intended (spec + prompt)”, not “observed from video”. That sets correct expectations.
2. **Optional — longer videos:** If you try longer videos (e.g. 5–10s) with multiple segments, you could later add **narrative-from-video** (e.g. per-segment mood/setting inference) and a separate “observed narrative” store. Not required for 100% accuracy of the **current** registry.
3. **Optional — narrative extraction from video:** Future work: scene/shot classification, mood/pace from motion and color over time, to populate an “observed narrative” layer. Out of scope for “fix current workflows to be 100% precise” but aligns with “all possible data from MP4”.
4. **Keep current narrative pipeline precise:** Ensure `extract_narrative_from_spec` and keyword sets (e.g. setting_keywords, theme_keywords) are complete and consistent with REGISTRY_FOUNDATION and that every run that has a spec still calls `grow_narrative_from_spec` and syncs to the API.

---

## 4. Interpretation registry — workflow and prompt creation

### 4.1 Current workflow

- **Storage:** Resolved prompts (prompt → instruction_json) in D1 `interpretations` (status = 'done').
- **Interpret loop:** `scripts/interpret_loop.py` polls `GET /api/interpret/queue`, runs `interpret_user_prompt(prompt)`, stores via `PATCH /api/interpret/:id` or `POST /api/interpretations`.
- **Prompt creation:** Main loop uses `get_knowledge_for_creation`; when exploring, with ~35% probability it picks from **interpretation_prompts** (pre-interpreted user prompts). New procedural prompts come from `generate_procedural_prompt()` (e.g. in `automation/prompt_gen.py` or `interpretation/prompt_gen.py`) using keywords, slang/dialect, and knowledge (learned colors, motion, etc.).

### 4.2 Your requirements

- **Creating new prompts:** Readable English; expand with slang/dialect and variants.
- **Extracting and growing from:** Previously produced prompts + primitive/origin prompts; same word with different meanings should be extractable and grown (linguistic registry).

### 4.3 Gaps and recommendations

1. **Volume of recorded interpretations:** “Not many prompts recorded” — ensure every path that completes a job **optionally** enqueues the prompt for interpretation (if not already interpreted) and that the interpret worker runs often enough. Backfill: scripts like `backfill_interpretations` to create interpretation rows from existing jobs.
2. **Prompt generation standard:** `interpretation/prompt_gen.py` and automation prompt_gen should generate **readable English** prompts (templates, slang/dialect from LOOP_STANDARDS), and avoid gibberish. Use `interpretation_prompt_gen.generate_procedural_prompt(avoid=..., knowledge=...)` with interpretation_prompts in avoid so we don’t duplicate.
3. **Extract + grow from prompts:** After each interpretation, run **linguistic extraction** (e.g. `extract_linguistic_mappings`) and POST to `/api/linguistic-registry/batch` so span→canonical (synonym, dialect, slang) are stored. That “grows” from previous prompts and primitives. Ensure this runs in the interpret loop and that the parser uses the merged linguistic lookup (origin + built-in + fetched).
4. **Same word, different meanings:** Track domain when storing mappings (e.g. “crane” → camera vs “crane” → bird). Parser already resolves by domain; ensure the linguistic registry stores **domain** and the merge logic uses it so “same word, different meaning” gets distinct canonical mappings per domain.

---

## 5. Diagnostics — missing learning and discovery

- **Observed:** Last 20 jobs: 4 missing learning, 3 missing discovery.
- **Hint (Worker):** “Missing learning: POST /api/learning may have failed or job completed via different path. Missing discovery: POST /api/knowledge/discoveries with job_id may have failed or path did not pass job_id.”

### 5.1 Where learning and discovery are called

- **automate_loop.py:** After each run: `post_all_discoveries(..., job_id=job_id)`, then `grow_and_sync_to_api(..., job_id=job_id)`, then a guaranteed `post_discoveries(api_base, {"job_id": job_id})` so discovery run is recorded even if growth failed, then `POST /api/learning` with job_id.
- **generate_bridge.py (--learn):** After upload: growth + `post_*_discoveries` + `grow_and_sync_to_api` + `POST /api/learning`. If **--learn** is not passed, learning is **not** logged.
- Jobs completed **without** going through automate_loop or generate_bridge --learn (e.g. manual upload, or a different worker path) will have no learning_run and possibly no discovery_run.

### 5.2 Recommendations

1. **Always pass job_id:** Every completion path that should count in diagnostics must POST to `/api/knowledge/discoveries` with `job_id` (and optionally other payload) and POST to `/api/learning` with `job_id`. Ensure generate_bridge and any other entry points do this when “learning” is intended.
2. **Retries:** Both POSTs already use `api_request_with_retry`; keep retries and timeouts (e.g. 45s for learning) so transient failures don’t leave jobs without learning.
3. **Backfill (optional):** Script that, for completed jobs (status=completed, r2_key present) without a row in `learning_runs`, POSTs to `/api/learning` with job_id and minimal spec/analysis from jobs table or a default. Same idea for discovery_runs if you want to backfill “attempted” discovery.
4. **Worker:** Ensure `discovery_runs` is inserted whenever `job_id` is present in the discoveries POST (even if no other keys are sent); the code already does this.

---

## 6. Prioritized plan: 100% precision and accuracy

### Priority 1 — Critical (precision of core pipelines)

1. **Depth for learned colors (single concept, vs pure static)**  
   - In Python: when sending `body.colors` to discoveries, attach **depth_breakdown** from `compute_color_depth(r,g,b)` (16 primitives).  
   - Worker: add `depth_breakdown_json` to **learned_colors** (migration); store and return it in GET /api/registries.  
   - UI/export: single “Depth (vs pure static)” column; drop duplicate “Depth %” vs “Depth towards primitives” for learned colors.

2. **Registries API: merge gradient/camera/sound discoveries**  
   - GET /api/registries: for `dynamic.gradient`, merge rows from **learned_gradient** (and optionally dedupe with learned_blends domain=gradient).  
   - Same for **learned_camera** → `dynamic.camera`.  
   - For `dynamic.sound`, merge **learned_blends** (domain=audio) and optionally **learned_audio_semantic** so Blended — Sound shows discoveries.  
   - Ensures per-window and per-run discoveries appear in the export and UI.

3. **Learning and discovery diagnostics**  
   - Ensure every completion path that should be counted calls POST /api/learning and POST /api/knowledge/discoveries with **job_id**.  
   - Document which paths are “learning” paths (e.g. automate_loop, generate_bridge --learn).  
   - Optional backfill script for learning_runs/discovery_runs for already-completed jobs.

### Priority 2 — High (accuracy and clarity)

4. **Narrative registry: document and optionally extend**  
   - Document clearly: narrative = intended (spec + prompt), not observed from video.  
   - Keep `extract_narrative_from_spec` and keyword sets aligned with REGISTRY_FOUNDATION; ensure narrative sync runs for every run with a spec.  
   - Optional: design “observed narrative” (from video) for longer/multi-segment clips later.

5. **Interpretation + linguistic workflow**  
   - Ensure interpret loop (or equivalent) runs linguistic extraction after each interpretation and POSTs to linguistic registry (with domain where applicable).  
   - Prompt generation: readable English only; use interpretation_prompts in avoid set; grow from primitives + previous prompts.  
   - Same word / different meaning: store and resolve by domain in the linguistic registry and parser.

6. **UI/export: single depth concept for Blended**  
   - Blended — Colors (learned): one “Depth (vs pure static)” (breakdown + optional single pct).  
   - Blended — Blends (other): keep one depth_pct + depth_breakdown; label as “Depth vs primitives” so it’s clear it’s one concept.

### Priority 3 — Medium (data completeness)

7. **Pure static sound**  
   - Implement per-frame or per-segment **audio decoding** from MP4; map to primitives (silence, rumble, tone, hiss) and strength_pct; call `ensure_static_sound_in_registry` with extracted values and sync to API.  
   - Until then, keep spec-derived static sound; document that static sound is spec-derived until extraction exists.

8. **Dynamic audio_semantic in registries**  
   - If you want “Blended — Sound” to include per-instance audio_semantic (role/mood/tempo) from discovery, merge **learned_audio_semantic** into GET /api/registries `dynamic.sound` (with a clear shape so it doesn’t clash with tempo/mood/presence blends).

### Priority 4 — Ongoing

9. **Algorithms and functions audit**  
   - Go through each workflow (interpretation, creation, extraction, growth, sync) and list every function that affects registries. Ensure each has a single, documented contract (inputs, outputs, side effects) and tests where feasible.  
   - Align with REGISTRY_FOUNDATION and LOOP_STANDARDS so “100% precise” is verifiable.

10. **Longer videos / multi-segment**  
    - If you introduce longer or multi-segment videos, revisit narrative-from-video and ensure windowing and aggregation still feed the same registries without double-counting or key collisions.

---

## 7. Video progression and pure-per-frame creation (creation-phase behaviour)

**Goal:** Videos should **progress** as more loops run: more unpredictable, less “one blend of colors + one motion + one sound”. Workflows and processes must **never be static** — algorithms and functions must **always** use **origin/primitive + previously extracted (named) values** when creating and rendering. The creation phase should favour **pure values per frame**: for **visuals**, randomly selected pure colors at random **pixel** locations (x, y) within each frame; for **audio**, numerous pure noises/sounds from the registry **within one frame** combining into **one final sound** for that frame (discovering a new sound). So **new blends emerge** and are then extracted and recorded in Blended (dynamic) and Semantic (narrative) registries.

### 7.1 Principles

**Workflow split (precision):** One workflow is dedicated to **pure/static** values (per-frame: many pure values in one frame → discoveries); another to **blends** (windows of frames, temporal). For **sound**, the pure/static workflow is focused on **numerous noises/sounds within one frame** combining into **one final sound** for that frame (essentially discovering a new sound). The blended workflow focuses on **melody**, **dialogue**, and other temporal sound aspects.

1. **No static behaviour in creation**  
   - No fixed “default palette” or single fallback that ignores the registry.  
   - Every choice (color, motion, sound, gradient, camera) must come from: **(a)** origin/primitive sets, or **(b)** previously extracted values that have been given authentic names and stored in the registries.  
   - Algorithms and functions in the creation pipeline must be **parameterised by** and **driven by** this data (from API or local registry), not by hardcoded lists used as the primary source.

2. **Unpredictability**  
   - Creation should be **unpredictable** (random selection from the pool of valid values) while still **conceptually aligned** with the prompt/spec (e.g. motion type, palette *concept*).  
   - The pool itself grows over time (origin + learned + discovered), so as loops run, the variety of possible outputs grows.

3. **Pure-per-frame as the main creation mode**  
   - **Idea:** For each frame, **randomly select pure values from the registry** (origin/primitive + previously extracted named values) and **place them at randomly selected pixel locations (x, y) within that frame**. Within a single frame there is no “time” dimension — time is relevant only **across frames** (e.g. in windows of multiple frames used by extraction). So: per frame = random choice from registry, random **pixel** placement only.  
   - Result: each frame is built from many pure values at different **(x, y)** positions; across frames the pattern can change (so extraction over **windows** of frames sees spatial and temporal variation) and records new blends in Blended (dynamic) and Semantic (narrative).  
   - **Sound (same precision):** Within **one frame** (one audio time-slice), **numerous pure noises/sounds** from the registry (silence, rumble, tone, hiss + discovered static sounds) execute together and combine into **one final sound** for that frame — **discovering a new sound** in the pure/static registry. The **blended** workflow focuses on melody, dialogue, etc. over windows of frames. So: pure/static = many sounds in one frame → one resulting sound (new discovery); blended = melody, dialogue, etc.  
   - This is in contrast to the current “one blended palette + one gradient + one motion” per clip, which yields a single dominant blend per video.

4. **Same concept, emergent blends**  
   - The **concept** (e.g. “warm”, “calm”, “neon”) is still respected via which **primitives and learned values** are in the pool (e.g. prompt → subset of palettes/primitives).  
   - The **actual pixels and samples** are determined by **random selection of pure values and random placement**, so the same concept can produce different emergent blends every time.

### 7.2 Implementation items (creation pipeline)

| Item | Description |
|------|-------------|
| **Pure color pool for creation** | Builder (or equivalent) builds a **pool of pure colors**: (1) **Origin primitives** (STATIC_COLOR_PRIMITIVES / COLOR_ORIGIN_PRIMITIVES), (2) **Discovered static colors** from the registry (names + RGB). No creation path should use a fixed palette as the only source; always merge origin + discovered. |
| **Pure-per-frame render mode** | Renderer supports a **creation_mode** (e.g. `pure_per_frame`): for each frame, randomly select pure colors **from the registry** (origin + discovered) and assign them to **random pixel locations (x, y)** within that frame. Within one frame only spatial (pixel) placement applies; time is relevant only across frames (e.g. hash can include frame index so the pattern varies per frame → emergent blends in multi-frame windows). Motion/camera can still apply. |
| **Spec carries pure data** | SceneSpec (or equivalent) carries **pure_colors** (list of (R,G,B)) and **creation_mode**. When creation_mode is pure_per_frame, the renderer uses only these pure colors and random placement; no single blended “palette” gradient for the whole frame. |
| **Motion and gradient from registry** | Motion type, gradient type, camera type: always chosen from **origin_* + learned_*** (no hardcoded default list as primary). Builder already uses _pool_from_knowledge; ensure no code path falls back to a single static default when the pool is non-empty. |
| **Sound: pure per frame (static workflow)** | Within **one audio frame** (one time-slice), **numerous pure sound primitives** from the registry (silence, rumble, tone, hiss + discovered static sounds) are combined; the result is **one final sound** for that frame, which is **discovered as a new (pure) sound** in the static registry. **Blended** workflow handles melody, dialogue, etc. over windows of frames. Creation: randomly select multiple pure noises per frame, mix them → one output sound per frame → extraction records new pure sounds. |
| **Extraction unchanged** | Extraction and growth (per-frame static, per-window dynamic, narrative from spec) remain as today; they will naturally record the **new blends** that emerge from pure-per-frame creation. |

### 7.3 Success criteria

- As loop count increases, **videos are visibly more varied** (different spatial color distribution, different dominant “blends” per run).  
- **No creation path** uses a fixed “default” palette or motion when the registry (origin + learned) has values available.  
- **Creation uses pure values from the registry:** visuals = random pixel locations (x, y) per frame; **audio = numerous pure noises in one frame → one final sound per frame** (new sound discovery in pure/static). Time is relevant only in **multi-frame windows** (blended extraction). Blended workflow focuses on melody, dialogue, etc.; pure/static focuses on discovering new sounds from many noises in one frame.

### 7.4 Implementation status (creation pipeline)

- **SceneSpec** (`procedural/parser.py`): Added `pure_colors: list[tuple[int,int,int]] | None` and `creation_mode: str` (`"blended"` | `"pure_per_frame"`).
- **Builder** (`creation/builder.py`): `_build_pure_color_pool(knowledge, instruction)` builds the pool from **COLOR_ORIGIN_PRIMITIVES** (blend_depth) plus **learned_colors** from knowledge; never uses a fixed default list. Spec is always given `pure_colors` and `creation_mode` (`"pure_per_frame"` when pool is non-empty).
- **Renderer** (`procedural/renderer.py`): When `creation_mode == "pure_per_frame"` and `pure_colors` is set, `_render_pure_per_frame()` assigns to each pixel a pure color from the registry pool: **per frame**, the choice is a deterministic function of **pixel location (x, y)** (and optionally frame index so the pattern varies across frames; time is not a dimension within a single frame). Camera transform and light noise still apply; extraction over **windows of frames** then sees spatial and temporal variation and records new blends. Blended mode (single gradient + palette) remains when `pure_colors` is empty.
- **Knowledge**: Generator already calls `get_knowledge_for_creation(config)` and passes `knowledge` into `build_spec_from_instruction`; origin + learned colors are thus always used when available. No change required.

**Sound:** Pure-per-frame audio (numerous pure noises from the registry combined **within one frame** → one final sound per frame → new sound discovery in static registry) is not yet implemented; audio remains mood/tempo/presence-driven. Blended sound (melody, dialogue, etc.) is the domain of the blended workflow. Planned as a follow-up.

### 7.5 Three workflows: 2 frame-focused, 1 window-focused

- **2 workflows** are dedicated to **extraction + discovery within an individual frame** (pure/static): they run per-frame extraction only, grow only the static registry (colors, sound), and record every new value with a **newly created (authentic) name**. Use **LOOP_EXTRACTION_FOCUS=frame** on both workers. Prompt choice can differ (e.g. one with **LOOP_EXPLOIT_RATIO_OVERRIDE=0** for explore, one with **LOOP_EXPLOIT_RATIO_OVERRIDE=1** for exploit) so you get two frame-focused workflows (e.g. frame-explorer and frame-exploiter).
- **1 workflow** is dedicated to **discovering + extracting blends within windows of frames** (blended/dynamic): it runs per-window extraction only, grows dynamic and narrative registries, and posts dynamic + narrative discoveries plus whole-video aggregates (learned_colors, learned_motion, learned_blends). Use **LOOP_EXTRACTION_FOCUS=window** on that worker.
- **LOOP_EXTRACTION_FOCUS** = `frame` | `window` | unset. Unset (or invalid) = **all** (current behaviour: both per-frame and per-window growth and post). Implemented in `grow_all_from_video(..., extraction_focus=...)` and in `automate_loop.py` (gating of growth, post_static vs post_dynamic/post_narrative, and grow_and_sync_to_api).

---

## 8. Summary table

| Area | Issue | Action |
|------|--------|--------|
| Pure sound | Sparse; only spec-derived | Implement audio extraction from MP4 → primitives; document until then. |
| Blended gradient/camera/sound | Discoveries empty in export | Merge learned_gradient, learned_camera, learned_blends (audio) / learned_audio_semantic into GET /api/registries. |
| Blended colors (learned) | Two depth concepts; B/W only | Single “depth vs pure static”; store 16-primitive depth_breakdown for learned_colors; UI one column. |
| Blended blends (other) | OK | Keep one depth; label clearly. |
| Semantic (Narrative) | “Wrong” themes/plots | Clarify: intended from spec+prompt, not from video; optional narrative-from-video later. |
| Interpretation | Few prompts; growth | Record more interpretations; extract+POST linguistic mappings; prompt gen = readable English; domain for same word different meaning. |
| Diagnostics | Missing learning/discovery | job_id on every path; retries; optional backfill. |
| Mission | 100% precision/accuracy | Priorities 1–2 first; then 3–4; audit algorithms per workflow. |
| Creation progression | One palette/motion/sound per video | §7: pure-per-frame creation; origin + learned only; random pure placement → emergent blends. |

This plan prioritizes correctness of existing workflows and registries first, then fills gaps (sound extraction, narrative-from-video, interpretation volume) and **creation-phase behaviour** (§7) so that videos progress and become more unpredictable over time while always using origin + learned data and producing extractable blends.
