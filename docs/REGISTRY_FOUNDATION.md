# Registry foundation — four registries, 100% precise & accurate

This document is the **authoritative foundation** for all registries. Everything recorded and computed must align with it. Algorithms and functions are **100% precise**; what we record is **100% accurate**.

---

## 1. The four registries

| Registry | Role | Source | What it holds |
|----------|------|--------|----------------|
| **Pure** (Static) | Pure elements only — single frame, single pixel or single sample. | Single frames (extraction). | **Primitives/origins** (the starting set) + **pure blends** (each with a **name** and **depth_breakdown**). No element that uses time or multi-pixel connection. |
| **Blended** (Dynamic / Temporal) | Non-pure blends that use **time** (multiple frames) and/or **distance** (e.g. gradient = many colored pixels connected in one frame). | Windows (multiple frames) or single-frame blends (e.g. gradient). | **Categories** (e.g. role, mood, tempo, gradient_type, motion_type) that **elements** fit into. **Elements** are named blended values with **depth_breakdown**. Kick, snare, bass, melody, etc. are **already-known blends** (elements), not single pure elements. |
| **Semantic** (Narrative) | Same idea as Blended: documents **blends** that fit **categories** (plot, setting, dialogue, genre, mood, theme) and use time and/or distance. | Spec + prompt. | **Categories** (plot, setting, dialogue, …) and **elements** (named entries with **depth_breakdown** where applicable). |
| **Interpretation** | Human input resolved into structured elements. The program is always dealing with the **unknown** until the user successfully sends input/prompt; this registry is how we prepare for **everything and anything**. | User prompts → interpretation pipeline. | Resolved interpretations: prompt → instruction (palette, motion, gradient, camera, mood, etc.). Each has a canonical form and can be referenced by name. |

**Naming:** In code we use `static`, `dynamic`, `narrative` for compatibility. The second registry is often called "temporal" or "dynamic" but conceptually it is **Blended** (time and/or distance). The fourth is `interpretation` (table `interpretations`). Docs and APIs can use Pure / Blended / Semantic / Interpretation where helpful.

---

## 2. Pure registry (Static) — rules

- **Only pure elements.** One frame → one pixel (color) or one sample (sound). Adding opacity to an RGB produces a **pure blend** (still pure); each such blend gets a **name** and is stored as one entry.
- **Color:** Primitives = origin colors (black, white, red, green, blue, …). Every **color at each level of opaqueness** that appears is a pure blend with **name** and **depth_breakdown** (origin color % + opacity).
- **Sound — critical distinction:**
  - **Measurements** (not the names of pure elements): **silent**, **low**, **mid**, **high** are measurements (e.g. frequency band, level). They are used for computation and **depth_breakdown**, not as the names of the actual sound primitives.
  - **Actual sound noises** are the pure elements: e.g. **silence**, and the named noise types that correspond to bands (e.g. rumble, tone, hiss). Each discovered sound noise gets a **name**; when a noise has different levels of strength, we record the **strength percentage** (0–100% or 0–1) as well. So: **name** = the noise; **strength_pct** = measurement stored with the entry.
  - Kick, snare, clap, bass, melody, speech, etc. are **not** pure — they are **already-known blends** (Blended registry). Only truly pure sound noises (silence + single-band noise types) live in Pure.
- **Depth breakdown (required for every non-primitive):** Origin percentages (e.g. origin colors, origin noise types) and, where applicable, opacity or strength_pct.

---

## 3. Blended registry (Dynamic / Temporal) — rules

- **Categories vs elements:** The registry holds **categories** (e.g. role, mood, tempo, gradient_type, motion_type) that **elements** fit into. The **categories are not elements**. The **elements** are the actual blended values that get a **name** and **depth_breakdown** (what the blend consists of).
- **Non-pure blends:** Use **time** (frames) and/or **distance** (e.g. gradient = pixels connected in one frame). Motion, gradient, camera, spec-derived sound (kick, snare, bass, ambient, etc.) are **elements** in this registry.
- Every **element** has a **name** (not just a key) and **depth_breakdown**. Keys are for deduplication; names are for display and reference.

---

## 4. Semantic registry (Narrative) — rules

- **Same as Blended:** Documents **blends** that fit **categories** (plot, setting, dialogue, genre, mood, theme, scene type) and use **time** and/or **distance**. Each entry is a named **element** with **depth_breakdown** where applicable. Categories (plot, setting, dialogue, …) are not elements; the named entries are.

---

## 5. Interpretation registry — rules

- The program/software is always dealing with the **unknown** until the user successfully sends their input/prompt. The **Interpretation registry** is how we prepare for **everything and anything**: it stores resolved interpretations (prompt → instruction) so we can reuse and learn from human input. Entries can be referenced by name and carry the resolved structure.

---

## 6. Name generator — requirement

- **100% semantic or name-like.** No gibberish. The generator must produce names that are **semantic and have meaning** (e.g. real-word-like, place-name style). Algorithms and functions used in the generator must be **precise** so it can assign such semantic names to the many elements that have yet to be discovered.
- Used for: Pure blends (color, sound), Blended elements, Semantic entries, and optionally Interpretation labels.

---

## 7. Frame vs time/distance — precise distinction

- **Pure:** Elements from **singular frames** (one frame → one pixel/sample or one pure blend).
- **Blended & Semantic:** Elements from **windows** (multiple frames) or **connection over distance** (e.g. gradient in one frame). These are **non-pure blends**.

---

## 8. Summary table

| Registry       | Source              | Primitives / categories     | Elements / entries |
|----------------|---------------------|-----------------------------|--------------------|
| **Pure**       | Single frame        | Origin colors; silence + actual sound noises | Named pure blends; **depth_breakdown**; sound entries include **strength_pct**. |
| **Blended**    | Windows / single-frame blends | Categories (role, mood, tempo, gradient_type, motion_type, …) | Named **elements** with **depth_breakdown**. |
| **Semantic**   | Spec + prompt       | Categories (plot, setting, dialogue, …) | Named **elements** with **depth_breakdown** where applicable. |
| **Interpretation** | User prompts   | —                           | Resolved instruction + optional name; references other registries. |

---

## 9. Implementation checklist

- [x] Pure: depth_breakdown required for every non-primitive; origin % and opacity/strength_pct.
- [x] Pure: color+opacity as named pure blends.
- [x] Pure: sound = **actual sound noises** (named); **low/mid/high** = measurements; **strength_pct** recorded; kick/snare/etc. in Blended only.
- [x] Blended: **categories** vs **elements**; every element has **name** + **depth_breakdown**.
- [x] Semantic (Narrative): same (categories vs elements; name + depth where applicable).
- [x] Name generator: semantic/meaningful only; precise algorithms for undiscovered elements.
- [x] Interpretation: program deals with unknown until user input; registry prepares for everything.

See also: [REGISTRIES.md](REGISTRIES.md), [MP4_ASPECTS.md](MP4_ASPECTS.md), [NAME_GENERATOR.md](NAME_GENERATOR.md).
