# Motion Productions — Roadmap to Authentic AI Video

This roadmap outlines the path to video generation that uses industry aspects (cinematography, lighting, composition, narrative, etc.) to produce high-quality, varied output from user prompts.

---

## Vision

Video generation software that can utilize any aspect within the movie industry — cinematography, lighting, color, composition, motion, editing, narrative, genre — to produce high-quality videos based on user intent.

---

## Phase 1: Expand Visual Vocabulary

**Goal:** Move from "gradient + one motion" to varied visuals and motion types.

| Task | Description | Status |
|------|-------------|--------|
| 1.1 | Add gradient types (vertical, radial, angled, horizontal) | Done |
| 1.2 | Add shape primitives (circle, rect) as overlay layers | Done |
| 1.3 | Add camera-style motion (zoom, zoom_out, pan, rotate) | Done |
| 1.4 | Support multiple layers (background + shape overlay) | Done |
| 1.5 | Extend keywords for gradient_type, camera_motion, shape | Done |
| 1.6 | Wire new params through interpretation → creation → renderer | Done |

**Success criteria:** Same prompt can produce different layouts; zoom/pan/rotate visible; radial and angled gradients work.

---

## Phase 2: Cinematography and Scene Structure

**Goal:** Think in shots and camera work; scenes with transitions.

| Task | Description | Status |
|------|-------------|--------|
| 2.1 | Shot types: wide, medium, close-up, POV | Done |
| 2.2 | Camera motion: static, pan, dolly, crane, handheld | Done |
| 2.3 | Transitions: cut, fade, dissolve, wipe | Done |
| 2.4 | Scene model: sequence of shots with duration and transitions | Done |
| 2.5 | Pacing control (slow/fast per segment) | Done |

**Success criteria:** Prompt → scene script with shots and transitions; video respects pacing.

---

## Phase 3: Lighting and Color as First-Class

**Goal:** Lighting and color drive mood and quality.

| Task | Description | Status |
|------|-------------|--------|
| 3.1 | Lighting model: key, fill, rim, ambient | Done |
| 3.2 | Color grading: LUT-style transforms, contrast, saturation | Done |
| 3.3 | Mood presets (noir, golden hour, neon, documentary) | Done |
| 3.4 | Keyword → lighting and grade | Done |

**Success criteria:** Same scene looks different under different lighting/grading.

---

## Phase 4: Content Layers (Text, Graphics, Diagrams)

**Goal:** Support information and narrative overlays.

| Task | Description | Status |
|------|-------------|--------|
| 4.1 | Text rendering: titles, subtitles, bullet points | Done |
| 4.2 | Graphics primitives: arrows, callouts, highlights | Done |
| 4.3 | Educational templates (concept → example → summary) | Done |
| 4.4 | Prompt parsing for "explain X", "tutorial about Y" | Done |

**Success criteria:** Educational/explainer videos with text and graphics.

---

## Phase 5: Narrative and Genre

**Goal:** Genre and story shape the whole video.

| Task | Description | Status |
|------|-------------|--------|
| 5.1 | Genre conventions (documentary, thriller, ad, etc.) | Done |
| 5.2 | Story beats: setup, development, climax, resolution | Done |
| 5.3 | Emotional arc: tension curves, pacing | Done |
| 5.4 | Templates per genre | Done |

**Success criteria:** Same system produces different "feel" for different genres.

---

## Phase 6: Sound

**Goal:** Audio that matches visuals and intent.

| Task | Description | Status |
|------|-------------|--------|
| 6.1 | Music: mood, tempo, genre selection | Done |
| 6.2 | SFX: transitions, emphasis, ambience | Done |
| 6.3 | Sync: beats aligned with cuts and motion | Done |
| 6.4 | Optional narration (TTS or pre-recorded) | Done |

**Success criteria:** Videos have appropriate audio; sync with cuts.

---

## Phase 7: Higher Realism (Optional)

**Goal:** Move beyond abstract visuals if desired.

| Task | Description | Status |
|------|-------------|--------|
| 7.1 | 2.5D / depth: parallax, layered depth | Done |
| 7.2 | Asset libraries: textures, shapes, icons | Done |
| 7.3 | 3D primitives or external model integration | Done |

**Success criteria:** More realistic or asset-driven visuals when enabled.

---

## Implementation Order

Phases build on each other:

```
Phase 1 (visuals) → Phase 2 (structure) → Phase 3 (lighting) → Phase 4 (content)
                                                        ↓
Phase 7 (realism) ← Phase 6 (sound) ← Phase 5 (narrative)
```

---

## Design Principles

1. **Procedural-first** — Generate from parameters; avoid black boxes.
2. **Knowledge in data** — Cinematography rules, genre rules in config.
3. **Layered architecture** — Intent → Director → Specialists → Renderer.
4. **Learn from output** — Loop continues to refine mappings.
5. **Modular growth** — Each phase adds new specialists without breaking existing behavior.

---

## Part 2: Educational animated (Phases A–F)

This track outlines the path to **educational yet entertaining animated videos, 2 minutes long, with characters, script, and objects**. See also [INTENDED_LOOP.md](INTENDED_LOOP.md).

## Target capability

**Input:** User describes a topic and desired style.

**Output:** A 2-minute animated video that teaches a concept in an engaging way; has characters (even if simple/stylized); follows a script (intro → content → recap); uses objects/props to illustrate ideas; is entertaining, not dry.

## Current state vs goal

| Capability | Current | Target |
|------------|---------|--------|
| Duration | Up to 2 min (segment concat) | ✓ 2 min supported |
| Educational structure | Templates, text overlay | ✓ Partial |
| Visual style | Abstract gradients, motion | Animated characters, objects |
| Characters | None | Characters with simple animation |
| Objects/props | Shape overlays only | Discrete objects, props |
| Script | Prompt → single interpretation | Multi-scene script with dialogue |
| Entertainment | Genre, pacing, tension | Characters, humor, narrative arc |

## Phase A: Domain coverage (Done)

Every domain from INTENDED_LOOP is represented in prompts and interpretation (color, motion, lighting, camera, composition, temporal, audio, narrative). Prompts and specs use all domains; the loop explores the full primitive space.

## Phase B: Multi-scene educational structure

**Goal:** 2-minute videos with clear educational flow (intro → concept → example → recap).

| Task | Description | Status |
|------|-------------|--------|
| B.1 | Script template: 4–6 beats (hook, concept, example, recap) | Pending |
| B.2 | Duration allocation per beat | Pending |
| B.3 | Beat-specific pacing | Pending |
| B.4 | Text overlays per beat | Partial |
| B.5 | Prompt: "explain X in 2 minutes" → structured script | Pending |

## Phase C: Object/entity primitives

**Goal:** Discrete objects and props before characters (entity model, object library, place in scene, object animation). **Status:** Pending.

## Phase D: Character system

**Goal:** Simple characters that can appear and move (primitive, animation, placement, expression). **Status:** Pending.

## Phase E: Script parsing

**Goal:** User provides a script; system breaks it into scenes and actions. **Status:** Pending (partial: text overlay sync).

## Phase F: Entertainment layer

**Goal:** Make educational content engaging (humor/tone, character personality, visual gags, pacing variation). **Status:** Pending (partial).

## Educational implementation order

Phase A (done) → B → C → D → E → F. The foundation (origins, interpretation, creation, loop) is in place; phases B–F add structure, objects, characters, script, and entertainment.
