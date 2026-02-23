# Workflow efficiency and registry completion

**Goal:** Improve the efficiency of every workflow so each registry moves toward **completion** — i.e. recording every possible combination of true primitive/origin values.

**Audience:** Operators and developers. Complements [WORKFLOWS_AND_REGISTRIES.md](WORKFLOWS_AND_REGISTRIES.md), [REGISTRY_REVIEW_AND_IMPROVEMENT_PLAN.md](REGISTRY_REVIEW_AND_IMPROVEMENT_PLAN.md), and [MISSION_AND_OPERATIONS.md](MISSION_AND_OPERATIONS.md).

---

## 1. What “registry complete” means per registry

| Registry | Primitives / origins | “Complete” = every combination of … |
|----------|----------------------|--------------------------------------|
| **Pure (static) — Color** | 16 color primitives; key = quantized RGB + opacity | Every **color key** (r,g,b at tolerance 25, opacity steps ~21). Space size: ~11³ × 21 ≈ **28k** cells. |
| **Pure (static) — Sound** | 4 primitives: silence, rumble, tone, hiss | Every **sound key** (amplitude/tone/timbre or strength bands) that can be produced; in practice, all four primitives represented in `depth_breakdown` across discoveries. |
| **Blended (dynamic)** | Gradient (4), camera (16), motion (4×4×…), sound (tempo×mood×presence), lighting, composition, etc. | Every **canonical value** per domain (e.g. each gradient_type, each camera_motion) seen at least once; novel **combinations** (e.g. gradient + camera) recorded as discoveries. |
| **Semantic (narrative)** | NARRATIVE_ORIGINS: genre, tone, style, tension_curve, settings, themes, scene_type | Every **origin value** in each aspect recorded at least once; optionally every **combination** (e.g. genre × mood × theme) for full cross-product coverage. |

So completion is **bounded and well-defined** for narrative (finite origin lists); **large but finite** for static color/sound and dynamic (quantized keys / canonical lists).

---

## 2. High-impact efficiency and completion enhancements

### 2.1 Coverage-aware prompt selection (exploration bias)

**Idea:** Use current registry state to bias **exploration** toward under-sampled primitives and combinations so each run is more likely to add **new** keys.

- **Implementation:**
  - Add **GET /api/registries/coverage** (or extend **GET /api/loop/progress**) to return, per registry (or per aspect), at least:
    - `static_colors_count`, `static_colors_estimated_cells` (e.g. 28k), `static_colors_coverage_pct`
    - `static_sound_count`, which primitives appear in discoveries (e.g. `has_tone`, `has_hiss`), `static_sound_coverage_pct`
    - Per-aspect narrative: e.g. `genre_count`, `genre_origin_size`, `genre_coverage_pct`; same for mood, themes, settings, etc.
    - Optional: list of **missing origin values** (e.g. narrative aspects where some origin values have count 0).
  - In **pick_prompt** / **generate_procedural_prompt** (and optionally **generate_interpretation_prompt**), accept an optional **coverage** or **gaps** payload:
    - Prefer **palette_hints** / **subjects** / **modifiers** that map to under-sampled narrative aspects (e.g. genre “thriller” if thriller has 0 or low count).
    - Prefer **mood/tempo/presence** combinations that are rare in learned_audio / static_sound.
  - In **automate_loop.py**, fetch coverage (or progress-with-coverage) when fetching knowledge; pass coverage into **pick_prompt** or the prompt generator so exploration is **gap-aware**.

**Effect:** Fewer “wasted” runs that only reinforce already-well-covered combos; faster filling of sparse narrative and dynamic aspects.

---

### 2.2 Discovery- and coverage-adjusted exploit ratio (extend existing)

**Current:** `_get_discovery_adjusted_exploit_ratio()` already lowers exploit when `discovery_rate_pct` is low or `repetition_score` is high.

- **Extension:** When **per-registry coverage** is available (e.g. from §2.1), optionally:
  - If **static_colors_coverage_pct** &lt; 5% (or 10%), cap exploit more aggressively (e.g. max 0.3) so more runs explore new colors.
  - If **narrative** has many aspects with coverage &lt; 50%, bias toward explore until those rise.
  - Keep overrides (e.g. Exploiter at 1.0) respected when operator explicitly sets them.

**Effect:** Automatically shifts the loop toward exploration when registries are far from complete.

---

### 2.3 Extraction efficiency (more novel keys per run)

**Current:** `grow_all_from_video(..., max_frames=None, sample_every=2)` reads every 2nd frame for the whole video. For 1–2 minute clips that’s already a lot of frames; for short loops (e.g. 5–10 s) we might get only a few frames.

- **Suggestions:**
  - **Configurable max_frames:** e.g. `config.learning.max_frames = 120` (or from API loop config) so very long videos don’t dominate; keep `sample_every=2` for cost/speed.
  - **Adaptive sample_every:** For short duration (e.g. &lt; 15 s), use `sample_every=1` to maximize static color/sound discovery per run; for long duration, keep or increase `sample_every` to cap CPU/decode time.
  - **Optional static-only pass:** When **LOOP_EXTRACTION_FOCUS=frame** and **static_focus=color**, consider a second pass with a **different** sample_every or time offset to hit different frames and increase color key diversity from the same file (trade-off: extra decode cost).

**Effect:** More distinct color/sound keys per run without necessarily longer videos; better use of each rendered clip.

---

### 2.4 Narrative: proactive targeting of missing origins

**Idea:** Narrative registry is **spec- and prompt-derived**; we can drive runs that **explicitly** request under-sampled genre/mood/theme/settings.

- **Implementation:**
  - From **GET /api/registries/coverage** (or narrative_entries counts), compute **missing or low-count** origin values per aspect (e.g. genre: thriller, tutorial; mood: energetic; themes: hope, loss).
  - Add a **targeted narrative prompt generator**: e.g. “Create a {genre} scene with {mood} mood and {theme}” using only missing/low-count values from NARRATIVE_ORIGINS.
  - In **pick_prompt**, with some probability (e.g. 15–25% when exploring), call this targeted generator instead of the general procedural one, so a fraction of runs are **dedicated** to filling narrative gaps.

**Effect:** Narrative registry moves toward “every origin value recorded” with fewer total runs.

---

### 2.5 Static sound: all four primitives (tone, hiss) represented

**Current:** Many static_sound discoveries map only to **rumble** and **silence**; **tone** and **hiss** are under-represented (see REGISTRY_REVIEW_AND_IMPROVEMENT_PLAN).

- **Implementation:**
  - In **procedural audio** (e.g. `_generate_procedural_audio` or equivalent), ensure **mid** (tone) and **high** (hiss) frequency components are sometimes present (e.g. by mood or random layer), so extraction can produce keys that map to tone/hiss in **depth_breakdown**.
  - In **derive_static_sound_from_spec**, when falling back to spec-derived sound, vary **tone/timbre** so that not every entry maps to the same band; optionally bias toward under-sampled primitives when coverage is known.

**Effect:** Static sound registry moves toward “all four primitives present in discoveries,” which is a necessary condition for considering it complete.

---

### 2.6 Parallel workers (Explorer + Exploiter)

**Current:** Single loop process; workflow type (explorer / exploiter / main) and exploit_ratio control explore vs exploit.

- **Suggestion:** Run **two** workers (or two services) in parallel:
  - **Explorer:** `LOOP_EXPLOIT_RATIO_OVERRIDE=0` (or exploit_ratio=0), focus on discovery and coverage.
  - **Exploiter:** `LOOP_EXPLOIT_RATIO_OVERRIDE=1` (or high exploit), focus on quality and reinforcing good prompts.
  - Both call the same API (jobs, upload, learning, discoveries); both contribute to the same registries. Explorer fills gaps; Exploiter improves precision and stability.

**Effect:** Completion (coverage) and quality (precision) improve in parallel without slowing either.

---

### 2.7 Optional “color sweep” or targeted static runs

**Idea:** Static color has ~28k cells; random prompts may cluster in certain RGB regions. To speed completion:

- **Option A — Batch sweep (offline):** A separate script or job type that, instead of interpreting a natural-language prompt, **iterates** over a grid of (r,g,b) or palette seeds and renders minimal clips (e.g. solid color or simple gradient), then runs static extraction and growth. Run periodically (e.g. nightly) to fill many cells without going through the full prompt → interpret → create pipeline.
- **Option B — Palette bias from coverage:** If coverage API exposes which **RGB bands** (e.g. low R, high B) are sparse, **generate_procedural_prompt** or **builder** could prefer palette_hints that tend to produce those bands (e.g. “cool blue tones,” “deep red”) when coverage for that band is low.

**Effect:** Faster progress toward “every color key recorded” for pure static.

---

### 2.8 Single source of truth for “complete” definition

- **Recommendation:** In **config** or **docs**, define explicitly:
  - **Static color:** e.g. “All keys in the set `{ (r,g,b)_o : r,g,b ∈ {0,25,…,250,255}, o ∈ opacity_steps }` have at least one discovery.”
  - **Static sound:** “All four primitives (silence, rumble, tone, hiss) appear in at least one discovery’s depth_breakdown.”
  - **Narrative:** “Every value in NARRATIVE_ORIGINS for genre, mood, themes, settings, style, scene_type, plots has count ≥ 1.”
  - **Dynamic:** “Every canonical value in gradient_type, camera_motion, and sound (tempo/mood/presence) has at least one discovery; optional: target combinations across domains.”
- Expose these as **targets** in the same place as coverage (e.g. **GET /api/registries/coverage** or **GET /api/loop/progress**) so the UI and the loop can show “X% toward static color complete” and adjust behavior.

**Effect:** Clear definition of “done” and measurable progress.

---

## 3. Implementation status

Implemented:

- **§2.8** — `src/knowledge/completion_targets.py` defines targets; `config/default.yaml` documents learning.max_frames and sample_every; **GET /api/registries/coverage** returns counts and coverage_pct.
- **§2.1** — **GET /api/registries/coverage** with static_colors, static_sound, narrative per-aspect (count, entry_keys, coverage_pct); **automate_loop** fetches coverage and passes to pick_prompt; **generate_procedural_prompt** accepts `coverage` and biases lighting when static color coverage &lt; 25%.
- **§2.2** — **\_get_discovery_adjusted_exploit_ratio** accepts `coverage`; caps exploit when static_colors_coverage_pct &lt; 10 or narrative_min_coverage_pct &lt; 50.
- **§2.4** — **generate_targeted_narrative_prompt(coverage, avoid)** in prompt_gen; **pick_prompt** uses it with probability 0.20 when exploring.
- **§2.5** — **\_generate_procedural_audio** adds mid (330 Hz) and high (1200 Hz) layers by mood/random; **derive_static_sound_from_spec** varies tone/timbre (mid, high) so keys and depth_breakdown can map to tone/hiss.
- **§2.3** — **config.learning.max_frames** (default 120) and **sample_every** (default 2); **automate_loop** uses adaptive sample_every=1 when duration &lt; 15 s.
- **§2.6** — Note in **config/workflows.yaml** for running Explorer + Exploiter in parallel.
- **§2.7** — **Palette bias**: when coverage is passed and static_colors_coverage_pct &lt; 25, **generate_procedural_prompt** biases toward lighting modifiers (bias_lighting) to widen color discovery.

---

## 4. Metrics to track

- **Per registry:** `*_count`, `*_estimated_cells` (where applicable), `*_coverage_pct`, and for narrative **per-aspect** coverage.
- **Loop:** Keep existing `precision_pct`, `discovery_rate_pct`, `repetition_score`; add optional `static_color_coverage_pct`, `narrative_min_aspect_coverage_pct`, etc.
- **Efficiency:** Novel discoveries per run (e.g. per job_id), novel per minute of video processed; can be derived from learning_runs and discovery POSTs if job_id is stored.

These enhancements keep the current workflows and mission intact while making each run more likely to advance registry completion and making completion measurable and actionable.
