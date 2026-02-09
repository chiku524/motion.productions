# Roadmap: Educational Yet Entertaining Animated Video

This document outlines the path from the current state to **educational yet entertaining animated videos, 2 minutes long, with characters, script, and objects**.

See also: [INTENDED_LOOP.md](./INTENDED_LOOP.md), [ROADMAP.md](./ROADMAP.md).

---

## Target Capability

**Input:** User describes a topic and desired style.

**Output:** A 2-minute animated video that:
- Teaches a concept in an engaging way
- Has characters (even if simple/stylized)
- Follows a script (intro → content → recap)
- Uses objects/props to illustrate ideas
- Is entertaining, not dry

---

## Current State vs Goal

| Capability | Current | Target |
|------------|---------|--------|
| Duration | Up to 2 min (segment concat) | ✓ 2 min supported |
| Educational structure | Templates, text overlay | ✓ Partial |
| Visual style | Abstract gradients, motion | Animated characters, objects |
| Characters | None | Characters with simple animation |
| Objects/props | Shape overlays only | Discrete objects, props |
| Script | Prompt → single interpretation | Multi-scene script with dialogue |
| Entertainment | Genre, pacing, tension | Characters, humor, narrative arc |

---

## Phase A: Domain Coverage (Done)

**Goal:** Every domain from INTENDED_LOOP is represented in prompts and interpretation.

- ✓ Color, Motion, Lighting, Camera, Transitions
- ✓ Composition (balance, symmetry) — now in prompts
- ✓ Temporal (pacing) — now in prompts
- ✓ Audio (tempo, mood, presence) — now in prompts
- ✓ Narrative (tension curve) — now in prompts

**Impact:** Prompts and specs use all domains; the loop explores the full primitive space.

---

## Phase B: Multi-Scene Educational Structure

**Goal:** 2-minute videos with clear educational flow (intro → concept → example → recap).

| Task | Description | Status |
|------|-------------|--------|
| B.1 | Script template: 4–6 beats (hook, concept, example, recap) | Pending |
| B.2 | Duration allocation per beat (e.g. 0:00–0:20 intro, 0:20–1:00 concept) | Pending |
| B.3 | Beat-specific pacing (slower for concepts, faster for examples) | Pending |
| B.4 | Text overlays per beat (titles, bullets, key terms) | Partial |
| B.5 | Prompt: "explain X in 2 minutes" → structured script | Pending |

**Success criteria:** One prompt yields a 2-min video with distinct educational beats.

---

## Phase C: Object/Entity Primitives

**Goal:** Discrete objects and props before characters.

| Task | Description | Status |
|------|-------------|--------|
| C.1 | Entity model: position, scale, appearance, animation | Pending |
| C.2 | Object library: shapes, icons, simple props (arrow, box, icon) | Pending |
| C.3 | Place objects in scene per shot (e.g. "diagram with 3 boxes") | Pending |
| C.4 | Object animation: appear, move, highlight | Pending |
| C.5 | Prompt: "show diagram with labeled parts" | Pending |

**Success criteria:** Videos contain discrete, animated objects that illustrate concepts.

---

## Phase D: Character System

**Goal:** Simple characters that can appear and move.

| Task | Description | Status |
|------|-------------|--------|
| D.1 | Character primitive: silhouette or simple shape (e.g. stick, blob) | Pending |
| D.2 | Character animation: idle, gesture, speak (mouth movement) | Pending |
| D.3 | Character placement: on screen, facing, scale | Pending |
| D.4 | Expression/mood: happy, curious, explaining | Pending |
| D.5 | Prompt: "narrator explains X" → character on screen | Pending |

**Success criteria:** Videos feature a simple character that "explains" or "presents."

---

## Phase E: Script Parsing

**Goal:** User provides a script; system breaks it into scenes and actions.

| Task | Description | Status |
|------|-------------|--------|
| E.1 | Script format: scene descriptions, optional dialogue | Pending |
| E.2 | Parser: script → list of (scene, duration, text, character_actions) | Pending |
| E.3 | Map scenes to shots, pacing, and objects | Pending |
| E.4 | Sync text overlay with script timing | Partial |
| E.5 | Voice/TTS integration (optional) | Pending |

**Success criteria:** A written script drives the full 2-minute video structure.

---

## Phase F: Entertainment Layer

**Goal:** Make educational content feel engaging and entertaining.

| Task | Description | Status |
|------|-------------|--------|
| F.1 | Humor/tone hints: "lighthearted", "dramatic", "quirky" | Pending |
| F.2 | Character personality: curious, enthusiastic, deadpan | Pending |
| F.3 | Visual gags: objects react, exaggerate, highlight | Pending |
| F.4 | Pacing variation: faster for jokes, slower for key moments | Partial |
| F.5 | A/B test: same content, different tones | Pending |

**Success criteria:** Same educational content can feel dry vs entertaining based on user choice.

---

## Implementation Order

```
Phase A (domains) ✓
        ↓
Phase B (multi-scene structure) → Phase C (objects)
        ↓                              ↓
Phase E (script parsing) ← Phase D (characters)
        ↓
Phase F (entertainment)
```

**Recommended sequence:** A (done) → B → C → D → E → F.

---

## Dependencies

- **Duration:** Already supported via segment concatenation and temporal continuation.
- **Educational scaffolding:** `educational_template`, `text_overlay` exist; need beat-level structure.
- **Domain coverage:** All domains now in prompts and interpretation (Phase A complete).
- **Knowledge loop:** Continues to grow palettes, motion, etc.; will eventually include object/character combos.

---

## Summary

| Phase | Focus | Outcome |
|-------|-------|---------|
| A | Domain coverage | ✓ Done — prompts use all domains |
| B | Multi-scene structure | 2-min videos with educational beats |
| C | Objects | Discrete props and diagrams |
| D | Characters | Simple animated characters |
| E | Script parsing | Script → full video |
| F | Entertainment | Tone, humor, engagement |

The foundation (origins, interpretation, creation, loop) is in place. Phases B–F add layers: structure, objects, characters, script, and entertainment. Each phase builds on the previous; the loop will learn from each new capability.
