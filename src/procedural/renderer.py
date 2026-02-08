"""
Procedural frame renderer: spec + time → pixels. Our algorithms only — no external model.
Supports multiple gradient types (vertical, radial, angled, horizontal) and camera motion.
"""
from typing import TYPE_CHECKING

import numpy as np

from .data.palettes import PALETTES
from .motion import get_camera_params, get_motion_func
from .parser import SceneSpec

if TYPE_CHECKING:
    pass


def _apply_camera_transform(
    xx: "np.ndarray", yy: "np.ndarray", zoom: float, pan_x: float, pan_y: float, rotate: float
) -> tuple["np.ndarray", "np.ndarray"]:
    """Transform normalized coords (0-1) by zoom, pan, rotate around center."""
    cx, cy = 0.5, 0.5
    x_centered = xx - cx
    y_centered = yy - cy
    if abs(rotate) > 1e-9:
        c, s = np.cos(rotate), np.sin(rotate)
        x_rot = x_centered * c - y_centered * s
        y_rot = x_centered * s + y_centered * c
        x_centered, y_centered = x_rot, y_rot
    x_scaled = x_centered / zoom + cx + pan_x
    y_scaled = y_centered / zoom + cy + pan_y
    return x_scaled, y_scaled


def _gradient_value(
    xx: "np.ndarray",
    yy: "np.ndarray",
    gradient_type: str,
    motion_val: float,
) -> "np.ndarray":
    """Compute 0-1 gradient value per pixel based on gradient type."""
    if gradient_type == "vertical":
        v = (yy + motion_val * 0.3) % 1.0
    elif gradient_type == "horizontal":
        v = (xx + motion_val * 0.3) % 1.0
    elif gradient_type == "angled":
        v = (xx * 0.7 + yy * 0.7 + motion_val * 0.3) % 1.0
    elif gradient_type == "radial":
        cx, cy = 0.5, 0.5
        dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) * 1.414  # normalize to ~0-1
        v = (dist + motion_val * 0.3) % 1.0
    else:
        v = (yy + motion_val * 0.3) % 1.0
    return np.clip(v, 0, 1)


def render_frame(
    spec: SceneSpec,
    t: float,
    width: int,
    height: int,
    *,
    seed: int = 0,
) -> "np.ndarray":
    """
    Generate one RGB frame (H, W, 3) uint8 from our procedural algorithms.
    Supports vertical, radial, angled, horizontal gradients and camera motion (zoom, pan, rotate).
    """
    palette = PALETTES.get(spec.palette_name, PALETTES["default"])
    motion_fn = get_motion_func(spec.motion_type)
    motion_val = motion_fn(t)
    intensity = max(0.1, min(1.0, spec.intensity))
    gradient_type = getattr(spec, "gradient_type", "vertical") or "vertical"
    camera_motion = getattr(spec, "camera_motion", "static") or "static"

    # Grid of coordinates 0..1
    y = np.linspace(0, 1, height, dtype=np.float32)
    x = np.linspace(0, 1, width, dtype=np.float32)
    xx, yy = np.meshgrid(x, y)

    # Apply camera motion
    zoom, pan_x, pan_y, rotate = get_camera_params(camera_motion, t)
    xx, yy = _apply_camera_transform(xx, yy, zoom, pan_x, pan_y, rotate)

    # Compute gradient value per pixel
    v = _gradient_value(xx, yy, gradient_type, motion_val)
    idx = v * (len(palette) - 1)
    i0 = np.clip(np.floor(idx).astype(np.int32), 0, len(palette) - 2)
    i1 = i0 + 1
    frac = idx - i0

    r0 = np.array([palette[i][0] for i in i0.flat]).reshape(i0.shape)
    g0 = np.array([palette[i][1] for i in i0.flat]).reshape(i0.shape)
    b0 = np.array([palette[i][2] for i in i0.flat]).reshape(i0.shape)
    r1 = np.array([palette[i][0] for i in i1.flat]).reshape(i1.shape)
    g1 = np.array([palette[i][1] for i in i1.flat]).reshape(i1.shape)
    b1 = np.array([palette[i][2] for i in i1.flat]).reshape(i1.shape)

    r = r0 * (1 - frac) + r1 * frac
    g = g0 * (1 - frac) + g1 * frac
    b = b0 * (1 - frac) + b1 * frac

    # Add noise texture (our algorithm — vectorized)
    n = np.sin(xx * 12.9898 + yy * 78.233 + (seed + t * 100) * 43758.5453) * 43758.5453
    n = n - np.floor(n)
    amp = 20 * intensity
    r = np.clip(r + (n - 0.5) * amp, 0, 255)
    g = np.clip(g + (n - 0.5) * amp, 0, 255)
    b = np.clip(b + (n - 0.5) * amp, 0, 255)

    # Shape overlay (soft circle or rect)
    shape_overlay = getattr(spec, "shape_overlay", "none") or "none"
    if shape_overlay in ("circle", "rect") and palette:
        mid = len(palette) // 2
        cr, cg, cb = palette[mid][0], palette[mid][1], palette[mid][2]
        cx, cy = 0.5, 0.5
        if shape_overlay == "circle":
            dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) * 2
            alpha = np.clip(1 - dist, 0, 1) ** 2 * 0.15
        else:
            edge = 0.25
            mx = np.maximum(np.abs(xx - 0.5) - (0.5 - edge), 0)
            my = np.maximum(np.abs(yy - 0.5) - (0.5 - edge), 0)
            dist = np.sqrt(mx * mx + my * my) * 4
            alpha = np.clip(1 - dist, 0, 1) ** 2 * 0.2
        r = np.clip(r * (1 - alpha) + cr * alpha, 0, 255)
        g = np.clip(g * (1 - alpha) + cg * alpha, 0, 255)
        b = np.clip(b * (1 - alpha) + cb * alpha, 0, 255)

    frame = np.stack([r, g, b], axis=-1).astype(np.uint8)
    return frame
