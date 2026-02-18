# Loop standards — algorithms and growth model

Both workflow loops use **set algorithms and functions** and grow from **origin/primitive values + extracted values**. Registries store all values; each entry’s **depth %** is with respect to the **origin value(s) that it stems from** (not a single global origin).

---

## 1. Interpretation loop — language standard

**Goal:** Interpret every prompt in a consistent standard of language (primarily English, dialects, slang/lingo).

### Algorithms and functions (code)

| Algorithm | Purpose | Where |
|-----------|---------|--------|
| **Normalize prompt** | Trim, length cap (e.g. 2000 chars). | `language_standard.normalize_prompt_for_interpretation` |
| **Extract words** | Lowercase alphabetic tokens for lookup. | `parser._extract_words` |
| **Dialect normalize** | Map variant → one form for lookup (e.g. colour→color, grey→gray). | `language_standard.normalize_word_for_lookup`, `DIALECT_NORMALIZE` |
| **Merge linguistic lookup** | Per domain: **base (origin) keywords** → **built-in slang/dialect** → **fetched linguistic registry** (extracted from past runs). | `language_standard.merge_linguistic_lookup`; used by `parser._merge_linguistic` |
| **Resolve word → canonical** | First match in merged lookup; negation and duration use dedicated patterns. | Parser `_resolve_*` (palette, motion, lighting, gradient, camera, genre, etc.) |
| **Extract mappings** | (span, canonical, domain, variant_type) from prompt + instruction for growth. | `linguistic.extract_linguistic_mappings` |
| **Variant type** | Classify span→canonical as synonym, dialect, or slang. | `language_standard.infer_variant_type` |

### Resolution order (per domain)

1. **Origin/primitive** — `KEYWORD_TO_PALETTE`, `KEYWORD_TO_MOTION`, etc. (procedural data).
2. **Built-in linguistic** — `BUILTIN_LINGUISTIC` in `language_standard.py` (lit→warm_sunset, chill→ocean, etc.).
3. **Fetched linguistic registry** — D1/API span→canonical from previous interpretation runs.

So every interpretation uses the same standard: primitives first, then learned mappings. New mappings are extracted and posted to the linguistic registry for future runs.

### Growth from extracted values

- **Prompt generation** uses `get_knowledge_for_creation`: learned colors, motion, gradient, camera, by_keyword, by_palette, interpretation_prompts.
- **Avoid set** = existing interpretation prompts so we don’t duplicate.
- **Linguistic growth** = extracted (span, canonical, domain) → `POST /api/linguistic-registry/batch`.

---

## 2. Video generation loop — MP4 aspects standard

**Goal:** Create, extract, and learn MP4 aspects using pure (static), blended (dynamic), and semantic (narrative) categories, all from origin/primitive + extracted values.

### Algorithms and functions (code)

| Aspect type | Origin/primitives | Extraction | Growth |
|-------------|-------------------|------------|--------|
| **Pure (static)** | `STATIC_COLOR_PRIMITIVES`, `STATIC_SOUND_PRIMITIVES` (static_registry). | Per-frame color (dominant RGB), per-frame sound. | `ensure_static_color_in_registry`, `ensure_static_sound_in_registry`; depth_breakdown with respect to the origin value(s) each entry stems from. |
| **Blended (dynamic)** | Gradient, camera, transition, audio_semantic origins (origins.py; seeded in growth). | Per-window: motion, time, gradient, camera, lighting, composition, graphics, temporal, technical, transition, depth. | `ensure_dynamic_*_in_registry`; primitive_depths; learned_colors, learned_motion, learned_blends (D1). Depth % with respect to the origin(s) that entry stems from. |
| **Semantic (narrative)** | `NARRATIVE_ORIGINS` (genre, mood, themes, plots, settings, style, scene_type). | From spec/instruction after interpretation. | `ensure_narrative_in_registry`; narrative_entries (D1). |

### Creation: instruction + knowledge (original + learned values)

1. **Instruction** from interpretation (prompt → palette, motion, gradient, camera, etc.).
2. **Knowledge** from `get_knowledge_for_creation`: **original** (origin/primitive) values and **learned** values (learned_colors, learned_motion, learned_gradient, learned_camera, interpretation_prompts).
3. **Blending** uses primitive lists + learned values; the exact transformed value is what gets stored.

### Growth from extracted values

- **Static:** Per-frame extraction → novel color/sound → add with semantic name; depth % with respect to the origin value(s) that entry stems from (e.g. color → black/white; sound → primitives).
- **Dynamic:** Per-window extraction + spec-derived (e.g. audio_semantic) → novel keys → add with semantic name; primitive_depths with respect to the origin(s) that entry stems from.
- **Narrative:** Spec/instruction → novel genre, mood, themes, etc. → add with semantic name.
- **Sync:** All discoveries POST to API (static_colors, static_sound, learned_colors, learned_motion, learned_blends, narrative_entries).

---

## 3. Shared principles

| Principle | Interpretation loop | Video loop |
|-----------|----------------------|------------|
| **Primitives first** | Base keyword dicts (KEYWORD_*) are the canonical set. | STATIC_*_PRIMITIVES, origins.py, NARRATIVE_ORIGINS. |
| **Then extracted** | Built-in + linguistic registry (span→canonical). | Learned colors, motion, gradient, camera, narrative entries. |
| **Precise algorithms** | Normalize → merge lookup → resolve → extract mappings. | Extract from frames/spec → compare to registry → add novel with depth. |
| **Registries** | Interpretations + linguistic registry (D1). | Static, dynamic, narrative tables + learned_* (D1). |
| **Depth/origin** | N/A (interpretation is prompt→instruction). | depth_breakdown / primitive_depths: % with respect to the origin value(s) that each entry stems from. |

Both loops are designed so that **accuracy** (what we store) and **precision** (how we compute) are defined in code; registries hold values and depth percentages, not the algorithms.

---

## 4. See also

- [WORKFLOWS_AND_REGISTRIES.md](WORKFLOWS_AND_REGISTRIES.md) — Where values live (Part I); workflow steps and prompt selection (Part II).
- [REGISTRY_FOUNDATION.md](REGISTRY_FOUNDATION.md) — Four registries, depth rules, naming.
- `src/interpretation/language_standard.py` — Language standard (built-in linguistic, merge, variant type).
- `src/knowledge/origins.py` — Primitives for MP4 aspects.
