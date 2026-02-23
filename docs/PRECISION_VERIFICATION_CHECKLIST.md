# Precision verification checklist

Use this checklist to verify that workflows and registries align with the **refined mission** (100% precision, comprehensive data acquisition, robust prompt interpretation). See **REGISTRY_REVIEW_AND_IMPROVEMENT_PLAN.md** (refined mission section) and **MISSION_AND_OPERATIONS.md**.

---

## 1. Workflow enforcement (LOOP_EXTRACTION_FOCUS)

**Goal:** Frame workers post only static; window worker posts only dynamic/narrative. No unintended `Growth [all]` when the variable is set.

| Check | How |
|-------|-----|
| **Env set correctly** | On Railway (or your host): Explorer and Exploiter have `LOOP_EXTRACTION_FOCUS=frame`; Balanced has `LOOP_EXTRACTION_FOCUS=window`. Exact name is **LOOP_EXTRACTION_FOCUS** (not LCXP). Copy from **RAILWAY_CONFIG.md**. |
| **Logs: frame workers** | In Explorer/Exploiter logs you should see **`Growth [frame]`** (and static counts). You should **not** see `Growth [all]` on those services if the variable is set. |
| **Logs: window worker** | In Balanced logs you should see **`Growth [window]`** (and dynamic/narrative counts). You should **not** see `Growth [all]` on that service if the variable is set. |
| **First-run reminder** | If the variable is **unset**, the first run of automate_loop logs: *"LOOP_EXTRACTION_FOCUS is unset → Growth [all]. For split workers set ..."*. Use that to catch misconfiguration. |

**If you see `Growth [all]` on a worker that should be frame or window:** Confirm the env var is set in that service’s environment (e.g. Railway env vars) and redeploy.

---

## 2. Data loss (missing learning / missing discovery)

**Goal:** Every successful run is recorded (learning + discovery run). Minimize persistent missing learning/discovery.

| Check | How |
|-------|-----|
| **Logs on failure** | On POST failure you should see **`Missing learning (job_id=...)`** or **`Missing discovery (job_id=...)`** with status/exception. Use job_id in your diagnostics (e.g. Worker “last N jobs” or DB) to trace which run failed. |
| **Retries** | Learning POST uses **5 retries** with 2s backoff (automate_loop.py). Discovery POSTs use api_request_with_retry (3 retries by default). Transient 5xx/429/connection errors are retried. |
| **Discovery run recorded** | After growth/sync (success or fail), the loop always calls `post_discoveries(api_base, {"job_id": job_id})` so the API can insert a discovery_runs row for that job. |
| **Persistent issues** | If missing learning/discovery remains high: (1) Check API availability and rate limits (e.g. KV 1 write/sec). (2) Inspect API response status and body for the failing job_id. (3) Consider optional backfill: POST /api/learning for completed jobs that have no learning_runs row. |

---

## 3. Backfill semantic consistency

**Goal:** When gibberish names are replaced with semantic names, the new name is propagated everywhere that referenced the old name.

| Check | How |
|-------|-----|
| **Cascade coverage** | Backfill (POST /api/registries/backfill-names) triggers **cascadeNameUpdate**: learning_runs.prompt, interpretations.prompt + instruction_json, jobs.prompt, learned_blends (source_prompt, **inputs_json**, **output_json**, **primitive_depths_json**), and all sources_json columns for static_colors, static_sound, learned_*, narrative_entries. See cloudflare/src/index.ts. |
| **Running backfill** | `python scripts/backfill_registry_names.py --api-base https://motion.productions` (optionally `--table learned_blends` or `--dry-run`). |

---

## 4. Sparse categories (registry density)

**Goal:** No category in Pure, Blended, or Semantic stays consistently empty or stagnant. Adjust creation or extraction for sparse areas.

| Check | How |
|-------|-----|
| **Review exports** | Periodically open exported registry JSON (e.g. `json registry exports/motion-registries-YYYY-MM-DD.json`) and scan **Pure**, **Blended**, and **Semantic** sections for categories with very few entries or no growth over time. |
| **Examples** | Gradient, camera, or narrative categories were noted as sparse in earlier exports. If still sparse: (1) Confirm window worker is running and posting (Growth [window]). (2) Confirm creation uses learned_gradient / learned_camera and that grow_and_sync_to_api runs for window. (3) Check that registries API merges learned_gradient / learned_camera into the export if your UI reads from that. |
| **Sound** | Pure sound (static_sound) grows from frame workers and from **sound_loop.py**. If static_sound is sparse, ensure sound_loop is deployed and that frame workers have static_focus including sound. |

---

## 5. Sound discovery workflow

**Goal:** sound_loop.py is deployed and its discoveries are used in creation.

| Check | How |
|-------|-----|
| **Deployment** | Sound-only worker runs `python scripts/sound_loop.py` with API_BASE set (e.g. config/workflows.yaml → sound). |
| **Integration** | GET /api/knowledge/for-creation returns **static_sound**. Builder uses it for pure_sounds (3–5 per run), audio mood/tone refinement, and (when spec.pure_sounds is set) mixed procedural audio. No code change needed if for-creation and builder are current. |

---

## 6. Interpretation & linguistic

**Goal:** Every prompt used in the loop is recorded so we can reference it later; interpret workflow can interpret all sorts of prompts; new/different/authentic prompts are generated to test interpretation.

| Check | How |
|-------|-----|
| **Recording in Railway** | After each run the loop prints **`[interpretation] posting...`** then **`[interpretation] recorded`** (or **`[interpretation] failed ...`**). If you never see these, the deployed code may be old or the process may not be the main video loop. Interpretation is posted **immediately** after interpret_user_prompt (before spec build) so it is not skipped by later errors. |
| **Interpret worker logs** | In interpret_loop.py you should see **`[cycle] interpreted`**, **`[cycle] backfill`**, **`[cycle] generated`**, **`[cycle] linguistic growth`**. If absent, check queue, API, and --no-backfill / --no-generate flags. |
| **Prompt quality** | Procedural prompts use slot pools and _expand_from_knowledge. Nonsensical prompts are filtered. Run backfill_registry_names so cascaded prompts stay semantic. |

---

## 6b. Algorithm precision (checks that workflows produce accurate results)

**Goal:** Algorithms and functions have precision so workflows produce accurate results; we have checks to confirm everything is working as expected.

| Check | How |
|-------|-----|
| **Depth %** | For every discovered value, depth % = how much each origin/primitive makes up that value. Weights in depth_breakdown should sum to 1 (or 100 when stored as percentages). Color: compute_color_depth returns two primitives with weights summing to 1. Sound: compute_sound_depth returns origin_noises summing to 1. |
| **Keys** | Static color key: rgb_opacity (e.g. 100,125,150_1.0). Static sound key: amplitude_tone_timbre (e.g. 0.06_low_low). Validation in tests or a small script can assert key format and depth sums. |
| **Interpretation schema** | interpret_user_prompt returns an instruction with required fields (palette_hints, motion_hints, etc.). Parser and schema tests ensure prompts map to valid specs. |
| **Registry growth** | Exports and loop_progress show discovery_rate and precision_pct. Use them as ongoing checks that learning and discovery POSTs are succeeding. |

---

## 7. Creation: pure-per-frame and data-driven

**Goal:** Pure-per-frame uses per-pixel pure colors from the pool; every creation decision is driven by registry/origin data; no hardcoded defaults; underused/recent bias in use.

| Check | How |
|-------|-----|
| **Code** | builder.py builds pure_colors from origin + static_colors + learned_colors; creation_mode = "pure_per_frame" when pool non-empty. renderer.py _render_pure_per_frame() assigns a color per pixel from that pool. See MISSION_AND_OPERATIONS.md §2.4. |
| **Parameterization** | Palette: 2–3 hints when default, with underused bias. Motion, gradient, camera: from _pool_from_knowledge (learned_* + origin_*). Audio: 35% weighted_choice_favor_recent(learned_audio), else most_common; static_sound for mood/tone with underused bias. |
| **Tests** | Run `python -m pytest tests/ -v` or `python -m unittest discover -s tests -p "test_*.py" -v` to confirm _build_pure_color_pool and growth_metrics behave as expected. |

---

## 8. Code quality and deployment

| Check | How |
|-------|-----|
| **Tests** | `python -m pytest tests/ -v` (or unittest discover). Add tests for new registry-affecting functions when feasible. |
| **Recursion** | No recursion in src/ (audit confirmed). If you add recursive logic, use limits or iterative form to avoid RecursionError. |
| **Commit and deploy** | After code/config changes, commit and push; redeploy services (e.g. Railway) so new logic and env vars are active. |
| **Standards** | Registry-affecting behaviour should align with **REGISTRY_FOUNDATION.md** and **LOOP STANDARDS** (INTENDED_LOOP.md, WORKFLOWS_AND_REGISTRIES.md). |

---

**Summary:** Use **Growth [frame]** / **Growth [window]** and **Missing learning (job_id=...)** / **Missing discovery (job_id=...)** as primary log indicators. Keep **LOOP_EXTRACTION_FOCUS** set per service. Review registry exports for sparse categories and backfill names when needed. This checklist supports the refined mission of 100% precision and comprehensive data acquisition for a robust prompt interpretation system.

---

## FAQ: Precision & accuracy (design decisions)

This section answers common questions about how the registries work and how we improve precision and accuracy. It complements [REGISTRY_EXPORT_SCHEMA.md](../json%20registry%20exports/REGISTRY_EXPORT_SCHEMA.md) and [WORKFLOWS_AND_REGISTRIES.md](WORKFLOWS_AND_REGISTRIES.md).

### Pure (Static) Registry

**Q: There are only 4 sound primitives (silence, rumble, tone, hiss) and none have been "recorded" in a produced video.**

- The **4 primitives** are the **origin set**; they are **seeded** so the mesh can reference them. Until per-frame audio extraction runs on real video, most static_sound entries come from **spec-derived** sound or from the **sound-only loop**. Discoveries from video or procedural audio reference them in `depth_breakdown`.

**Pure — Colors: duplicate names** — Names are unique per key; when the same name would apply to different keys we disambiguate as **"Name (r,g,b)"**.

**Depth % vs "Depth (primaries + theme/opacity)"** — There is **one** depth concept: how much this discovery is composed of primitives (and, for static color, theme/opacity). **Depth vs primitives (breakdown)** = the full mixture; **Depth %** = a single-number summary. Both refer to the same notion.

**Pure — Sound: What origin/primitive sounds are used?** — The same 4 primitives; each discovery has `depth_breakdown` (origin_noises) giving the weight of each. **sound_ prefix** — We normalize for display (strip prefix in API/export). **Strength %** — Amplitude/weight of the sound in that instant (0–100%); separate from depth.

### Blended (Dynamic) Registry

**Gradient / Camera / Motion** — Canonical lists are the full origin sets. The API merges learned_gradient, learned_camera, learned_motion with learned_blends so per-window discoveries appear.

**Learned colors here vs Pure (Static)?** — learned_colors = whole-video dominant color (aggregates over time). static_colors = per-frame discoveries. Difference is granularity: per-frame (Pure) vs per-video (Blended).

**Blends (other)** — Fallback when a value does not fit a single category; API splits by domain so only full_blend or no-dedicated-section appear under "Blends (other)".

### Semantic (Narrative) Registry

**entry_key vs value** — entry_key = canonical identifier (code/DB); value = display form. **High counts** — Count = how many times that value was recorded; high count = chosen/inferred often. **Primitives and discoveries** — NARRATIVE_ORIGINS; loop targets missing origins via targeted narrative prompt.

### Interpretation (Linguistics)

**Instruction summary** — Built in the UI from the instruction object (up to 6 keys). **How interpretation grows** — Interpretation stores every resolved prompt→instruction; linguistic registry stores span→canonical; every loop adds new interpretations and span→canonical entries.

### Overall

**One depth concept** — Depth = composition of origin primitives (and theme/opacity where applicable); Depth % is a summary. **Unique names** — Unique per key within a table; across registries use context or scope prefix. **Extraction and growth order** — (1) extract_from_video (2) grow_all_from_video (3) post_*_discoveries (4) grow_and_sync_to_api (5) post_discoveries with job_id (6) POST /api/learning. Creation pool = get_knowledge_for_creation → _pool_from_knowledge merges origin + learned.
