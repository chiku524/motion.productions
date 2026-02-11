# Registry & Loop Workflow Audit

**Date:** 2026-02-11  
**Based on:** `JSON Registry Exports/motion-registries-2026-02-11.json` + codebase analysis

This document answers your questions and provides actionable recommendations to ensure:
1. All discoveries receive authentic/semantic names
2. All publicly documented primitives are present and utilized
3. Interpretation registry is populated and ready for any prompt
4. Depth calculation is complete for all blend types
5. Narrative (including style) is fully populated
6. Dynamic sound discovery is optimized
7. Precision gap is addressed

---

## 1. Discovery Naming: Semantic vs Generic

### Current state
- **Python side** (`blend_names.py`): Uses `generate_sensible_name()` and `generate_blend_name()` → produces names like `color_suntor`, `color_velvet`, `motion_drift` (prefix + invented word from curated syllables).
- **Cloudflare side** (Worker): When discoveries arrive with `name: ""`, the API uses `generateUniqueName()` which invents words like `sacilalumila`, `rolirabivira`, or falls back to `dsc_<uuid>` when no unique name is found.

### The split
- **Static/dynamic growth (Python)** → names assigned locally via `generate_sensible_name` before sync. These show as `color_suntor`, `color_leaf`, etc. ✅
- **Discoveries from `grow_and_sync_to_api`** → sent with `"name": ""`. The Worker assigns names when persisting to D1. The Worker uses `generateUniqueName()` (consonant+vowel invention) → `sacilalumila`-style names, or `dsc_<uuid>` fallback. ❌ Not using the Python semantic generator.

### Recommendation
- **Option A:** Have Python assign names for all discoveries (including blends from `grow_and_sync_to_api`) before sending, so the API receives non-empty `name` and never calls `generateUniqueName`.
- **Option B:** Implement semantic name generation in the Worker (mirror `blend_names.py` logic) and use it instead of `generateUniqueName` when `name` is empty.

---

## 2. Primitive/Origin Coverage vs Publicly Documented

### Current origins (`origins.py`)
| Domain | Current primitives | Gaps vs public taxonomy |
|--------|---------------------|-------------------------|
| **Camera** | static, pan, tilt, dolly, crane, zoom, zoom_out, handheld | Missing: roll, truck, pedestal, arc, tracking/follow, bird's-eye, whip-pan |
| **Transition** | cut, fade, dissolve, wipe | Matches common set |
| **Motion** | static, slow, medium, fast, steady, pulsing, wave, random | Adequate; smoothness/directionality in origins but may not all flow to UI |
| **Audio** | tempo (3), mood (5), presence (5) | Canonical sound has 13 combos; need to ensure all used in prompt/spec generation |
| **Narrative style** | cinematic, abstract, minimal, realistic, anime | SceneSpec has **no** `style` field → never extracted → narrative style stays empty |
| **Lighting** | contrast_ratio: flat, normal, high, chiaroscuro | Matches |
| **Color** | 16 primaries in UI; 5 in blend_depth (black, white, red, green, blue) | Blend depth uses subset; consider full set for depth |

### Recommendations
1. **Add missing camera primitives** to `CAMERA_ORIGINS` and Worker `dynamicCanonical.camera_motion`: roll, truck, pedestal, arc, tracking, bird_eye, whip_pan.
2. **Add `style` to SceneSpec** and have `parse_prompt_to_spec` populate it from keywords (e.g. KEYWORD_TO_STYLE mapping cinematic, abstract, minimal, etc.).
3. **Expand audio diversity** in procedural prompt/spec generation so tempo, mood, and presence vary (slow/calm/silence, fast/tense/sfx, etc.), not just medium/neutral/ambient.
4. **Audit** origins against [MovieLabs ontology](https://mc.movielabs.com/docs/ontology/) and film production standards for full coverage.

---

## 3. Precision Gap (60% vs 95% Target)

### What precision measures
`precision_pct` = (runs with a `learning_runs` row) / (last N completed jobs).  
A run has “learning” if `POST /api/learning` succeeded and created a row with that `job_id`.

### Likely causes of the gap
1. **Different completion paths:** Some jobs may be completed by flows that do **not** call `POST /api/learning` (e.g. generate_bridge, manual upload). Those completed jobs will have no learning_run.
2. **API failures:** If `POST /api/learning` fails (503, timeout), no row is created; the run still “succeeds” from the user’s perspective.
3. **Your hypothesis (discovery exhaustion):** As the loop reuses combinations, **novel discoveries** decrease. That affects **registry growth**, not the learning_run count. Precision is about *logging*, not discovery. So discovery exhaustion doesn’t directly explain the precision gap, but it does explain why growth slows over time.

### Recommendations
1. **Trace job completion:** Ensure every path that marks a job “completed” also logs a learning run (or explicitly record “no-learning” where appropriate).
2. **Improve learning POST reliability:** Retry on 5xx; consider a small queue for failed logs.
3. **Add a “discovery rate” metric:** `(runs with any novel discovery) / total runs` to track discovery exhaustion separately from precision.

---

## 4. Interpretation Registry Empty

### Why it’s empty
Interpretations are populated by **`interpret_loop.py`**, a separate process that:
1. Processes pending items from `GET /api/interpret/queue`
2. Backfills prompts from `GET /api/interpret/backfill-prompts` (from the `jobs` table)
3. Calls `interpret_user_prompt()` and stores results via `POST /api/interpretations`

If `interpret_loop.py` is **not deployed** (e.g. only `automate_loop.py` runs on Railway), no interpretations are ever created.

### Recommendations
1. **Deploy `interpret_loop.py`** as a separate Railway (or similar) service.
2. **Backfill existing jobs:** Once running, it will pull prompts from completed jobs and interpret them, populating the registry.
3. **Pre-warm with common prompts:** Optionally seed the interpretation registry with a curated list of user-like prompts before going live.

---

## 5. full_blend depth_pct: 0 — Incomplete Depth Calculation

### Root cause
`compute_full_blend_depths()` returns a **nested** structure:
```json
{
  "color": { "black": 0.5, "white": 0.5 },
  "motion": { "slow": 0.6, "static": 0.4 },
  "lighting": { "normal": 0.7, "flat": 0.3 }
}
```

The Worker’s `depthFromBlendDepths()` only handles **flat** `{ key: number }`:
```ts
for (const [k, v] of Object.entries(depths)) {
  if (typeof v === "number") depth_breakdown[k] = ...
}
```
For full_blend, `v` is an object, not a number, so nothing is added → `depth_breakdown` stays `{}`, `depth_pct` stays 0.

### Recommendation
Flatten nested primitive depths for full_blend when computing `depth_pct` and `depth_breakdown`, e.g.:
- Prefix keys: `color.black`, `motion.slow`, `lighting.normal`
- Or use a single aggregated `depth_pct` (e.g. max across domains) and merge breakdowns.

---

## 6. Narrative Style Empty; Few Narrative Entries

### Why style is empty
- **SceneSpec** (from procedural prompts) does **not** have a `style` field.
- `extract_narrative_from_spec()` does `getattr(src, "style", None)` → always `None` for SceneSpec.
- `NARRATIVE_ORIGINS` has `style: ["cinematic", "abstract", "minimal", "realistic", "anime"]`, but nothing ever writes to the narrative registry for style when the spec has no style.

### Why other narrative aspects are thin
- Narrative values come from the **spec** (genre, tension_curve, audio_mood, lighting_preset, shot_type, palette_name).
- Procedural prompts tend to reuse similar values (e.g. `genre=general`, `lighting_preset=neutral`), so variety is low.
- `ensure_narrative_primitives_seeded()` seeds primitives into **local** narrative JSON; syncing to D1 happens via `post_narrative_discoveries`, which only sends **novel** values from `grow_narrative_from_spec`. If the spec rarely has novel genre/mood/settings, few entries are added.
- **Bug:** `automate_loop.py` line 320 checks `("genre", "mood", "plots", "settings", "themes", "scene_type")` but omits **"style"** — so even if style were extracted, it would not be posted to the API.

### Recommendations
1. **Add `style` to SceneSpec** and populate it from `parse_prompt_to_spec` (e.g. KEYWORD_TO_STYLE from prompt words).
2. **Increase narrative variety in procedural prompts:** Vary genre, mood, settings, style in `generate_procedural_prompt` so more combinations reach the narrative registry.
3. **Seed narrative primitives in D1:** Run `ensure_narrative_primitives_seeded` and sync those seeded values to D1 so the registry has full origin coverage even before discoveries.

---

## 7. Dynamic Sound: Only 3 Discoveries vs 13 Canonical

### Why so few
- Audio discoveries come from the **spec** (`audio_tempo`, `audio_mood`, `audio_presence`).
- Procedural generation often uses defaults: `medium`, `neutral`, `ambient`.
- The same combo is recorded repeatedly; unique combos are few.

### Recommendation
**Diversify audio in procedural prompts:**
- Add audio-related keywords to `generate_procedural_prompt` (e.g. “calm”, “tense”, “upbeat”, “quiet”, “driving”).
- Map keywords to `audio_tempo`, `audio_mood`, `audio_presence` so we get slow/calm/silence, fast/tense/sfx, etc.
- Use `knowledge` (learned_colors, learned_motion) to bias toward less-seen audio combos.

---

## 8. Summary: Action Items

| Priority | Task | Owner / Location |
|----------|------|-------------------|
| **P1** | Add `style` to SceneSpec + KEYWORD_TO_STYLE in procedural parser | `src/procedural/parser.py` |
| **P1** | Deploy `interpret_loop.py` so interpretation registry is populated | Railway/config |
| **P1** | Fix full_blend depth: flatten nested primitive_depths in Worker | `cloudflare/src/index.ts` |
| **P2** | Assign semantic names in Python for all discoveries (avoid Worker fallback) | `src/knowledge/remote_sync.py` |
| **P2** | Add missing camera primitives (roll, truck, pedestal, arc, etc.) | `origins.py`, Worker `dynamicCanonical` |
| **P2** | Diversify audio in procedural prompts | `src/automation/prompt_gen.py` |
| **P2** | Diversify narrative (genre, mood, settings, style) in procedural prompts | `src/automation/prompt_gen.py` |
| **P2** | Add "style" to narrative sync check in automate_loop (line 320) | `scripts/automate_loop.py` |
| **P3** | Audit origins against MovieLabs / public taxonomy | `origins.py` |
| **P3** | Add “discovery rate” metric (runs with novel discovery / total) | API + UI |

---

## References
- `src/knowledge/origins.py` — primitive definitions
- `src/knowledge/blend_depth.py` — `compute_full_blend_depths`
- `src/knowledge/blend_names.py` — semantic naming
- `cloudflare/src/index.ts` — `depthFromBlendDepths`, `generateUniqueName`
- `src/knowledge/narrative_registry.py` — `extract_narrative_from_spec`, `ensure_narrative_primitives_seeded`
- `scripts/interpret_loop.py` — interpretation worker
- MovieLabs ontology: https://mc.movielabs.com/docs/ontology/
