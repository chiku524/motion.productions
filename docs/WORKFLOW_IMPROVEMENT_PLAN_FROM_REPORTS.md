# Workflow Improvement Plan (from Registry Comparison & Enhancement Reports)

**Date:** February 24, 2026  
**Sources:** *Motion.Productions_Registry_Comparison_&_Optimization_Report.pdf*, *enhancement_and_optimization_report.md.pdf*  
**Scope:** All four registries, five workflows, and docs; three registry snapshots (Feb 21, 22, 24).

---

## 1. Summary of report findings

### What’s working

- **Blended registry “unlocking”:** Feb 22→24 saw large growth in lighting (+526), composition (+93), graphics (+46), temporal (+9), blends (+15), motion (+46). Per-window extraction and `grow_dynamic_from_video` are feeding the dynamic registry as intended.
- **Pure static:** Color depth_breakdown improved (235→342 with full 16-primitive breakdown); sound moved from placeholders to 42 active discoveries with strength_pct and depth; opacity_pct and theme_breakdown are present.
- **Schema and pipeline:** `exported_schema_version: 2` and `coverage_snapshot` are in exports; schema doc has been updated to describe them. Core loop (Interpret → Create → Render → Extract → Grow/Sync) is functioning.

### Critical issues to fix

| Issue | Registry / area | Impact |
|-------|------------------|--------|
| **Numeric-suffix names** (e.g. Slate5441, Violet4817) | Blended (colors_from_blends, blends) | 99%+ of colors_from_blends; blocks “authentic semantic name” goal |
| **Missing depth_breakdown** for per-window dynamic categories | Blended (motion, lighting, composition, graphics, temporal, technical) | 0% depth on motion/lighting/composition/graphics; names without primitive composition |
| **Pure sound key leakage** (calm, tense, dark, uplifting in tone slot) | Pure (static_sound) | REGISTRY_FOUNDATION requires primitive tones only (low, mid, high, silent, neutral) |
| **15% runs_with_learning gap** (total_runs vs runs_with_learning) | Loop | ~15% of cycles not contributing to knowledgebase |
| **Semantic registry stagnation** | Semantic (all categories) | Zero growth across snapshots; prompt pool not discovering new narrative values |
| **Linguistic gaps** | Interpretation | Missing domains: transition, shot, theme, mood, setting; low tone/style resolution |
| **Color bias** | Pure (colors) | Heavy cool/neutral bias; warm and green zones underused; creation favors high-count entries |
| **Schema doc drift** | Docs | Done: v2 and coverage_snapshot documented in REGISTRY_EXPORT_SCHEMA.md |

---

## 2. Prioritized action plan

### P0 — Critical (do first)

| # | Action | Where | Notes |
|---|--------|--------|--------|
| 1 | **Run and automate `backfill_registry_names.py`** | `scripts/backfill_registry_names.py` | Fix ~395 numeric names in colors_from_blends. Run: `python scripts/backfill_registry_names.py --api-base https://motion.productions --timeout 300` (use `--dry-run` first). Add to OPERATIONAL_CHECKLIST / CI or cron. |
| 2 | **Add depth_breakdown to per-window dynamic growth** | `grow_dynamic_from_video` path; `_ensure_dynamic_in_registry` / post_dynamic_discoveries | Motion, lighting, composition, graphics (and temporal/technical if applicable) currently send no depth. Implement `compute_motion_depth`, `compute_lighting_depth`, etc. (or equivalent) and pass depth_breakdown in the payload to POST /api/knowledge/discoveries. API already accepts and stores `depth_breakdown_json` for learned_motion, learned_lighting, etc. |
| 3 | **Enforce primitive-only tones in static sound key** | Extractor: `_static_sound_key` / sound key format | Reject or map non-primitive tone values (calm, tense, dark, uplifting) to the allowed set (low, mid, high, silent, neutral). Per REGISTRY_FOUNDATION.md; semantic mood belongs in Blended audio_semantic, not Pure sound. |

### P1 — High

| # | Action | Where | Notes |
|---|--------|--------|--------|
| 4 | **Seed linguistic registry with missing domains** | language_standard.py or seed script; BUILTIN_LINGUISTIC | Add initial mappings for: **shot** (close-up→close, wide→wide, etc.), **transition** (fade, dissolve, cut, wipe), **mood**, **theme**, **setting**. One-time seed script or extend BUILTIN_LINGUISTIC. |
| 5 | **Add tone and style synonyms** | language_standard.py | Increase resolution rate for tone and style instruction fields (currently ~16% and ~3%); add comprehensive synonyms to built-in mappings. |
| 6 | **Zone-aware creation biasing (colors)** | builder.py: `_build_pure_color_pool` / creation phase | Bias creation toward underused RGB zones (warm, green) and/or use `weighted_choice_favor_underused` (count-inverse) to break high-count feedback loop. See REGISTRY_REVIEW_AND_IMPROVEMENT_PLAN.md. |
| 7 | **Diagnose and fix runs_with_learning gap** | automate_loop; POST /api/learning | Add logging and optional dead-letter/retry for failed learning POSTs. Ensure job_id is passed through so learning is attributed. |

### P2 — Medium

| # | Action | Where | Notes |
|---|--------|--------|--------|
| 8 | **Formalize schema v2** | REGISTRY_EXPORT_SCHEMA.md | ✅ Done: exported_schema_version, coverage_snapshot, loop_progress documented. Optionally document coverage_snapshot shape and any new Blended category shapes in more detail. |
| 9 | **Track exploit_count / explore_count** | automate_loop.py; loop_progress export | Populate and persist so the 3-workflow balance (exploit vs explore) can be monitored. |
| 10 | **Expand procedural prompt pool (Semantic)** | automate_loop / prompt generation | Add genre, mood, setting, theme (and plot) keywords so new narrative values are discovered; consider a dedicated “narrative exploration” mode. |
| 11 | **depth_breakdown for narrative** | ensure_narrative_in_registry | Where applicable (e.g. mood as blend of origin moods), compute and store depth_breakdown for Semantic entries. |
| 12 | **generate.py: full growth or deprecate** | generate.py | Either call grow_from_video, grow_dynamic_from_video, grow_narrative_from_spec and post_*_discoveries when learning is desired, or deprecate in favor of generate_bridge.py --learn. See ALGORITHMS_AND_FUNCTIONS_AUDIT.md. |

### P3 — Lower / strategic

| # | Action | Where | Notes |
|---|--------|--------|--------|
| 13 | **Transition detection and blended_transition** | extract_dynamic_per_window; ensure_dynamic_*_in_registry | Add transition category to dynamic extraction and registry (cut, fade, dissolve, wipe) for video-editing completeness. |
| 14 | **Parallax/depth_parallax** | _resolve_depth_parallax; prompt pool | Add keywords and parallax-focused prompts so depth_parallax is populated in interpretations. |
| 15 | **Coverage targets in coverage_snapshot** | Export / schema | Define and track primitive-combination coverage targets (e.g. % of RGB zones, % of motion combos) in coverage_snapshot. |
| 16 | **Interpretation cap (100 entries)** | API / config | Review cap; consider rotation or increase so interpretation registry can grow with new prompts. |
| 17 | **Batch-seed linguistic registry** | Script + curated lists | Proactively add synonyms, slang, and domain terms for color, motion, mood, etc. to accelerate interpreter robustness. |

---

## 3. Recommended next steps (immediate)

1. **Run backfill (dry-run then live)**  
   - Dry-run (preview only):  
     `python scripts/backfill_registry_names.py --dry-run`  
   - Full run:  
     `python scripts/backfill_registry_names.py --api-base https://motion.productions --timeout 300`  
   - For a faster pass on one table:  
     `python scripts/backfill_registry_names.py --api-base https://motion.productions --table learned_blends --timeout 300`  
   - Add to OPERATIONAL_CHECKLIST or cron so names stay semantic after new discoveries.

2. **Locate dynamic depth computation**  
   - In `src/`: find where `post_dynamic_discoveries` builds payloads for motion, lighting, composition, graphics.  
   - Confirm whether `blend_depth` (or equivalent) has or can have `compute_motion_depth`, `compute_lighting_depth`, etc.  
   - Add depth computation and include `depth_breakdown` in each payload; verify Cloudflare Worker persists it (already has columns).

3. **Harden static sound key**  
   - In extractor/key logic for static sound, ensure the tone slot only allows primitive values; map or reject calm/tense/dark/uplifting.

4. **Verify 3-workflow model**  
   - Confirm Railway (or run env) uses `LOOP_EXTRACTION_FOCUS=frame` vs `window` as intended; check logs for “Growth [frame]” and “Growth [window]”.

5. **Linguistic seed**  
   - Add the five missing domains (shot, transition, theme, mood, setting) and expand tone/style in BUILTIN_LINGUISTIC or via a one-time seed.

---

## 4. References

- **Registry Comparison & Optimization Report** — Schema v2, naming priority, creation biasing, linguistic expansion, 3-workflow verification.
- **Enhancement & Optimization Report** — P0/P1/P2/P3 table, depth_breakdown gap, sound key integrity, learning gap, Semantic stagnation, coverage targets.
- **In repo:** `REGISTRY_EXPORT_SCHEMA.md`, `REGISTRY_REVIEW_AND_IMPROVEMENT_PLAN.md`, `ALGORITHMS_AND_FUNCTIONS_AUDIT.md`, `OPERATIONAL_CHECKLIST.md`, `MISSION_AND_OPERATIONS.md`, `scripts/backfill_registry_names.py`.
