# The Intended Loop

This document describes the core design of Motion Productions: base knowledge from **origins** (primitives of every film/video aspect), continuous **interpretation** of user prompts, and a **learning loop** that grows knowledge from every generation.

---

## Vision

Motion Productions is built to be the **go-to AI video generator**. The software:

1. Uses the **origins** (fundamental primitives) of every aspect within filmmaking/video-making as its ground truth — base knowledge.
2. Is **ready for any user prompt** — abstract, unexpected, novel. The system interprets whatever the user provides without being limited to predefined templates.
3. **Grows continuously** — each generation is analyzed; what emerges from blending primitives becomes new knowledge. The more it generates, the more it learns.

---

## The Loop

```
┌─────────────────────────────────────────────────────────────────────────┐
│  ORIGINS (Base Knowledge)                                                │
│  Primitives of every film/video aspect: color, motion, lighting,         │
│  composition, temporal, audio, narrative, technical.                     │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  USER PROMPT (arbitrary input)                                           │
│  "A dreamy ocean at dusk with slow waves"                                │
│  "Explain quantum tunneling in 10 seconds"                               │
│  "Fast neon city pulse with parallax"                                    │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  INTERPRETATION                                                          │
│  Map prompt → parameters using origins + learned knowledge               │
│  Handle unknowns, negations, style hints, duration, etc.                 │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  CREATION (blend/combine primitives)                                     │
│  Use origins + learned values to build SceneSpec                         │
│  Blend palettes, motion types, lighting, etc.                            │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  OUTPUT (video)                                                          │
│  Procedural renderer produces frames → video file                        │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  EXTRACTION                                                              │
│  Analyze output: colors, motion, lighting, composition, consistency      │
│  Capture what actually appeared in the video                             │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  GROWTH                                                                  │
│  Compare extracted values to existing registry                           │
│  If novel → add to learned knowledge                                     │
│  If known → refine statistics, counts                                    │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    └──────────────────┐
                                                       │
                                    ┌──────────────────┘
                                    ▼
                         NEXT GENERATION
                    (can use origins + learned)
```

---

## Principles

### 1. Origins as Ground Truth

Base knowledge is **not** arbitrary named styles. It is the **primitives** of each domain:

| Domain | Primitives (origins) |
|--------|----------------------|
| **Color** | RGB, HSL; brightness, contrast, saturation |
| **Motion** | Speed, smoothness, directionality, rhythm, steadiness |
| **Lighting** | Key, fill, rim, ambient; contrast, saturation |
| **Composition** | Center of mass, balance, symmetry, framing |
| **Temporal** | Pacing, cut frequency, shot length |
| **Camera** | Pan, tilt, dolly, crane, zoom, static |
| **Transitions** | Cut, fade, dissolve, wipe |
| **Audio** | Tempo, mood, intensity, silence |
| **Narrative** | Genre conventions, tension curve |

### 2. Blending Creates New Knowledge

When the system combines primitives (e.g. blend two palettes, mix motion types), the output contains values that may not exist in the origins. Extraction captures these. If they are sufficiently novel, they are added to the learned registry. Future prompts can then use both origins and learned values.

**Blend naming and depth:** Every blend gets a unique name. For each blend, we record **primitive depths** — how far down each side of the blend is with respect to origin primitives. For example, a color blend of ocean + fire at 60/40 yields `primitive_depths: {"ocean": 0.6, "fire": 0.4}`. For full blends, depths are stored per domain: `{domain: {primitive: depth}}`. This enables reconstructing or explaining any output in terms of its origin contributions.

### 3. Interpretation Is Unbounded

The interpreter does not assume a fixed vocabulary. It:

- Maps known keywords to primitives or learned values
- Infers from context when words are unfamiliar
- Handles negations, intensity modifiers, duration, style
- Falls back to origins when no match exists

### 4. The Loop Never Stops

Each run: **prompt → interpret → create → output → extract → grow**. The more the loop runs, the richer the knowledge and the better the system interprets and generates.

---

## Implementation

- **Origins:** `src/knowledge/origins.py` — registry of primitives per domain
- **Blending:** `src/knowledge/blending.py` — blend functions for every origin primitive
- **Blend depth:** `src/knowledge/blend_depth.py` — compute primitive depths (how much each origin contributed)
- **Growth:** `src/knowledge/growth.py` — extraction → compare → add novel
- **Registry:** `config/knowledge/` — local JSON; when `api_base` is set, discoveries sync to D1/KV (Cloudflare Worker)
- **Interpretation:** `src/interpretation/` — prompt → parameters (uses origins + learned)
- **Creation:** `src/creation/` — build spec from interpretation + knowledge

---

## Summary

| Concept | Role |
|---------|------|
| **Origins** | Primitives of every film/video aspect; ground truth |
| **Interpretation** | Map any user prompt → parameters; ready for abstract input |
| **Creation** | Blend primitives; use origins + learned |
| **Extraction** | Capture what actually appeared in output |
| **Growth** | Add novel values to learned registry |
| **Loop** | Prompt → interpret → create → output → extract → grow → repeat |
