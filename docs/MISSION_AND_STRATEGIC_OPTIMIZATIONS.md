# Refined Mission & Strategic Optimizations

**Purpose:** Align the `motion.productions` project with a clear mission and five optimization areas to achieve comprehensive data acquisition and a robust prompt interpretation system.

---

## Refined Mission Statement

- **Core objective:** Achieve **100% precision** in all workflow algorithms and functions so that results across the platform are **100% accurate**.
- **Data acquisition:** Systematically acquire and record **every possible combination** of origin/primitive values across all video-related aspects (sound, color, motion, theme, plot, etc.). Each discovered value receives an **authentic, semantically meaningful name** in its registry.
- **Ultimate goal:** Build a **complete, granular dataset** across the Pure (Static), Blended (Dynamic), Semantic (Narrative), and Interpretation registries. This dataset is the foundation for a **fully capable prompt interpretator** that understands user prompts (including slang and multi-sense words) and generates corresponding videos with high accuracy.

---

## 1. Registry Completeness & Precision (Data Acquisition Foundation)

**Goal:** Complete, accurate, and semantically consistent data across all registries.

| Action | How |
|--------|-----|
| **Monitor extraction focus** | Use **`LOOP_EXTRACTION_FOCUS`** (not `LCXP_EXTRACTION_FOCUS`) on each worker. See **RAILWAY_CONFIG.md** §8 and **REGISTRY_REVIEW_AND_IMPROVEMENT_PLAN.md**. |
| **Verify logs** | Explorer/Exploiter (frame): expect `Growth [frame]`. Balanced (window): expect `Growth [window]`. Wrong or unset env → `Growth [all]`. |
| **Eliminate missing learning/discovery** | Investigate every `Missing discovery (job_id=...)` and `Missing learning (job_id=...)` in logs; fix POST/sync so successful runs always contribute. |
| **Backfill propagation** | Backfill scripts replace gibberish names with semantic ones; **cascade** must propagate new names to prompts (learning_runs, interpretations, jobs), **sources_json**, and **blend JSON** (learned_blends inputs_json, output_json, primitive_depths_json) so no reference to the old name remains. |

---

## 2. Dedicated Sound Discovery Workflow (Critical Data Gap)

**Goal:** Comprehensive, precise discovery of pure and composite sound elements.

| Action | How |
|--------|-----|
| **Deploy sound-only workflow** | Finalize and run **`sound_loop.py`** as a dedicated process: generate procedural audio meshes, extract **pure sound** values (including combinations from multiple noises in a single frame), record into the Pure (Static) sound registry **without** rendering full video. |
| **Integrate into creation** | Ensure discovered pure sounds are used in the **creation phase** of other workflows (especially frame-focused ones) so novel visual–audio combinations are explored. (Already wired: for-creation returns static_sound; builder samples pure_sounds and mixes them in audio.) |

---

## 3. Interpretation & Linguistic Precision (Prompt Interpretator Foundation)

**Goal:** Robust linguistic registry and prompt generator for an accurate interpretator.

| Action | How |
|--------|-----|
| **Monitor Interpret worker** | Check logs for `[cycle] interpreted`, `[cycle] backfill`, `[cycle] generated`, and `[cycle] linguistic growth` so the interpretation loop and linguistic growth run continuously. |
| **Refine procedural prompt generator** | Use the **growing linguistic registry** and **semantic information** (learned colors, motion, static_sound, learned_audio, interpretation_prompts) so generated prompts are **meaningful and diverse**, not nonsensical. Filter by `is_semantic_name`; expand slot pools and modifiers from registry. |

---

## 4. Creation-Phase Behavior (Maximize Exploration)

**Goal:** Maximize exploration of novel combinations during video creation.

| Action | How |
|--------|-----|
| **Audit pure-per-frame mode** | Confirm it produces **diverse, unpredictable** outputs (multiple colors, motion, sounds), not generic 1-color/1-motion/1-sound patterns. |
| **Parameterize every decision** | Every creation choice (color, motion, sound, gradient, camera) must be **driven by data** from all available origin/primitive sets and registry values. **Remove** remaining hardcoded defaults or static-only pools. |
| **Wider selection & bias** | Use **wider selection pools** (e.g. 2–3 learned colors for palette hints when applicable). **Bias** toward underused (lower count) and recently discovered (created_at) values. **Aggressively randomize** DEFAULT gradient, motion, camera when no user hint. |

---

## 5. Registry Density Monitoring (Comprehensive Coverage)

**Goal:** All video aspects contribute to learned combinations.

| Action | How |
|--------|-----|
| **Review exported registry JSON** | Regularly inspect exports (e.g. `motion-registries-YYYY-MM-DD.json`) for categories that stay **sparse** or **stagnant** (e.g. gradient, camera, narrative). |
| **Investigate sparse categories** | For each sparse category, check extraction logic and creation-phase integration; apply **targeted changes** to stimulate growth. |

---

## Reference

- **Living plan:** **REGISTRY_REVIEW_AND_IMPROVEMENT_PLAN.md** — refined mission, five key areas, and implementation status; update with findings and next steps.
- **Verification:** **PRECISION_VERIFICATION_CHECKLIST.md** — operator checklist for workflow enforcement, data loss, backfill, sparse categories, sound, interpretation, creation, and code quality.
- **Codebase audit:** **CODEBASE_AUDIT_MISSION_ALIGNMENT.md** — full audit of workflows, creation, sound, interpretation, and code quality with findings and checklist.
- **Env variable:** **`LOOP_EXTRACTION_FOCUS`** — see RAILWAY_CONFIG.md §8.1 (use this exact name; not `LCXP_EXTRACTION_FOCUS`).
- **Logging:** Use `Growth [frame]`, `Growth [window]`, `Missing learning (job_id=...)`, and `Missing discovery (job_id=...)` as primary indicators. Commit and redeploy after changes.
- **Backfill:** `scripts/backfill_registry_names.py`; API `POST /api/registries/backfill-names`; cascade updates prompts and blend-related JSON.
- **Sound workflow:** `scripts/sound_loop.py`; config `workflows.yaml` (sound workflow).
- **Creation parameterization & bias:** `src/creation/builder.py`; `src/random_utils.py` (weighted_choice_favor_underused / weighted_choice_favor_recent).
- **Prompt gen:** `src/automation/prompt_gen.py` (`_build_slot_pools`, `_expand_from_knowledge`).
