# Precision & accuracy: FAQ and design decisions

This document answers common questions about how the registries work, what each field means, and how we improve precision and accuracy. It complements [REGISTRY_EXPORT_SCHEMA.md](../json%20registry%20exports/REGISTRY_EXPORT_SCHEMA.md) and [WORKFLOWS_AND_REGISTRIES.md](WORKFLOWS_AND_REGISTRIES.md).

---

## Pure (Static) Registry

### Pure — Sound primitives (origin noises)

**Q: There are only 4 listed (silence, rumble, tone, hiss) and none have been “recorded” in a produced video.**

- The **4 primitives** are the **origin set**: they define the vocabulary for depth. They are **seeded** in the static registry (locally and, when seeding is run, in D1) so the mesh can reference them.
- “Recorded in a produced video” means: a **discovery** (a per-frame sound that maps to one or more of these primitives in `depth_breakdown`) was **extracted from a video** and stored. Until per-frame audio extraction runs on real video, most static_sound entries come from **spec-derived** sound (what we intended for the clip) or from the **sound-only loop** (procedural audio → extract → grow). So the primitives themselves may not appear as rows with “source = video” until extraction actually produces keys that resolve to them. We **seed** the 4 primitives in the DB so they appear as “present” in the registry; discoveries from video or procedural audio then reference them in `depth_breakdown`.

### Pure — Colors (per-frame discoveries): duplicate names

- **Names are unique per key** in the API/export: when the same name would apply to different keys, we disambiguate as **"Name (r,g,b)"** so each row has a distinct label. So “Cyan” can appear as “Cyan (100,125,175)” and “Cyan (75,125,200)” for different keys.

### Depth % vs “Depth (primaries + theme/opacity)” — one concept

- There is **one** depth concept: **how much this discovery is composed of primitives (and, for static color, theme/opacity)**.
  - **Depth vs primitives (breakdown)**: The object that lists each **primary** (e.g. black, white, gray, teal) with a **percentage** (0–100). That is the “depth”: the mixture of origin primitives that best explains this discovery. For static color we also split out **theme_breakdown** (e.g. ocean, night) and **opacity_pct** when present, so “Depth vs primitives” shows only the 16 color primitives; theme and opacity are shown separately when available.
  - **Depth %**: A **single number** summarizing that breakdown (e.g. 100 when we have a full primitive breakdown, or the dominant component). So “Depth %” is not a second kind of depth — it is a **summary** of the same “depth vs primitives” idea (e.g. “how much of this value is explained by primitives” or “max contribution”).
- In the UI we use one column **“Depth vs primitives”** for the breakdown and, where useful, **“Depth %”** as that summary. Both refer to the same notion: consistency of the discovered value with respect to primary (and, when applicable, theme/opacity) contributions.

### Pure — Sound (per-frame discoveries)

**Q: What origin/primitive sounds are used here?**

- The **same 4 primitives**: silence, rumble, tone, hiss. Each discovery has a **depth_breakdown** (often as `origin_noises`) giving the weight of each primitive. So every per-frame sound discovery is expressed as a blend of these four.

**Q: Why do some names still have a `sound_` prefix?**

- Those names were generated when a **domain prefix** was applied (e.g. to avoid collisions). We **normalize for display**: in the API response and export we strip the `sound_` prefix so the UI shows a clean name (e.g. “emlyn” instead of “sound_emlyn”). Stored names in the DB can keep the prefix for uniqueness; display is normalized.

**Q: What is “Strength %” measuring?**

- **Strength %** is the **amplitude/weight of the sound in that instant** (0–100%): how loud or present that sound is in the frame/sample. It is stored as `strength_pct` (or derived from amplitude/weight). So it answers “how strong is this sound at this moment?” and is separate from **depth** (which answers “which primitives make up this sound?”).

---

## Blended (Dynamic) Registry

### Gradient / Camera / Motion canonical and discoveries

- **Canonical** lists are the full origin sets: gradient_type (vertical, horizontal, radial, angled), camera_motion (all 16 from origins), motion (static, slow, medium, fast, steady, pulsing, wave, random). The API merges **learned_gradient** and **learned_camera** (and learned_motion) with **learned_blends** so per-window discoveries appear. If only one or a few discoveries appear, it is because extraction has produced few distinct gradient/camera keys so far (e.g. many windows yield “static” or the same type). The loop and extraction are designed to keep adding new keys as more videos are processed.

### Blended — Colors (learned): why here and not Pure (Static)?

- **learned_colors** = **whole-video** dominant color (one representative color per video). They have **depth vs primitives** like static colors but are **aggregates over time**, not per-frame.
- **static_colors** = **per-frame** discoveries (each frame can add a new color key). So both “stem from primitives with depth”; the difference is **granularity**: per-frame (Pure) vs per-video (Blended). Learned colors stay in Blended because they are a **time-aggregated** product of the pipeline; static colors remain the place for per-frame, “pure” color discovery.

### Blends (other)

- **“Blends (other)”** is intended as a **fallback** when a value does not fit a single category. In practice, **learned_blends** stores one row per domain per video (color, motion, lighting, composition, graphics, temporal, technical, full_blend, narrative, etc.). So the API **splits** these: gradient/camera/audio go to their sections; **color, motion, lighting, composition, graphics, temporal, technical** are merged into their respective Blended sections where we already have learned_* tables; **only** entries whose domain is `full_blend` or has no dedicated section appear under “Blends (other)”. That keeps “other” as a true fallback and reduces the number of rows there.

---

## Semantic (Narrative) Registry

### Entry key vs Value

- **entry_key**: The canonical identifier used in code and DB (e.g. `"cinematic"`, `"uplifting"`). Often normalized (lowercase, no spaces).
- **value**: The same or a display form of that identifier. In most rows **entry_key** and **value** are the same; **value** can sometimes be longer or human-formatted. So there is a single logical value; “value” is what we show, “entry_key” is what we index.

### Why do some values have much higher count than others?

- Count = how many times that value was **recorded** (e.g. from spec + prompt in that run). So high count = that genre/mood/theme/setting was chosen or inferred often (e.g. “default”, “neutral”, “cinematic”). Lower counts are from less frequent prompts or from **targeted narrative** runs that explicitly fill missing origins.

### Primitives and discoveries

- We use **NARRATIVE_ORIGINS** (genre, tone, style, tension_curve, settings, themes, scene_type). The loop **targets missing origins** (targeted narrative prompt) so that over time every primitive value gets at least one recording. Coverage metrics and the targeted narrative generator are there to avoid leaving out known primitive values.

---

## Interpretation (Linguistics)

### How is “Instruction summary” created?

- The **Instruction summary** column is built in the UI from the **instruction** object: it lists up to 6 keys (e.g. palette, motion, gradient, camera, mood, audio_tempo) plus any other top-level keys. So it is a short, readable summary of **what the interpreter wrote into the instruction** for that prompt (palette, motion type, gradient, camera, mood, tempo, etc.). It does not dictate what is stored; it only **summarizes** the stored instruction.

### How does interpretation discover and grow?

- **Interpretation** stores every resolved prompt → instruction. **Linguistic registry** stores span → canonical (e.g. “promo” → “ad”) so we normalize synonyms and slang. So “preparing for everything” means: (1) **at current state** we resolve prompts using existing keywords and linguistic mappings; (2) **every loop** we add new interpretations and, when we extract linguistic mappings, new span→canonical entries; (3) the **pool** of interpretation_prompts and by_keyword grows so creation and exploration use more varied, real prompts. So we prepare as well as we can with the current registry and **learn from every loop** by encountering new prompts and new meanings.

---

## Overall

### One depth concept

- **Depth** = how much a discovery is composed of **origin primitives** (and, where applicable, theme/opacity). **Depth %** is a single-number summary of that (e.g. 100 when we have a full breakdown). The breakdown (“Depths towards primitives”) is the full picture; Depth % is not a second, different depth.

### Unique names across registries

- Within **color** lists we disambiguate (e.g. “Cyan (100,125,175)”). Across registries, the same word (e.g. “Slate”) can appear in Pure static and in Blended dynamic for different keys; we can **scope by registry** in the UI (e.g. “Static: Slate” vs “Dynamic: Slate”) or ensure display names are unique in export by appending key or registry when the same name appears elsewhere. So names are unique per key within a table; across registries we rely on context (section) or add a scope prefix where needed.

### Similar patterns and progress

- Every workflow is designed to **extract** (per-frame and per-window), **record** with semantic names, and **grow** the registries. The next loop uses a **pool** that includes both origin/primitive and newly discovered values; **pick_prompt** and **build_spec** use underused/recent bias and coverage so selection is **randomized** across that pool (not only primitives). If progress feels slow, check: (1) **extraction** is running (no early exit, correct sample_every/max_frames); (2) **discoveries** are POSTed (learning_runs and discovery_runs); (3) **exploit ratio** is not too high (coverage-based caps push toward explore); (4) **targeted narrative** and **lighting bias** are active so we fill gaps. All workflows should be extracting, recording, naming, and growing each loop; the doc and code assume a single pipeline that does all of that.

### Extraction and growth (audit)

- **Order in the loop:** (1) `extract_from_video(path)` → analysis dict; (2) `grow_all_from_video(...)` → per-frame static + per-window dynamic + novel_for_sync; (3) `post_static_discoveries` / `post_dynamic_discoveries` / `post_narrative_discoveries` (gated by extraction_focus); (4) `grow_and_sync_to_api(analysis_dict, spec=spec, ...)` for whole-video aggregates; (5) `post_discoveries(api_base, {"job_id": job_id})` so the run is counted in discovery_runs; (6) `POST /api/learning` with job_id. No step should be skipped when api_base is set.
- **Creation pool:** `get_knowledge_for_creation` returns `origin_gradient`, `origin_camera`, `origin_motion` and `learned_gradient`, `learned_camera`, etc. `build_spec_from_instruction` uses `_pool_from_knowledge`, which **merges origin + learned** (deduped) so the pool is always origin primitives plus discovered values. `secure_choice(pool)` or `weighted_choice_favor_underused` then picks from that merged pool, so no canonical value is left out and selection is randomized across primitives and discoveries.
