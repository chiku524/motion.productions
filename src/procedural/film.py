"""
Film camera post-process: depth-of-field, grain, motion smear (Tier E).

Keeps the procedural engine NumPy-only; effects are opt-in via SceneSpec.film_look
(or auto when style=realistic / depth_parallax).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

# Grain amplitude (fraction of 255) by lighting preset
_GRAIN_BY_PRESET: dict[str, float] = {
    "neutral": 0.025,
    "documentary": 0.035,
    "noir": 0.07,
    "moody": 0.055,
    "golden_hour": 0.03,
    "neon": 0.02,
}


def box_blur(frame: "np.ndarray", radius: int = 2) -> "np.ndarray":
    """Separable box blur on HxWxC uint8 or float (cumsum windows)."""
    import numpy as np

    r = int(radius)
    if r < 1:
        return frame
    f = frame.astype(np.float32)
    # Horizontal
    pad = np.pad(f, ((0, 0), (r, r), (0, 0)), mode="edge")
    c = np.cumsum(pad, axis=1)
    z = np.zeros((f.shape[0], 1, f.shape[2]), dtype=np.float32)
    c = np.concatenate([z, c], axis=1)
    horiz = (c[:, 2 * r + 1 :] - c[:, : f.shape[1]]) / float(2 * r + 1)
    # Vertical
    pad = np.pad(horiz, ((r, r), (0, 0), (0, 0)), mode="edge")
    c = np.cumsum(pad, axis=0)
    z = np.zeros((1, horiz.shape[1], horiz.shape[2]), dtype=np.float32)
    c = np.concatenate([z, c], axis=0)
    out = (c[2 * r + 1 :, :, :] - c[: horiz.shape[0], :, :]) / float(2 * r + 1)
    if frame.dtype == np.uint8:
        return np.clip(out, 0, 255).astype(np.uint8)
    return out


def estimate_depth_map(
    height: int,
    width: int,
    *,
    scene_layers: list[dict] | None = None,
    t: float = 0.0,
    composition_balance: str = "balanced",
) -> "np.ndarray":
    """
    Approximate depth map 0 (far) … 1 (near) from sky/ground + layer z.
    Used for DoF; not a true z-buffer.
    """
    import numpy as np
    from ..creation.scene_graph import composition_balance_offset, sample_layer_at

    y = np.linspace(0, 1, height, dtype=np.float32)
    yy = np.broadcast_to(y[:, None], (height, width))
    # Top of frame = farther (sky), bottom = nearer (ground)
    depth = 0.25 + 0.55 * yy
    if not scene_layers:
        return depth
    dx, dy = composition_balance_offset(composition_balance)
    for layer in scene_layers:
        if not isinstance(layer, dict):
            continue
        pose = sample_layer_at(layer, t)
        cx = max(0.02, min(0.98, float(pose["x"]) + dx))
        cy = max(0.02, min(0.98, float(pose["y"]) + dy))
        scale = max(0.15, float(pose["scale"]))
        radius = 0.14 * scale
        z = int(layer.get("z", 1))
        # Higher z → nearer
        layer_depth = 0.35 + 0.2 * min(3, max(0, z)) / 3.0 + 0.15 * cy
        xs = np.linspace(0, 1, width, dtype=np.float32)
        xx = np.broadcast_to(xs[None, :], (height, width))
        dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
        stamp = np.clip(1.0 - dist / max(1e-6, radius * 1.4), 0, 1) ** 1.2
        depth = np.maximum(depth, layer_depth * stamp + depth * (1.0 - stamp))
    return np.clip(depth, 0.0, 1.0)


def apply_depth_of_field(
    frame: "np.ndarray",
    depth_map: "np.ndarray",
    *,
    focus: float = 0.55,
    blur_radius: int = 2,
    strength: float = 1.4,
) -> "np.ndarray":
    """Blend sharp and blurred frames by circle-of-confusion from |depth - focus|."""
    import numpy as np

    blurred = box_blur(frame, radius=blur_radius)
    coc = np.clip(np.abs(depth_map - focus) * strength, 0.0, 1.0)
    if coc.ndim == 2:
        coc = coc[..., None]
    out = frame.astype(np.float32) * (1.0 - coc) + blurred.astype(np.float32) * coc
    if frame.dtype == np.uint8:
        return np.clip(out, 0, 255).astype(np.uint8)
    return out


def apply_film_grain(
    frame: "np.ndarray",
    lighting_preset: str,
    *,
    seed: int = 0,
    t: float = 0.0,
) -> "np.ndarray":
    """Additive film grain; stronger for noir/moody."""
    import numpy as np

    preset = (lighting_preset or "neutral").lower().replace(" ", "_")
    amount = _GRAIN_BY_PRESET.get(preset, 0.03)
    rng = np.random.default_rng(abs(int(seed + t * 1000)) % (2**31))
    noise = rng.normal(0.0, amount * 255.0, size=frame.shape).astype(np.float32)
    out = frame.astype(np.float32) + noise
    return np.clip(out, 0, 255).astype(np.uint8)


def apply_motion_smear(
    frame: "np.ndarray",
    *,
    pan_dx: float,
    pan_dy: float,
    strength: float = 0.55,
) -> "np.ndarray":
    """
    Cheap directional smear from camera pan deltas (normalized UV units).
    Blends the frame with 1–2 horizontally/vertically shifted copies.
    """
    import numpy as np
    from ..depth.parallax import horizontal_shift

    mag = float(np.hypot(pan_dx, pan_dy))
    if mag < 1e-4 or strength <= 0:
        return frame
    # Scale smear to a few pixels of shift
    shift_x = float(np.clip(pan_dx * strength * 2.5, -0.04, 0.04))
    # Vertical: reuse horizontal_shift on transposed if needed
    out = frame.astype(np.float32)
    shifted = horizontal_shift(out, shift_x)
    if abs(pan_dy) > 1e-5:
        # Approximate vertical smear via row roll
        h = out.shape[0]
        pixels = int(np.clip(pan_dy * strength * h * 2.5, -h // 8, h // 8))
        if pixels != 0:
            shifted = np.roll(shifted, pixels, axis=0)
    blend = min(0.45, 0.15 + mag * 3.0)
    out = out * (1.0 - blend) + shifted * blend
    return np.clip(out, 0, 255).astype(np.uint8)


def apply_film_look(
    frame: "np.ndarray",
    *,
    lighting_preset: str,
    seed: int = 0,
    t: float = 0.0,
    depth_map: "np.ndarray | None" = None,
    focus: float = 0.55,
    pan_dx: float = 0.0,
    pan_dy: float = 0.0,
    enable_dof: bool = True,
    enable_grain: bool = True,
    enable_smear: bool = True,
) -> "np.ndarray":
    """Apply Tier E film stack in order: smear → DoF → grain."""
    out = frame
    if enable_smear:
        out = apply_motion_smear(out, pan_dx=pan_dx, pan_dy=pan_dy)
    if enable_dof and depth_map is not None:
        out = apply_depth_of_field(out, depth_map, focus=focus, blur_radius=2, strength=1.35)
    if enable_grain:
        out = apply_film_grain(out, lighting_preset, seed=seed, t=t)
    return out
