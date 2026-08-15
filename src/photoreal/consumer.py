"""
Photoreal consumer — bind a SceneSpec to named registry values, then grade.

Loops grow the dictionaries. This module is the other half: when a prompt
asks for a real scene, creation resorts to those named colors / lighting /
setting values instead of leaving photoreal as a film-stack alias.
"""
from __future__ import annotations

from typing import Any

from ..procedural.parser import SceneSpec


def _rgb_from_entry(entry: Any) -> tuple[int, int, int] | None:
    if isinstance(entry, (list, tuple)) and len(entry) >= 3:
        try:
            return (int(entry[0]), int(entry[1]), int(entry[2]))
        except (TypeError, ValueError):
            return None
    if not isinstance(entry, dict):
        return None
    try:
        r, g, b = entry.get("r"), entry.get("g"), entry.get("b")
        if r is None or g is None or b is None:
            return None
        return (int(r), int(g), int(b))
    except (TypeError, ValueError):
        return None


def _luma(rgb: tuple[int, int, int]) -> float:
    return 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]


def catalog_from_knowledge(knowledge: dict[str, Any] | None, *, limit: int = 64) -> list[tuple[int, int, int]]:
    """Named static colors the photoreal path may resort to."""
    knowledge = knowledge or {}
    seen: set[tuple[int, int, int]] = set()
    out: list[tuple[int, int, int]] = []

    def _add(entry: Any) -> None:
        rgb = _rgb_from_entry(entry)
        if rgb is None or rgb in seen:
            return
        seen.add(rgb)
        out.append(rgb)

    static = knowledge.get("static_colors") or {}
    if isinstance(static, dict):
        for entry in static.values():
            _add(entry)
    elif isinstance(static, list):
        for entry in static:
            _add(entry)

    by_name = knowledge.get("color_by_name") or {}
    if isinstance(by_name, dict):
        for entry in by_name.values():
            _add(entry)

    learned = knowledge.get("learned_colors") or {}
    if isinstance(learned, dict):
        for entry in learned.values():
            if isinstance(entry, dict) and "mean_rgb" in entry:
                _add(entry.get("mean_rgb"))
            else:
                _add(entry)

    return out[: max(1, int(limit))]


def nearest_registry_color(
    rgb: tuple[int, int, int] | list[int],
    catalog: list[tuple[int, int, int]],
) -> tuple[int, int, int]:
    """Snap a working color onto the nearest named registry RGB."""
    if not catalog:
        return (int(rgb[0]), int(rgb[1]), int(rgb[2]))
    r, g, b = int(rgb[0]), int(rgb[1]), int(rgb[2])
    best = catalog[0]
    best_d = 1e18
    for cr, cg, cb in catalog:
        d = (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2
        if d < best_d:
            best_d = d
            best = (int(cr), int(cg), int(cb))
    return best


def bind_spec_to_registries(
    spec: SceneSpec,
    knowledge: dict[str, Any] | None = None,
) -> SceneSpec:
    """
    Resort palette (and bind metadata) to named registry colors.

    Mutates spec in place and returns it. Pairing / cel clips should not call this —
    they stay on the pixel-field primitive.
    """
    catalog = catalog_from_knowledge(knowledge)
    existing = [tuple(int(c) for c in rgb[:3]) for rgb in (getattr(spec, "palette_colors", None) or []) if rgb]
    if existing and catalog:
        bound = [nearest_registry_color(c, catalog) for c in existing]
    elif catalog:
        bound = catalog[: max(3, min(6, len(catalog)))]
    else:
        bound = existing

    if bound:
        spec.palette_colors = bound

    inst = dict(getattr(spec, "instance", None) or {})
    inst["photoreal_bind"] = {
        "palette": bound,
        "lighting": getattr(spec, "lighting_preset", None),
        "setting": getattr(spec, "setting", None),
        "bound": bool(catalog),
        "catalog_size": len(catalog),
    }
    spec.instance = inst
    if getattr(spec, "render_engine", "procedural") != "cel":
        spec.film_look = True
        spec.depth_parallax = True
        spec.render_engine = "photoreal"
    return spec


def apply_photoreal_grade(
    frame: "np.ndarray",  # noqa: F821
    spec: SceneSpec,
    *,
    t: float = 0.0,
) -> "np.ndarray":  # noqa: F821
    """Atmosphere + exposure using bound registry colors as sky / fill."""
    import numpy as np

    from ..procedural.film import (
        apply_atmospheric_haze,
        apply_soft_bloom,
        apply_tone_curve,
        estimate_depth_map,
    )

    inst = getattr(spec, "instance", None) or {}
    bind = inst.get("photoreal_bind") if isinstance(inst, dict) else None
    palette = []
    if isinstance(bind, dict):
        palette = list(bind.get("palette") or [])
    if not palette:
        palette = list(getattr(spec, "palette_colors", None) or [])
    rgbs = [tuple(int(c) for c in rgb[:3]) for rgb in palette if rgb and len(rgb) >= 3]

    if rgbs:
        sky = max(rgbs, key=_luma)
        fill = sorted(rgbs, key=_luma)[len(rgbs) // 2]
    else:
        sky = (176, 196, 214)
        fill = (118, 124, 132)

    h, w = frame.shape[:2]
    depth = estimate_depth_map(
        h,
        w,
        scene_layers=getattr(spec, "scene_layers", None),
        t=t,
        composition_balance=getattr(spec, "composition_balance", "balanced") or "balanced",
    )
    lighting = (getattr(spec, "lighting_preset", None) or "neutral").lower().replace(" ", "_")
    haze_strength = 0.28 if lighting in ("golden_hour", "documentary") else 0.22
    if lighting in ("noir", "moody"):
        haze_strength = 0.14

    out = apply_atmospheric_haze(
        frame,
        depth,
        haze_rgb=(float(sky[0]), float(sky[1]), float(sky[2])),
        strength=haze_strength,
    )
    # Bounce fill from a mid registry color so shadows aren't a dead procedural gray
    bounce = np.array(fill, dtype=np.float32).reshape(1, 1, 3)
    far = np.clip(1.0 - depth, 0.0, 1.0)[..., None]
    out = out.astype(np.float32) * (1.0 - 0.08 * far) + bounce * (0.08 * far)
    out = np.clip(out, 0, 255).astype(np.uint8)
    out = apply_tone_curve(out, contrast=1.10, lift=0.025)
    if lighting in ("golden_hour", "neon"):
        out = apply_soft_bloom(out, threshold=190.0, strength=0.22, radius=2)
    return out
