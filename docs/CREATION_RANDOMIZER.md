# Creation randomizer — registry-first for gradient / motion / camera

When interpretation leaves **gradient**, **motion**, or **camera** at their defaults (no keyword matched), creation picks **from the STATIC/learned registry first** so growth is prioritised and pure elements can blend across frames; only when the registry is empty do we fall back to origin primitives. No seed is used; choices use Python’s `random` (unseeded).

**Location:** `src/creation/builder.py` — inside `build_spec_from_instruction()`, after blending from instruction/knowledge.

---

## 1. Gradient (default only) — registry-first

- **Source:** `knowledge["learned_gradient"]` (from API `GET /api/knowledge/for-creation`; populated by growth from spec, domain `gradient` in `learned_blends`).
- **When default:** Filter to renderer-valid values (`vertical`, `horizontal`, `radial`, `angled`); if the filtered list is non-empty, `random.choice(pool)`; else `random.choice(origin primitives)` from `GRAPHICS_ORIGINS["gradient_type"]`.

So gradient is **picked from the registry** (values discovered in previous runs) when available, then truly random from origin primitives.

---

## 2. Motion (default only) — registry-first

- **Source:** `knowledge["learned_motion"]` (from API; `learned_motion` table).
- **When default:** `_random_motion_from_registry(knowledge)` picks one entry at random and maps to a valid motion type (`slow`, `wave`, `flow`, `fast`, `pulse`); if empty or mapping fails, `random.choice(_MOTION_OPTIONS)`.

Motion is **random from the registry** when available, else random from the five motion options.

---

## 3. Camera (default only) — registry-first

- **Source:** `knowledge["learned_camera"]` (from API for-creation; built from `learned_blends` where `domain = 'camera'`).
- **When default:** Filter to renderer-supported values (`static`, `zoom`, `zoom_out`, `pan`, `rotate`, `dolly`, `crane`); if the filtered list is non-empty, `random.choice(pool)`; else `random.choice(tuple(_CAMERA_VALID))`.

Camera is **picked from the registry** (values recorded from spec in growth) when available, then random from the supported set.

---

## Growth feeding the registry

- **Gradient and camera:** Each run’s spec is sent to the API in `grow_and_sync_to_api(spec=spec)`. The Worker stores a blend with `domain: "gradient"` (output `gradient_type`) and `domain: "camera"` (output `camera_motion`). For-creation returns distinct values from those blends as `learned_gradient` and `learned_camera`.
- **Motion:** Already grown into `learned_motion` (per-run extraction + API). Creation uses it as above.

So **motion and every other non-pure blend** go through the growth phase:

- **Static (per-frame):** `grow_from_video()` — color, sound; pure elements.
- **Dynamic (per-window, non-pure):** `grow_dynamic_from_video()` — motion, time, lighting, composition, graphics, temporal, technical, audio_semantic; multi-frame values. Novel entries get a name and are added to the dynamic registry. When randomly selected in creation, these can combine across frames (e.g. in 1s windows) and form **new non-pure blends** (e.g. sunset + sunrise → new style).
- **Narrative:** `grow_narrative_from_spec()` — genre, mood, themes, plots, settings, scene_type.

Short videos (e.g. 1 second) give multiple frames that merge into non-pure blends; growth records them so later creation can pick from the registry.
