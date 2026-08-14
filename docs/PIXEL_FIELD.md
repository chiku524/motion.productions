# Pixel field — color, time, motion, and objects

This is the **authoritative reading** of how a video exists in this project. Algorithms that generate loop clips (`_render_pure_per_frame`, pairing specs, emergence) must follow it. Camera pans, walk cycles, and named objects are **later readings** of this field, not the primitive.

See also: [REGISTRY_FOUNDATION.md](REGISTRY_FOUNDATION.md) §7, [MP4_ASPECTS.md](MP4_ASPECTS.md), [INTENDED_LOOP.md](INTENDED_LOOP.md).

---

## 1. The primitive

A frame is a grid of pixels. Each pixel is an independent pairing of registry colors at one instant.

**Motion is those pixels changing color from frame to frame.** That is the only motion primitive. Nothing else is more basic.

- **Stillness** — a pixel keeps its pairing across frames.
- **Motion** — that pairing changes as time advances.

---

## 2. Synchronization forms objects and motion

An isolated pixel that changes color is flicker, not a thing.

**Objects and motion appear the more pixels change in synchronization** — same timing, same direction of color change, same pairing family — as time passes.

| Pixel behavior | What it reads as |
|----------------|------------------|
| Neighboring pixels hold still | A still mass (object / setting / scenery at rest) |
| Neighboring pixels change color **together** | A moving mass (object / motion) |
| Neighboring pixels change color **independently** | Noise / flicker; form does not hold |
| The whole frame / window is many such masses | Scenery, settings, and objects — including ones already in the registries, and newly named discoveries |

**Dynamicity** is this process with respect to time. A **window** (~1 second) is not a catalog of motion types. It is how synchronized (or unsynchronized) color changes accumulate over those frames.

---

## 3. Frames vs windows (loop)

| Focus | Generation | What grows |
|-------|------------|------------|
| **Frame** (explorer) | Pixels hold their pairing. Spatial masses can still form. Sync is high; color change is ~0. | Pure / static (`static_colors`) plus whatever objects/settings the still field already resembles. |
| **Window** (balanced) | Pixels **are allowed to change color**. How locked those changes are (sync) decides whether masses move as objects or dissolve into flicker. | Blended / dynamic motion from that color-change; semantic settings and entities from emerged masses. |

Sound stays on its **own spectrum** (static instants vs rematching windows). This document is the **color / pixel** spectrum.

---

## 4. What the loop must not treat as the primitive

These can still exist as **named readings** after the field has done the work, or when a prompt actually names a subject:

- Camera pan / zoom / handheld (moving the grid instead of changing pixel colors)
- Premade object layers (tree, person, car) as the default clip
- Keyword motion catalogs (`wave`, `pulse`, `fast`) as the generator switch

For **pairing clips** (the default loop): the renderer changes pixel colors; it does not pan the field. Named-subject prompts (`a person walking in a forest`) still use the object path. The **cartoon loop** (`LOOP_WORKFLOW_TYPE=cartoon`) is that named-subject path with cel grade and hold-then-snap timing — it does not replace pairing as the Core 4 default.

---

## 5. Code that must obey this

| Step | Where | Rule |
|------|--------|------|
| Spec | `src/creation/builder.py` | Pairing frames: hold colors (`motion_level` low, `motion_sync` = 1). Pairing windows: allow color change (`motion_level` high) and set `motion_sync` from smoothness. Camera stays `static` / `locked`. |
| Render | `src/procedural/renderer.py` `_render_pure_per_frame` | Each pixel pairs independently. Time changes those pairings. `motion_sync` blends **shared** (region) drift vs **independent** (per-pixel) drift. No camera catalog motion on this path. |
| Emerge | `src/knowledge/pixel_emergence.py` | After render, masses of pairings (and their change over a window) are matched to registered settings/entities or newly named. |
| Extract | `extractor_per_instance.py` | Measured motion is still frame-to-frame color difference — the same primitive, observed rather than authored. |

`motion_sync`: **0** = each pixel’s color changes on its own (flicker). **1** = pixels in a mass change together (object / motion).
