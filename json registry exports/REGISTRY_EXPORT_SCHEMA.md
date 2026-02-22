# Registry export schema

Exports from the **Export JSON** action on the registries page produce a JSON file with this structure.

## Top-level

- **exported_at** — ISO 8601 timestamp (e.g. `2026-02-21T16:22:36.140Z`).
- **registries** — Object with `pure_static`, `blended_dynamic`, and `semantic_narrative`.
- **loop_progress** (optional) — Learning loop stats: `last_n`, `total_runs`, `precision_pct`, `target_pct`, `runs_with_learning`, `discovery_rate_pct`, `repetition_score`.

## Key format (canonical)

- **Color keys** are always **`"r,g,b"`** (e.g. `"100,125,150"`).  
  Static discoveries may be stored internally with an opacity suffix (e.g. `"100,125,150_1.0"`); the export normalizes to `"r,g,b"` for consistency with blended (dynamic) colors.
- **Sound keys** — e.g. `"0.5_neutral"`, `"0.03_mid_mid"` (strength/tone/timbre or similar).
- **Narrative** — `entry_key` and `value`; for low-count entries the displayed `name` is the same as `value`.

## pure_static

- **primitives**
  - **color_primaries** — Array of `{ name, r, g, b }` (the 16 base colors).
  - **sound_primaries** — Array of strings (e.g. silence, rumble, tone, hiss).
- **discoveries**
  - **colors** — Array of:
    - **key** — `"r,g,b"`.
    - **r, g, b, name, count, depth_pct**.
    - **depth_breakdown** — Object mapping **color primitive names only** (black, white, red, green, blue, yellow, cyan, magenta, orange, purple, pink, brown, navy, gray, olive, teal) to contribution percentages (0–100).
    - **opacity_pct** (optional) — 0–100 when the discovery had an opacity component.
    - **theme_breakdown** (optional) — When the blend was computed from theme/preset names (e.g. ocean, default, night, forest, warm_sunset, fire, dreamy, neon), those contributions appear here instead of in `depth_breakdown`. This keeps `depth_breakdown` strictly for color primitives.
  - **sound** — Array of `{ key, name, count, strength_pct?, depth_breakdown? }`. **strength_pct** = amplitude/weight of the sound in that instant (0–100%). The four primitives (silence, rumble, tone, hiss) are always present (count 0 if never recorded). Display names are normalized (e.g. `sound_` prefix stripped).

## Depth (one concept)

- **Depth** = how much a discovery is composed of **origin primitives** (and, for static color, theme/opacity). **depth_pct** is a single-number summary (e.g. 100 when we have a full breakdown). **depth_breakdown** (or “Depth vs primitives”) is the full picture: each primitive with its contribution %. So there is one depth concept; “Depth %” is not a second kind of depth.

## blended_dynamic

- **canonical** — `gradient_type`, `camera_motion`, `motion`, `sound` (arrays of allowed values).
- **discoveries**
  - **colors** — Same shape as pure_static discoveries (key = `"r,g,b"`, **depth_breakdown** = primaries only, optional **opacity_pct**, **theme_breakdown**). Whole-video dominant color (one per video).
  - **colors_from_blends** — Color-domain entries from learned_blends (same shape as other blend rows).
  - **motion, gradient, camera, sound** — Per-domain discovery lists with **name**, **key**, **depth_pct**, **depth_breakdown**.
  - **lighting, composition, graphics, temporal, technical** — Domain-specific blend lists (from learned_blends); only present when non-empty.
  - **blends** — **Fallback only**: entries that could not be labeled under a single category (e.g. full_blend, narrative).

## semantic_narrative

- **genre, mood, themes, plots, settings, style, scene_type** — Each is an array of:
  - **entry_key**, **value** — Identifier and value (often equal).
  - **name** — Display name: for entries with **count** below a threshold (e.g. 5), **name** is the same as **value**; otherwise it may be a generated or corrected semantic name (typos like `genre_starer` are corrected in the API response).
  - **count** — Number of times this value was recorded.

## interpretation / linguistic

- **interpretation** — Resolved prompts and instructions.
- **linguistic** (if present) — Variant mappings: **span**, **canonical**, **domain**, **variant_type**, **count**.

## Naming and uniqueness

- **Color names** in the API/export are disambiguated when the same name would appear for different keys (e.g. multiple “Cyan” entries). Duplicates are suffixed with the key: `"Cyan (100,125,175)"`.
- **Narrative** low-count entries use the **value** as the displayed **name** to avoid random or placeholder names in the export.
