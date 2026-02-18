# D1 database schema — audit and registry mapping

This document lists every D1 table, its role, and which registry it serves. There are **no unused or redundant tables**; each table is referenced by the Cloudflare Worker.

**Migrations:** Run in order (`0000` … `0012`). After adding `0012_depth_breakdown_and_strength.sql`, run migrations before deploying the Worker so new columns exist.

---

## Table → registry mapping

| Table | Registry | Purpose |
|-------|----------|---------|
| **jobs** | — | Generation jobs (prompt, status, r2_key, workflow_type). |
| **learning_runs** | — | Logged runs for learning (job_id, prompt, spec_json, analysis_json). |
| **events** | — | Event log (event_type, job_id, payload_json). |
| **feedback** | — | User feedback (job_id, rating). |
| **name_reserve** | — | Reserved names for uniqueness checks. |
| **static_colors** | **Pure** | Per-frame color entries (color_key, r, g, b, opacity, name, depth_breakdown_json). |
| **static_sound** | **Pure** | Per-frame sound noises (sound_key, name, strength_pct, depth_breakdown_json). |
| **narrative_entries** | **Semantic** | Narrative elements (aspect, entry_key, value, name, depth_breakdown_json). |
| **interpretations** | **Interpretation** | Resolved user prompts (prompt, instruction_json, status). |
| **learned_blends** | **Blended** | Blends with name, domain, output_json, primitive_depths_json. |
| **learned_colors** | **Blended** | Whole-video color discoveries (color_key, r, g, b, name). |
| **learned_motion** | **Blended** | Motion profiles (profile_key, motion_level, motion_trend, name). |
| **learned_lighting** | **Blended** | Lighting profiles. |
| **learned_composition** | **Blended** | Composition profiles. |
| **learned_graphics** | **Blended** | Graphics profiles. |
| **learned_temporal** | **Blended** | Temporal profiles. |
| **learned_technical** | **Blended** | Technical profiles. |
| **learned_audio_semantic** | **Blended** | Audio semantic (role, mood, tempo); depth_breakdown_json. |
| **learned_time** | **Blended** | Time profiles. |
| **learned_gradient** | **Blended** | Gradient profiles. |
| **learned_camera** | **Blended** | Camera profiles. |

---

## Migrations (in order)

| Migration | Contents |
|-----------|----------|
| 0000_initial.sql | jobs |
| 0001_learning_runs.sql | learning_runs |
| 0002_events_and_feedback.sql | events, feedback |
| 0003_learned_knowledge.sql | learned_blends, learned_colors, learned_motion, learned_lighting, learned_composition, learned_graphics, learned_temporal, learned_technical, name_reserve |
| 0004_static_registry.sql | static_colors, static_sound |
| 0005_narrative_registry.sql | narrative_entries |
| 0006_learned_audio_semantic.sql | learned_audio_semantic |
| 0007_learned_time.sql | learned_time |
| 0008_aspect_coverage.sql | ALTERs: static_colors (luminance, chroma, opacity), learned_motion (motion_direction, motion_rhythm) |
| 0009_workflow_type.sql | ALTER jobs (workflow_type) |
| 0010_interpretations.sql | interpretations |
| 0011_learned_gradient_camera.sql | learned_gradient, learned_camera |
| 0012_depth_breakdown_and_strength.sql | ALTERs: static_colors (depth_breakdown_json), static_sound (depth_breakdown_json, strength_pct), narrative_entries (depth_breakdown_json), learned_audio_semantic (depth_breakdown_json) |

---

## Design notes

- **Pure (static):** One frame = one instance. `static_colors` and `static_sound` store per-frame discoveries; sound entries use **actual noise names** and **strength_pct** (low/mid/high are measurements, not primitive names).
- **Blended (learned_*):** Categories (e.g. role, mood, tempo) hold **elements** (named entries with depth_breakdown). Kick, snare, bass, etc. are Blended elements.
- **Semantic (narrative_entries):** Categories (plot, setting, dialogue, genre, mood, …); elements are named entries with optional depth_breakdown.
- **Interpretation:** Program deals with the unknown until user input; this table stores resolved interpretations for reuse.

See [REGISTRY_FOUNDATION.md](REGISTRY_FOUNDATION.md) and [WORKFLOWS_AND_REGISTRIES.md](WORKFLOWS_AND_REGISTRIES.md) (Part I).
