# Registry and workflow improvements

**Consolidated from:** REGISTRY_REVIEW_AND_IMPROVEMENT_PLAN, WORKFLOW_EFFICIENCY_AND_REGISTRY_COMPLETION, WORKFLOW_IMPROVEMENT_PLAN_FROM_REPORTS, MANUS_AI_ENHANCEMENT_REPORT_REVIEW.

**References:** [WORKFLOWS_AND_REGISTRIES.md](WORKFLOWS_AND_REGISTRIES.md), [MISSION_AND_OPERATIONS.md](MISSION_AND_OPERATIONS.md), [RAILWAY_CONFIG.md](RAILWAY_CONFIG.md).

---

# Part I — Registry review and improvement plan

## Refined mission: 100% precision

1. **Comprehensive data acquisition:** Record every possible combination of origin/primitive values; each discovery gets an **authentic, semantically meaningful name**.
2. **Robust prompt interpretation:** Build a complete knowledge base across Pure, Blended, Semantic, and Interpretation registries.

**Five key areas:** Registry completeness (LOOP_EXTRACTION_FOCUS, backfill); Creation phase (pure-per-frame, data-driven); Sound discovery (sound_loop); Interpretation & linguistic; Code quality (tests, REGISTRY_FOUNDATION alignment).

**Configuration:** Use **`LOOP_EXTRACTION_FOCUS`** (not `LCXP_EXTRACTION_FOCUS`): `frame` for Explorer/Exploiter, `window` for Balanced. See RAILWAY_CONFIG.md. Logging: `Growth [frame]`, `Growth [window]`, `Missing learning (job_id=...)`, `Missing discovery (job_id=...)`.

## Export review: sparse categories

- **Pure sound:** Sparse until per-frame/per-segment audio decoding; spec-derived fallback used when decoded audio empty.
- **Blended gradient/camera/sound:** Worker now merges learned_gradient, learned_camera, learned_audio_semantic; per-window discoveries appear in export.
- **Depth for learned colors:** Single "depth vs pure static" with 16-primitive breakdown; stored in learned_colors.

## Prioritized plan (100% precision)

**P1 — Critical:** Depth for learned colors (done); merge gradient/camera/sound in registries API (done); ensure job_id on every learning/discovery path.

**P2 — High:** Narrative = intended (spec+prompt), not observed; interpretation + linguistic workflow; UI single depth concept.

**P3 — Medium:** Pure static sound extraction from MP4; dynamic audio_semantic in registries.

**P4 — Ongoing:** Algorithms audit; longer videos / multi-segment.

## Implementation status (registry & creation)

- LOOP_EXTRACTION_FOCUS (frame/window) in automate_loop and growth_per_instance.
- GET /api/knowledge/for-creation returns static_sound; builder uses it.
- backfill_registry_names.py; POST /api/registries/backfill-names with cascade.
- pure-per-frame creation mode in builder and renderer.
- Missing learning/discovery logs include job_id.

---

# Part II — Workflow efficiency and registry completion

## What “registry complete” means

| Registry | Complete = |
|----------|------------|
| Pure — Color | Every color key (r,g,b + opacity) ≈ 28k cells |
| Pure — Sound | All four primitives in depth_breakdown |
| Blended | Every canonical value per domain; novel combos recorded |
| Semantic | Every NARRATIVE_ORIGINS value recorded |

## High-impact enhancements

- **§2.1 Coverage-aware prompt selection:** GET /api/registries/coverage; pass coverage into pick_prompt; bias toward under-sampled aspects. **Implemented.**
- **§2.2 Discovery-adjusted exploit ratio:** Cap exploit when static_colors_coverage_pct < 10 or narrative_min_coverage_pct < 50. **Implemented.**
- **§2.3 Extraction efficiency:** max_frames, sample_every configurable; adaptive sample_every for short videos. **Implemented.**
- **§2.4 Targeted narrative prompts:** generate_targeted_narrative_prompt when exploring. **Implemented.**
- **§2.5 Static sound (tone/hiss):** Procedural audio adds mid/high layers; derive_static_sound_from_spec varies tone. **Implemented.**
- **§2.6 Parallel workers:** Explorer + Exploiter in config/workflows.yaml.
- **§2.7 Color sweep:** scripts/color_sweep.py for batch RGB grid.
- **§2.8 Completion targets:** completion_targets.py; coverage_snapshot in GET /api/registries/coverage.

---

# Part III — Workflow improvement plan (from reports)

## Report findings

**Working:** Blended registry growth (lighting, composition, graphics); pure static color depth; schema v2; core loop.

**Critical issues:** Numeric-suffix names (backfill_registry_names.py); missing depth_breakdown for motion/lighting/etc.; pure sound key leakage (primitive tones only); runs_with_learning gap; semantic stagnation; linguistic gaps; color bias.

## Prioritized action plan

**P0:** (1) Run backfill_registry_names.py; (2) Add depth_breakdown to per-window dynamic; (3) Enforce primitive-only tones in static sound.

**P1:** (4) Seed linguistic domains; (5) Tone/style synonyms; (6) Zone-aware creation biasing; (7) Fix runs_with_learning gap.

**P2:** Schema v2 (done); track exploit_count/explore_count; expand procedural prompt pool; depth_breakdown for narrative; generate.py full growth or deprecate.

**P3:** Transition detection; parallax; coverage targets in snapshot; interpretation cap; batch-seed linguistic.

## Recommended next steps

1. Run backfill (dry-run then live): `python scripts/backfill_registry_names.py --api-base https://motion.productions --timeout 300`
2. Add depth computation for motion/lighting/composition/graphics in post_dynamic_discoveries.
3. Harden static sound key (primitive tones only).
4. Verify LOOP_EXTRACTION_FOCUS on Railway.
5. Seed five missing linguistic domains.

---

# Part IV — Manus AI report review & adoption

## Report summary

Architecture correct. Data gaps: Pure sound (deployment/sound_loop); six empty Blended categories (Worker merge added); colors_from_blends numeric names (backfill); linguistic domains (seed script); color coverage (coverage bias, color_sweep).

## Priority matrix → actions

| # | Finding | Action |
|---|---------|--------|
| 1 | Zero sound | Deploy sound_loop; verify POST; procedural audio mid/high |
| 2 | Six empty Blended | Worker merges learned_lighting/composition/etc. (done) |
| 3 | Non-semantic names | backfill_registry_names.py |
| 4 | Linguistic domains | seed_linguistic_domains.py |
| 5 | Color coverage | GET /api/registries/coverage; coverage bias; color_sweep |

## Verification checklist

LOOP_EXTRACTION_FOCUS set; sound_loop deployed; Balanced posting; backfill run; linguistic seeded; coverage monitored; tests pass.

## Findings status

Sound: Addressed (spec-derived fallback). Blended merge: Addressed (Worker). Names: Operational (run backfill). Linguistic: Addressed (seed script). Color: Addressed (bias, color_sweep). Phases B–F: Roadmap.

---

# References

- **REGISTRY_FOUNDATION.md** — Authoritative foundation
- **WORKFLOWS_AND_REGISTRIES.md** — Full picture
- **MISSION_AND_OPERATIONS.md** — Strategic operations
- **RAILWAY_CONFIG.md** — Service config, env, post-deploy checklist
- **PRECISION_VERIFICATION_CHECKLIST.md** — Operator verification
- **ALGORITHMS_AND_FUNCTIONS_AUDIT.md** — Audit of extraction/growth
- **scripts/backfill_registry_names.py**, **scripts/color_sweep.py**, **scripts/registry_export_analysis.py**
