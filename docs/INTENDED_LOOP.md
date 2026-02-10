# The Intended Loop

This document describes the core design of Motion Productions: **foundation**, base knowledge from **origins** (primitives of every film/video aspect), continuous **interpretation** of user prompts, and a **learning loop** that grows knowledge from every generation.

---

## The Foundation

**Base knowledge** is everything that resides within video files: colors, graphics, resolutions, motion, frame rate, composition, brightness, contrast, consistency over time — every aspect that makes a video what it is.

As the program loops continuously, it **extracts every single thing** from this base knowledge. Each generation is analyzed; each analysis feeds back into the knowledge base.

With all that information extracted and available, the software is **capable of creating and producing videos** from a text, script, or prompt provided by a user. User input drives generation; generation is informed by everything we have learned from the base knowledge.

**The cycle:** Base knowledge → Continuous loop (extract every aspect, each output → analysis → knowledge update) → Video creation (user provides prompt; software produces video from extracted knowledge).

---

## Vision

Motion Productions is built to be the **go-to AI video generator**. The software:

1. Uses the **origins** (fundamental primitives) of every aspect within filmmaking/video-making as its ground truth — base knowledge.
2. Is **ready for any user prompt** — abstract, unexpected, novel. The system interprets whatever the user provides without being limited to predefined templates.
3. **Grows continuously** — each generation is analyzed; what emerges from blending primitives becomes new knowledge. The more it generates, the more it learns.

---

## The Loop

```
┌─────────────────────────────────────────────────────────────────────────┐
│  ORIGINS (Base Knowledge)                                                │
│  Primitives of every film/video aspect: color, motion, lighting,         │
│  composition, temporal, audio, narrative, technical.                     │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  USER PROMPT (arbitrary input)                                           │
│  "A dreamy ocean at dusk with slow waves"                                │
│  "Explain quantum tunneling in 10 seconds"                               │
│  "Fast neon city pulse with parallax"                                    │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  INTERPRETATION                                                          │
│  Map prompt → pure elements or non-pure elements (from origins +         │
│  registries). Goal: provide something new each loop for extraction/growth│
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  CREATION (instruction → spec)                                            │
│  Follow instruction 100% precisely. Use only static elements (same       │
│  registry as growth). Output: spec (blueprint). No pixels yet.            │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  RENDERER → OUTPUT (spec → MP4)                                           │
│  Color + sound on every frame. Pipeline assembles frames → video file.   │
│  Blends (non-pure) form over the duration of the video.                  │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  EXTRACTION                                                              │
│  Analyze output: colors, motion, lighting, composition, consistency      │
│  Capture what actually appeared in the video                             │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  GROWTH (static + narrative only)                                        │
│  Compare extracted STATIC (color, sound) to registry; if novel → add     │
│  with name. Narrative from spec → add if novel. Dynamic not grown       │
│  (preserves algorithmic precision).                                     │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    └──────────────────┐
                                                       │
                                    ┌──────────────────┘
                                    ▼
                         NEXT GENERATION
                    (can use origins + learned)
```

---

## Principles

### 1. Origins as Ground Truth

Base knowledge is **not** arbitrary named styles. It is the **primitives** of each domain:

| Domain | Primitives (origins) |
|--------|----------------------|
| **Color** | RGB, HSL; brightness, contrast, saturation |
| **Motion** | Speed, smoothness, directionality, rhythm, steadiness |
| **Lighting** | Key, fill, rim, ambient; contrast, saturation |
| **Composition** | Center of mass, balance, symmetry, framing |
| **Temporal** | Pacing, cut frequency, shot length |
| **Camera** | Pan, tilt, dolly, crane, zoom, static |
| **Transitions** | Cut, fade, dissolve, wipe |
| **Audio** | Tempo, mood, intensity, silence |
| **Narrative** | Genre conventions, tension curve |

### 2. Blending Uses Pure Elements Only; Pure Blends → Static Registry

Blending functions operate on **origin primitives and all values in the static registry** (pure elements only). They do not target dynamic or narrative values, since those are non-pure. When pure elements are combined, the result may be a **pure blend that becomes a single value**; these are added to the **STATIC registry** in the workflow (e.g. during growth or a dedicated step). **Growth and creation both use this same STATIC registry** (plus origins as primitives).

**Blend depth:** Depth is computed for **all pure (static) elements** with respect to **origin primitives**. It answers: how much did each primitive contribute to this value? Example: gray = 50% white + 50% black → depths relative to the primitives white and black. This enables explaining any static value in terms of its primitive contributions.

### 3. Interpretation Outputs Pure or Non-Pure Elements

The interpreter does not assume a fixed vocabulary. It maps whatever the user provides into **pure elements or non-pure elements** (from origins and registries). The goal is not to “cause blending,” but to provide **something new** each loop so that extraction and growth can happen — an optimization for self-learning. It:

- Maps input to primitives or learned static/narrative as appropriate
- Infers from context when words are unfamiliar
- Handles negations, intensity modifiers, duration, style
- Falls back to origins when no match exists

### 4. Creation vs Renderer (what each step is)

- **Creation** is the step that takes the **interpreted instruction** and produces a **spec** (e.g. SceneSpec): *what* the video should be. No pixels and no audio file exist yet. Creation outputs a blueprint: which colors, which motion, duration, lighting, etc. It should follow instruction flawlessly and use **only static elements (values)** from the static registry (and origins) for optimal results — not a mix of pure and non-pure blends. So: **instruction → spec**.

- **Renderer** is the step where the **video is actually put together** into the MP4. The renderer turns the spec into **pixel frames** (spec + time → one RGB frame per time step). **Color and sound are incorporated into every frame** (or per-segment for audio). The pipeline then assembles frames and audio into the final MP4 file. Over the **duration** of the entire video, non-pure **blends form as a result of the sequence** (e.g. motion, mood, pacing across time). So: **spec → frames (color + sound per frame) → pipeline → MP4**.

**In short:** Creation = decide *what* to make (spec). Renderer (+ pipeline) = build *the actual video file* (pixels + sound → MP4).

### 5. The Loop Never Stops

Each run: **prompt → interpret → create → render → output → extract → grow**. The more the loop runs, the richer the knowledge and the better the system interprets and generates.

---

## Learning efficiency: short vs long videos

**Shorter videos (e.g. 1 second) are more efficient for learning** when the goal is to populate the static and narrative registries (growth does not touch dynamic):

| | 1s video | 30s video |
|---|----------|-----------|
| **Static (per frame)** | ~24 frames → 24 color/sound instances to check and record | ~720 frames; we often sample (e.g. every 2nd) so ~360 instances from one prompt |
| **Per run** | Less I/O and compute; one clear pass over frames | More frames per job but all from one creative run |
| **Diversity** | More distinct prompts per hour (e.g. 60× 1s vs 2× 30s) → more variety in static/narrative | Fewer prompts per hour → less variety per unit time |

So: **1s (or 2–3s) is better when the loop’s goal is to learn**: easier to record every frame, cheaper per run, and more different prompts per hour so the static and narrative registries see more variety. Longer durations (5–30s) are still useful for “deeper” temporal variety from a single prompt or for final output quality.

**How to use:** Set `learning.duration_seconds: 1` in `config/default.yaml` to run the loop with 1s videos; or run `python scripts/automate_loop.py --duration 1` so every run uses 1s. For generate_bridge, duration comes from the job (user-selected); for learning-focused jobs you can create 1s jobs from the app or API.

---

## Loop workflow (step-by-step)

One full loop iteration:

| Step | What happens | Where |
|------|----------------|-------|
| **1. Pick prompt** | **Exploit:** reuse a **good prompt** (one that previously met quality thresholds). **Explore:** use a **new procedural prompt** (programmatically generated subject + modifier combo, avoiding recent). See *Good vs procedural prompt* below. | `scripts/automate_loop.py` → `pick_prompt()` |
| **2. Create job** | POST `/api/jobs` with prompt + duration. Get `job_id`. | `automate_loop.py` |
| **3. Interpret** | Map prompt → pure elements or non-pure elements (from origins + registries). Goal: something new each loop for extraction/growth. | `src/interpretation/` → `interpret_user_prompt()` |
| **4. Create (instruction → spec)** | Build spec by **precisely following instruction** (100% precise). Use **only static elements** (same STATIC registry as growth). **Creation includes audio/sound:** spec defines audio_tempo, audio_mood, audio_presence (sound is part of the blueprint). Output = spec (blueprint); no pixels yet. | `src/creation/` → `build_spec_from_instruction()` |
| **5. Render → MP4** | **Renderer:** spec + time → pixel frames; **color + sound on every frame** (audio from spec). Pipeline assembles frames + audio → MP4. Blends (non-pure) form over the duration. | `src/procedural/renderer.py` → `render_frame()`; `src/pipeline.py` → `generate_full_video()` |
| **6. Upload** | POST video to `/api/jobs/{id}/upload`. | `automate_loop.py` |
| **7. Extract** | Per-frame **static (color + sound)**; full-video analysis (motion, brightness, etc.). **Sound is extracted** like color (sound is in the STATIC registry). Extraction captures what actually appeared. | `src/knowledge/` → `extract_from_video()`, `extract_static_per_frame()` |
| **8. Growth (all three registries)** | **Static:** Compare extracted color + sound (single-frame/pure) to static registry; if novel → add with name. **Dynamic:** Compare extracted non-pure (2+ frames) to dynamic registry; if novel → add with name (new styles, e.g. sunset + sunrise blend). **Narrative:** From spec → add if novel. **Unknown names → sensible generated name in every registry.** Target: 95%+ of successful loops with successful growth. | `grow_from_video()` (static), `grow_dynamic_from_video()` (dynamic), `grow_narrative_from_spec()` (narrative) |
| **9. Sync discoveries** | POST static, dynamic, and narrative novel entries to API (D1). Optional: whole-video composite records (e.g. learned_blends) for loop analytics. | `post_static_discoveries()`, `post_dynamic_discoveries()`, `post_narrative_discoveries()`; `grow_and_sync_to_api()` for composite |
| **10. Learning log** | POST `/api/learning` with job_id, prompt, spec, analysis (for UI/history). | `automate_loop.py` |
| **11. Update state** | Increment run_count; append prompt to recent/good. Save state to KV. | `automate_loop.py` → `_save_state()` |

**Good prompt vs new procedural prompt**

- **Good prompt:** A prompt that has **already been run** and whose output **met quality thresholds** (e.g. brightness consistency and motion level in a target range). The loop stores these in `good_prompts` and, when **exploiting** (e.g. 70% of the time), picks one at random to reinforce quality.
- **New procedural prompt:** A **programmatically generated** prompt: random combination of subject + modifier(s) from a base set plus knowledge-expanded terms, using templates (e.g. “{subject}, {mod1}” or “{subject}, {mod1} and {mod2}”). It **avoids recently used** prompts so each run can explore new combinations. When **exploring** (e.g. 30% of the time), the loop uses this to discover new colors/sounds/narrative and fill the registry.

So: **good** = reuse a prompt that worked well; **procedural** = generate a new combo for exploration. Configurable via `exploit_ratio` (e.g. 70% exploit / 30% explore).

**Accuracy vs precision:** Registries (static, narrative) stay **100% accurate**. Algorithms and functions (extraction, growth, blending) live in code and stay **100% precise**. Growth only touches static and narrative so that precision is not diluted by non-pure (dynamic) blends.

---

## Optimizations for maximum self-learning

| Optimization | Why it helps |
|--------------|--------------|
| **Short duration (1–2 s) for learning** | More runs per hour → more distinct prompts → more variety in static/narrative registries. One window per video keeps extraction cheap. |
| **Growth = static + narrative only** | Keeps growth logic precise. Dynamic elements are non-pure; not growing them avoids diluting algorithmic precision. |
| **95%+ of successful loops → successful growth** | Target: the program should be learning in 95%+ of loops that complete successfully (i.e. growth/learning happens in almost every run). |
| **Exploit/explore balance** | Reuse prompts that yielded good outcomes (exploit) so quality is reinforced; sometimes pick new prompts (explore) so registries see new colors/sounds/narrative. Configurable via loop config (e.g. 70% exploit / 30% explore). |
| **Per-frame static extraction** | Every frame checked for novel color/sound. Use `sample_every` (e.g. 2) to trade off cost vs coverage. |
| **Name reserve + English-like names** | New static values get consistent, pronounceable names so the registry stays usable and human-readable. |
| **API retries + failure handling** | Loop survives transient API errors; state and discoveries are not lost. |
| **Knowledge fetch before each run** | Creation and prompt picking use latest learned static/narrative from D1 so each generation benefits from prior runs. |

See [ENHANCEMENTS_AND_OPTIMIZATIONS.md](ENHANCEMENTS_AND_OPTIMIZATIONS.md) for the enhancement checklist and [REGISTRY_TAXONOMY.md](REGISTRY_TAXONOMY.md) for what lives in static vs dynamic vs narrative.

---

## Dual-workflow design (prompt/interpretation vs growth/learning)

Both workflows include **growth + learning** and **creation + rendering**. **All three registries (static, dynamic, narrative) evolve via growth** as the continuous loop runs: compare to registry → if novel, add with a **sensible generated name when the element/blend is truly unknown** — for **every** registry.

- **Pure elements and pure blends with a distinct value within one frame** → **STATIC** registry (color or sound). Growth adds if novel with name.
- **Non-pure blends (values that arise from the combination of 2+ frames)** → **DYNAMIC** or **NARRATIVE** registry (by category). **Growth** adds if novel with name. For example, blending a non-pure “sunset” blend and a non-pure “sunrise” blend can form a **new non-pure blend** that is added to the dynamic registry as a new **style** (with a sensible name when unknown).

Algorithms and functions must be **100% precise** with these rules so the registries stay 100% accurate.

---

**Workflow A — Prompting and interpretation (specialized)**

- **Specialization:** Interpreting **human input** and preparing for the fact that every true user prompt is **unknown** to the software before it happens. The system must be **ready for anything and everything** with respect to prompting.
- **Still incorporates:** Growth + learning and creation + rendering. So the full loop runs (interpret → create → render → extract → grow → sync), but the *focus* is on interpretation: map any user prompt → pure or non-pure elements so creation can follow instruction precisely. Prompt selection can use past loop results and, over time, try every combination/blend of origin/primitive values (systematic or exploratory) so the registry can become fully complete.
- **Goal:** Continuously learn from the past loop; handle any user prompt; feed precise instructions into creation so that extraction and growth can add what actually appeared to all three registries (with sensible names when unknown).

---

**Workflow B — Growth and learning (discovery + growth in all three registries)**

- **Specialization:** **Discovery and growth** of new values. Every frame is made up of elements down to the pixel (sound + color). Blends occur within a single frame (pure blend → static) or **within a timespan of 2+ frames** (non-pure → dynamic or narrative). **All three registries undergo growth:** static (pure/single-frame), dynamic (non-pure/multi-frame, e.g. new “styles” from blending sunset + sunrise), narrative (imaginable non-pure). If the name of any element/blend is truly unknown, **always provide a sensible generated name — for every registry**. Newly discovered pure values are incorporated into creation + rendering so the registry keeps evolving every loop.
- **Still incorporates:** Growth + learning and creation + rendering. The full loop runs; the *focus* is on extraction → compare to registries → **grow** (add if novel with name): pure/single-frame → static; non-pure/multi-frame → dynamic or narrative; and on feeding the latest registries (and origins) into creation so every new loop can use newly discovered values.
- **Goal:** Grow all three registries from what actually appeared; pure → static, non-pure (2+ frames) → dynamic or narrative (new styles/blends with sensible names); target 95%+ of successful runs with successful growth; creation and rendering use the evolving registries.

---

**Growth rules (both workflows) — all three registries evolve**

| What appeared | Where it goes | Growth |
|---------------|---------------|--------|
| Pure element (single frame: one color, one sound value) | **STATIC** registry (color or sound) | Add if novel; **sensible generated name when unknown**. |
| Pure blend that becomes a **single value within one frame** | **STATIC** registry (color or sound) | Same as above. |
| Non-pure blend (value from **2+ frames** combined, e.g. motion over a window; or blending non-pure sunset + sunrise → new style) | **DYNAMIC** or **NARRATIVE** registry | **Growth:** add if novel; **sensible generated name when unknown**. Provides new “styles” per se. |
| Imaginable non-pure (plot, setting, theme, mood, etc.) | **NARRATIVE** registry | Add if novel; sensible generated name when unknown. |

**Result**

- **Workflow A** keeps the system ready for any user prompt and ensures interpretation + creation + rendering + extraction + **growth (all three registries)** all run so the loop learns from every run.
- **Workflow B** ensures every run contributes to **all three registries** via growth (pure → static, non-pure → dynamic/narrative, with sensible names when unknown), and newly discovered values are used in creation and rendering so the registries are always evolving.

---

### Railway / Render: same loop, two focuses (optional third)

**Both workflow types run the same code path** (`scripts/automate_loop.py`). Every run does: pick prompt → interpret → create → render → extract → grow (static + dynamic + narrative) → sync. The only lever is **how the prompt is chosen** (exploit vs explore), which aligns with Workflow A vs B *focus*:

| Railway/Render worker | Env | Focus | Aligns with |
|------------------------|-----|--------|-------------|
| **Explorer** | `LOOP_EXPLOIT_RATIO_OVERRIDE=0` | 100% explore — new combos, broad discovery | **Workflow B** (growth / discovery) |
| **Exploiter** | `LOOP_EXPLOIT_RATIO_OVERRIDE=1` | 100% exploit — reuse known-good prompts | **Workflow A** (interpretation / refinement) |
| **Balanced (main)** | (none; uses webapp config) | e.g. 70% exploit / 30% explore | Mix of both |

- **You do not need to remove the 3 workflows.** They already implement the distinction: Explorer = growth-focused loop, Exploiter = interpretation-focused loop, Balanced = mix. All three incorporate growth; all use the same pipeline.
- **Optional:** If you prefer only two services, run **Explorer** (Workflow B) + **Exploiter** (Workflow A) and omit Balanced. Config: `config/workflows.yaml`; see also `docs/AUDIO_AND_WORKFLOWS.md` and `docs/AUTOMATION.md`.

---

## Implementation

- **Origins:** `src/knowledge/origins.py` — registry of primitives per domain (the starting point of the learning curve).
- **Blending:** `src/knowledge/blending.py` — blend functions for **origin primitives and all values in the static registry** (pure elements only). Do not target dynamic or narrative values (they are not pure).
- **Blend depth:** `src/knowledge/blend_depth.py` — compute the depth of **all pure (static) elements** with respect to **origin primitives** (e.g. gray = 50% white + 50% black → depth relative to primitives).
- **Registry:** All **pure** discoveries (including pure blends that become single values) → static registry. All **non-pure** → dynamic or narrative (by category). **Growth and creation both use this same STATIC registry** (and origins). Local: `config/knowledge/` (or project `knowledge/`); when `api_base` is set, discoveries sync to D1/KV and creation fetches from GET /api/knowledge/for-creation.
- **Interpretation:** `src/interpretation/` — interpret prompts to **pure elements or non-pure elements**. Goal: something new every loop so extraction and growth can happen (optimization).
- **Creation:** `src/creation/` — **precisely follow instruction** (100% precise). Use **only static elements (values)** from the static registry (and origins). **Audio/sound is part of creation:** spec includes audio_tempo, audio_mood, audio_presence (sound is in STATIC registry and is specified here, then extracted and grown like color). Output is a **spec** (blueprint); no pixels or audio file yet. Instruction is the root cause for discoveries.
- **Growth:** `src/knowledge/growth.py` — legacy extraction → compare → add novel; **per-instance:** `grow_from_video()` (static), `grow_dynamic_from_video()` (dynamic), `grow_narrative_from_spec()` (narrative). **All three registries evolve via growth;** non-pure (2+ frames) and new blends (e.g. sunset + sunrise → new style) are added to the dynamic registry with a sensible name when unknown. Target: 95%+ of successful loops with successful growth. **If any element/blend is truly unknown, provide a sensible generated name — for every registry.**
- **Renderer:** `src/procedural/renderer.py` — the step where the **video is put together** into the MP4. **Color + sound are incorporated into every frame**. Renderer: spec + time → one RGB frame; pipeline assembles frames and adds audio → final MP4. Blends (non-pure) form over the duration of the entire video. Uses our procedural algorithms only (gradients, camera motion, lighting, shot types).

---

## Audit: algorithms and functions (100% precision vs workflows)

All algorithms and functions below must stay **100% precise** with the two workflows and recording rules:

- **Pure / single-frame distinct value** → STATIC registry (color or sound).
- **Non-pure / 2+ frames** → DYNAMIC or NARRATIVE registry (**growth:** add if novel with sensible name when unknown).
- **Workflow A:** Interpretation ready for any user prompt; growth + learning and creation + rendering present.
- **Workflow B:** Discovery + growth in all three registries; new values feed creation + rendering; unknown names get a sensible generated name in every registry.

| Area | Function / module | Purpose | Precision vs workflows |
|------|-------------------|---------|------------------------|
| **Interpretation** | `interpret_user_prompt()` | Map prompt → pure or non-pure elements (instruction). | Must support any user input; output 100% precise instruction for creation. |
| **Creation** | `build_spec_from_instruction()` | Instruction → spec (blueprint). | Must use only static elements (same registry as growth); include audio/sound in spec. |
| **Renderer** | `render_frame()` | Spec + time → one RGB frame. | Color per frame; pipeline adds sound per frame/segment. |
| **Pipeline** | `generate_full_video()` | Frames + audio → MP4. | Assembles renderer output; sound incorporated; non-pure blends form over duration. |
| **Extraction** | `extract_static_per_frame()` | Per-frame color + sound. | One frame = one static instance (pure); feeds growth. |
| **Extraction** | `extract_dynamic_per_window()` | Per-window (2+ frames) motion, time, lighting, etc. | Multi-frame = non-pure; feeds **growth** in dynamic registry. |
| **Extraction** | `extract_from_video()` | Full-video aggregate (legacy). | One summary per video; used for analysis/API; not per-frame/per-window. |
| **Growth** | `grow_from_video()` | Add novel **static** (color + sound) to registry. | Pure/single-frame only; add if novel with sensible name when unknown. |
| **Growth** | `grow_dynamic_from_video()` | Add novel **non-pure** (per-window) to DYNAMIC registry. | 2+ frames → growth in dynamic (motion, time, lighting, composition, graphics, temporal, technical, audio_semantic); new blends/styles with sensible name when unknown. |
| **Narrative** | `grow_narrative_from_spec()` | Add narrative from spec to narrative registry. | Imaginable non-pure; add if novel with sensible name when unknown. |
| **Static registry** | `load_static_registry()`, `save_static_registry()`, `ensure_static_*_in_registry()` | Persist and add static entries. | Keys/values 100% precise; pure and pure-blend-single-value only; sensible name when unknown. |
| **Dynamic registry** | `load_dynamic_registry()`, `save_dynamic_registry()`, `ensure_dynamic_*_in_registry()` | Persist and add dynamic entries. | Used by **growth** (grow_dynamic_from_video); non-pure only; sensible name when unknown (new styles). |
| **Narrative registry** | `load_narrative_registry()`, `save_narrative_registry()`, `ensure_narrative_in_registry()` | Persist and add narrative entries. | Non-pure imaginable only. |
| **Blending** | `blending.py` (e.g. `blend_colors`, `blend_palettes`) | Combine origin + static registry values. | Pure elements only; result that is single value → can become new static entry. |
| **Blend depth** | `blend_depth.py` | Depth of pure (static) elements vs origin primitives. | Per static element; not for dynamic/narrative. |
| **Lookup** | `get_knowledge_for_creation()` | Fetch static (and origins) for creation. | Creation must use this so new pure values are used next loop. |
| **Sync** | `post_static_discoveries()`, `post_dynamic_discoveries()`, `post_narrative_discoveries()` | POST novel entries to API. | Static, dynamic, and narrative from **growth** (all three registries). |

**Checks for 100% precision**

1. **Single frame** → only static extraction and static growth. No dynamic registry write from a single frame.
2. **Window (2+ frames)** → dynamic extraction and **growth** in dynamic registry (`grow_dynamic_from_video`). Non-pure blends (e.g. sunset + sunrise → new style) added with sensible name when unknown.
3. **Creation** reads from static registry + origins (and can use dynamic/narrative for non-pure styles where appropriate).
4. **Interpretation** produces instruction that creation can follow 100% precisely; no hard-coded palette/motion hints required.
5. **Loop** runs **growth for all three registries** (static, dynamic, narrative); every unknown element/blend gets a sensible generated name in the appropriate registry.

See [REGISTRY_AND_LOOP_AUDIT.md](REGISTRY_AND_LOOP_AUDIT.md) for legacy/extended audit of registry and loop functions.

---

## Summary

| Concept | Role |
|---------|------|
| **Origins** | Primitives per domain; starting point of the learning curve |
| **Interpretation** | Map prompt → pure elements or non-pure elements; goal: something new each loop for extraction/growth |
| **Creation** | Instruction → spec (blueprint). Use only static elements; follow instruction 100% precisely |
| **Renderer** | Spec → frames (color + sound every frame); pipeline → MP4. Blends form over duration |
| **Extraction** | Capture what actually appeared in output |
| **Growth** | Add novel to **all three registries** (static, dynamic, narrative); sensible generated name when unknown; target 95%+ of loops with successful growth |
| **Registry** | Pure discoveries → static; non-pure → dynamic or narrative (by category) |
| **Loop** | Prompt → interpret → create → render → output → extract → grow → repeat |
