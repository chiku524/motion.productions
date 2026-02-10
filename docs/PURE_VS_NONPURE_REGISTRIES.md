# Pure vs non-pure registries and depth

Measurements are **down to the pixel**. This doc defines how we classify values and how **depth %** compares discoveries to primitives.

---

## Pure → STATIC registry

**Pure** = single frame, single pixel (or single sample). One frame cannot output gradient or motion as a single pixel; a single pixel at one time has one color value.

- **Static registry** holds **pure** discoveries: per-frame color (dominant RGB per frame), per-frame sound.
- **Pure primitives** (origin values) for depth comparison: e.g. black, white, red, green, blue (RGB). Used to compute depth for static colors — e.g. grey = 50% white + 50% black.

---

## Non-pure → DYNAMIC + NARRATIVE registries

**Non-pure** = multi-frame blends. When multiple frames are present, the same pixel has different values over time; combining those frames forms a blend at that pixel (dynamic).

- **Gradient, motion, camera** are **non-pure**: they require multiple frames to observe (one frame cannot define a gradient or motion at a single pixel).
- These are **canonical non-pure** options (origin gradient types, camera motions, motion types). They live in the **dynamic** conceptual space; discoveries are stored in learned_blends / dynamic registries.
- **Narrative** (genre, mood, themes, etc.) is also non-pure in the sense of being composite; it goes in the **narrative** registry.

So we do **not** call gradient/camera/motion “primitives” in the same sense as static color primitives. They are **canonical non-pure** values used for creation and for depth comparison in the dynamic registry.

---

## Depth % — always compare to primitives

- **Depth %** compares each **discovered** value to the **origin (primitive or canonical)** values.
- Example: **grey = 50% white + 50% black** → depth_breakdown: `{ white: 50, black: 50 }`; depth_pct can summarize (e.g. max contribution or blend strength).
- For **static colors**: depth is computed vs pure color primaries (e.g. black/white luminance split, or palette means).
- For **dynamic blends** (gradient, camera, motion, etc.): depth comes from `primitive_depths` (how much each canonical value contributed) and is always returned in the registries API with `depth_pct` and `depth_breakdown`.

The registries UI and `GET /api/registries` always include depth % (and depth_breakdown where available) so every discovery is expressed relative to the origin values.
