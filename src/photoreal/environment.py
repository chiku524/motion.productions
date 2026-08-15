"""
Photoreal environment plate — sky hemisphere, ground plane, setting texture,
and a directional key from the lighting model.

Composited under subjects using the depth map so named registry colors become
the world, not only a post haze.
"""
from __future__ import annotations

from typing import Any

from ..procedural.parser import SceneSpec


def _luma(rgb: tuple[int, int, int]) -> float:
    return 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]


def _bind(spec: SceneSpec) -> dict[str, Any]:
    inst = getattr(spec, "instance", None) or {}
    bind = inst.get("photoreal_bind") if isinstance(inst, dict) else None
    return bind if isinstance(bind, dict) else {}


def _sky_ground(spec: SceneSpec) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    bind = _bind(spec)
    sky = bind.get("sky")
    ground = bind.get("ground")
    if isinstance(sky, (list, tuple)) and len(sky) >= 3 and isinstance(ground, (list, tuple)) and len(ground) >= 3:
        return (int(sky[0]), int(sky[1]), int(sky[2])), (int(ground[0]), int(ground[1]), int(ground[2]))
    palette = list(bind.get("palette") or getattr(spec, "palette_colors", None) or [])
    rgbs = [tuple(int(c) for c in rgb[:3]) for rgb in palette if rgb and len(rgb) >= 3]
    if rgbs:
        return max(rgbs, key=_luma), min(rgbs, key=_luma)
    return (176, 196, 214), (72, 78, 64)


def render_environment_plate(
    width: int,
    height: int,
    spec: SceneSpec,
    *,
    seed: int = 0,
) -> "np.ndarray":  # noqa: F821
    """
    Full-frame sky + ground from bound registry colors.

    Top is a zenith-to-horizon sky; bottom is a textured ground plane.
    Key light from upper-left (same convention as spatial layer lighting).
    """
    import numpy as np

    from ..depth.assets import get_asset_texture, texture_for_setting
    from ..lighting.grading import get_lighting_model

    bind = _bind(spec)
    sky_rgb, ground_rgb = _sky_ground(spec)
    inst = getattr(spec, "instance", None) or {}
    horizon = float(inst.get("horizon") or 0.62)
    horizon = min(0.82, max(0.38, horizon))

    y = np.linspace(0.0, 1.0, height, dtype=np.float32)
    x = np.linspace(0.0, 1.0, width, dtype=np.float32)
    yy = np.broadcast_to(y[:, None], (height, width))
    xx = np.broadcast_to(x[None, :], (height, width))

    sky_w = np.clip((horizon - yy) / max(0.12, horizon), 0.0, 1.0) ** 1.15
    ground_w = np.clip((yy - horizon) / max(0.12, 1.0 - horizon), 0.0, 1.0) ** 1.25
    haze_w = np.clip(1.0 - sky_w - ground_w, 0.0, 1.0)

    sky = np.array(sky_rgb, dtype=np.float32).reshape(1, 1, 3)
    ground = np.array(ground_rgb, dtype=np.float32).reshape(1, 1, 3)
    # Zenith is a bit darker/cooler than the horizon glow
    zenith = sky * np.array([0.72, 0.78, 0.92], dtype=np.float32)
    sky_grad = zenith * (1.0 - sky_w[..., None]) + sky * sky_w[..., None]
    # Perspective: ground nearer the camera is darker
    ground_grad = ground * (0.55 + 0.45 * ground_w[..., None])

    plate = sky_grad * sky_w[..., None] + ground_grad * ground_w[..., None]
    plate = plate + sky * 0.35 * haze_w[..., None]

    setting = bind.get("setting") or getattr(spec, "setting", None)
    tex_name = bind.get("texture") or texture_for_setting(setting)
    if tex_name:
        tex = get_asset_texture(str(tex_name), width, height, seed=seed + 17)
        if tex is not None:
            tex_f = tex.astype(np.float32) / 255.0
            # Texture lives on the ground; faint grain in the sky
            plate = plate * (1.0 - 0.28 * ground_w[..., None]) + (plate * (0.55 + 0.45 * tex_f)) * (
                0.28 * ground_w[..., None]
            )
            plate = plate * (1.0 - 0.06 * sky_w[..., None]) + (plate * (0.92 + 0.08 * tex_f)) * (
                0.06 * sky_w[..., None]
            )

    lighting = (bind.get("lighting") or getattr(spec, "lighting_preset", None) or "neutral")
    key, fill, _rim, ambient = get_lighting_model(str(lighting))
    kx, ky = -0.55, -0.72
    # Fake world normal: sky faces up, ground faces up-toward-camera
    nx = (xx - 0.5) * 0.35
    ny = np.where(yy < horizon, -0.85, 0.55)
    ndot = np.clip(-(nx * kx + ny * ky), 0.0, 1.0)
    light = np.clip(float(ambient) * 0.65 + float(key) * ndot + float(fill) * 0.25, 0.35, 1.75)
    plate = plate * light[..., None]
    return np.clip(plate, 0, 255).astype(np.uint8)


def composite_environment(
    frame: "np.ndarray",  # noqa: F821
    env: "np.ndarray",  # noqa: F821
    spec: SceneSpec,
    *,
    t: float = 0.0,
) -> "np.ndarray":  # noqa: F821
    """
    Replace backdrop (no stamped layer) with the environment plate.
    Subjects keep the rendered pixels.
    """
    import numpy as np

    from ..procedural.film import estimate_depth_map

    h, w = frame.shape[:2]
    yy = np.linspace(0.0, 1.0, h, dtype=np.float32)
    yy = np.broadcast_to(yy[:, None], (h, w))
    base_depth = 0.25 + 0.55 * yy
    depth = estimate_depth_map(
        h,
        w,
        scene_layers=getattr(spec, "scene_layers", None),
        t=t,
        composition_balance=getattr(spec, "composition_balance", "balanced") or "balanced",
    )
    layer_presence = np.clip((depth - base_depth) / 0.18, 0.0, 1.0)
    weight = (1.0 - layer_presence) * 0.62
    if weight.ndim == 2:
        weight = weight[..., None]
    out = frame.astype(np.float32) * (1.0 - weight) + env.astype(np.float32) * weight
    return np.clip(out, 0, 255).astype(np.uint8)
