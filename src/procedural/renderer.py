"""
Procedural frame renderer: spec + time → pixels. Our algorithms only — no external model.
Supports gradients, camera motion, shot types, lighting presets.
"""
from typing import TYPE_CHECKING

import numpy as np

from .data.palettes import PALETTES
from .motion import get_camera_params, get_motion_func
from .parser import SceneSpec

if TYPE_CHECKING:
    pass

try:
    from ..cinematography.shot_types import get_shot_params
except ImportError:
    def get_shot_params(_: str):
        return 1.0, 0.1, 0.0

try:
    from ..lighting.grading import apply_lighting_preset
except ImportError:
    def apply_lighting_preset(fr: "np.ndarray", _: str):
        return fr


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
    *,
    directionality: str = "none",
    smoothness: str = "smooth",
) -> "np.ndarray":
    """Compute 0-1 gradient value per pixel based on gradient type + directionality."""
    from .motion import directionality_offsets

    dx, dy = directionality_offsets(directionality, motion_val, smoothness=smoothness)
    # When directionality is set, bias axes; else keep classic motion_val shift
    mx = motion_val * 0.3 + dx
    my = motion_val * 0.3 + dy
    if directionality == "radial" or gradient_type == "radial":
        cx, cy = 0.5, 0.5
        dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) * 1.414
        v = (dist + mx) % 1.0
    elif directionality == "horizontal" or gradient_type == "horizontal":
        v = (xx + mx) % 1.0
    elif directionality == "vertical" or gradient_type == "vertical":
        v = (yy + my) % 1.0
    elif directionality == "diagonal" or gradient_type == "angled":
        v = (xx * 0.7 + yy * 0.7 + mx) % 1.0
    elif gradient_type == "angled":
        v = (xx * 0.7 + yy * 0.7 + motion_val * 0.3) % 1.0
    elif gradient_type == "horizontal":
        v = (xx + motion_val * 0.3) % 1.0
    elif gradient_type == "vertical":
        v = (yy + motion_val * 0.3) % 1.0
    else:
        v = (yy + my) % 1.0
    return np.clip(v, 0, 1)


def _render_pure_per_frame(
    xx: "np.ndarray",
    yy: "np.ndarray",
    pure_colors: list[tuple[int, int, int]],
    t: float,
    seed: int,
    intensity: float,
) -> tuple["np.ndarray", "np.ndarray", "np.ndarray"]:
    """
    Pure-per-frame creation (§7): pure values from the registry at random pixel locations.

    Within each frame, placement is by pixel (x, y) only; time is not a dimension inside
    a single frame. Each pixel gets a pure color chosen by a deterministic hash of (x, y)
    and optionally frame time t so that across frames the pattern varies (temporal
    variation matters only in windows of multiple frames for extraction).
    """
    n_colors = len(pure_colors)
    if n_colors == 0:
        raise ValueError("pure_colors must be non-empty for pure_per_frame")
    # Deterministic per-pixel index: hash of position + time + seed
    h = (
        np.floor(xx * 997.0).astype(np.int64)
        + np.floor(yy * 997.0).astype(np.int64) * 1000
        + int(t * 200.0) * 1000000
        + seed * 100000000
    )
    idx = np.mod(np.abs(h), n_colors)
    R_arr = np.array([c[0] for c in pure_colors], dtype=np.float32)
    G_arr = np.array([c[1] for c in pure_colors], dtype=np.float32)
    B_arr = np.array([c[2] for c in pure_colors], dtype=np.float32)
    r = R_arr[idx]
    g = G_arr[idx]
    b = B_arr[idx]
    # Light noise so extraction still sees local variation (emergent blends)
    n = np.sin(xx * 12.9898 + yy * 78.233 + (seed + t * 100) * 43758.5453) * 43758.5453
    n = n - np.floor(n)
    amp = 12 * intensity
    r = np.clip(r + (n - 0.5) * amp, 0, 255)
    g = np.clip(g + (n - 0.5) * amp, 0, 255)
    b = np.clip(b + (n - 0.5) * amp, 0, 255)
    return r, g, b


def _composite_scene_layers(
    frame: "np.ndarray",
    layers: list[dict],
    t: float,
    width: int,
    height: int,
) -> "np.ndarray":
    """Composite keyframed stylized layers onto an RGB float frame."""
    from ..creation.scene_graph import sample_layer_at

    out = frame.astype(np.float32)
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    xx = xx / max(1, width - 1)
    yy = yy / max(1, height - 1)

    sorted_layers = sorted(layers, key=lambda L: int(L.get("z", 1) if isinstance(L, dict) else 1))
    for layer in sorted_layers:
        if not isinstance(layer, dict):
            continue
        pose = sample_layer_at(layer, t)
        kind = pose.get("kind") or layer.get("kind") or "circle"
        cx, cy = float(pose["x"]), float(pose["y"])
        scale = max(0.15, float(pose["scale"]))
        opacity = max(0.0, min(1.0, float(pose["opacity"]))) * 0.85
        color = layer.get("color") or [220, 60, 60]
        cr, cg, cb = float(color[0]), float(color[1]), float(color[2])
        radius = 0.12 * scale

        if kind == "rect":
            half = radius * 1.1
            mask = ((np.abs(xx - cx) < half) & (np.abs(yy - cy) < half)).astype(np.float32)
            # Soft edge
            edge = np.clip(1.0 - np.maximum(np.abs(xx - cx) / half, np.abs(yy - cy) / half), 0, 1)
            alpha = (mask * edge * opacity)[..., None]
        elif kind == "arrow":
            # Simple chevron pointing along +x (or -x if moving left historically)
            dx = xx - cx
            dy = yy - cy
            body = (np.abs(dy) < radius * 0.25) & (dx > -radius) & (dx < radius * 0.4)
            head = (dx > radius * 0.2) & (dx < radius) & (np.abs(dy) < (radius - dx) * 0.9)
            mask = (body | head).astype(np.float32)
            alpha = (mask * opacity)[..., None]
        elif kind == "character":
            # Head + body (two circles/rects)
            head_r = radius * 0.45
            body_r = radius * 0.7
            head_m = (np.sqrt((xx - cx) ** 2 + (yy - (cy - radius * 0.55)) ** 2) < head_r).astype(np.float32)
            body_m = ((np.abs(xx - cx) < body_r * 0.55) & (np.abs(yy - (cy + radius * 0.15)) < body_r)).astype(np.float32)
            mask = np.clip(head_m + body_m, 0, 1)
            alpha = (mask * opacity)[..., None]
        else:
            # circle
            dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
            mask = np.clip(1.0 - dist / max(1e-6, radius), 0, 1) ** 1.5
            alpha = (mask * opacity)[..., None]

        color_arr = np.array([cr, cg, cb], dtype=np.float32).reshape(1, 1, 3)
        out = out * (1.0 - alpha) + color_arr * alpha

    return np.clip(out, 0, 255)


def render_frame(
    spec: SceneSpec,
    t: float,
    width: int,
    height: int,
    *,
    seed: int = 0,
    duration_seconds: float | None = None,
) -> "np.ndarray":
    """
    Generate one RGB frame (H, W, 3) uint8 from our procedural algorithms.
    Supports vertical, radial, angled, horizontal gradients and camera motion (zoom, pan, rotate).
    When creation_mode is pure_per_frame, uses randomly placed pure colors (§7) for emergent blends.
    """
    creation_mode = getattr(spec, "creation_mode", "blended") or "blended"
    pure_colors = getattr(spec, "pure_colors", None) or []

    palette = getattr(spec, "palette_colors", None)
    if not palette:
        palette = PALETTES.get(spec.palette_name, PALETTES["default"])
    motion_fn = get_motion_func(spec.motion_type)
    motion_val = motion_fn(t)
    directionality = getattr(spec, "motion_directionality", "none") or "none"
    smoothness = getattr(spec, "motion_smoothness", "smooth") or "smooth"
    intensity = max(0.1, min(1.0, spec.intensity))
    # Phase 5: tension curve modulates intensity when duration known
    if duration_seconds and duration_seconds > 0:
        try:
            from ..narrative.story import get_tension_at
            t_norm = min(1.0, t / duration_seconds)
            tension = get_tension_at(t_norm)
            intensity = intensity * (0.7 + 0.3 * tension)
            intensity = max(0.1, min(1.0, intensity))
        except ImportError:
            pass
    gradient_type = getattr(spec, "gradient_type", "vertical") or "vertical"
    camera_motion = getattr(spec, "camera_motion", "static") or "static"

    # Grid of coordinates 0..1
    y = np.linspace(0, 1, height, dtype=np.float32)
    x = np.linspace(0, 1, width, dtype=np.float32)
    xx, yy = np.meshgrid(x, y)

    # Shot type affects base zoom
    shot_type = getattr(spec, "shot_type", "medium") or "medium"
    shot_zoom, _, handheld = get_shot_params(shot_type)
    zoom, pan_x, pan_y, rotate = get_camera_params(camera_motion, t)
    zoom = zoom * shot_zoom
    if handheld > 0:
        shake = np.sin(t * 23.7) * handheld * 0.02
        pan_x += shake
        pan_y += np.sin(t * 17.3) * handheld * 0.02
    xx, yy = _apply_camera_transform(xx, yy, zoom, pan_x, pan_y, rotate)

    if creation_mode == "pure_per_frame" and pure_colors:
        r, g, b = _render_pure_per_frame(xx, yy, pure_colors, t, seed, intensity)
    else:
        # Compute gradient value per pixel (blended mode)
        v = _gradient_value(
            xx, yy, gradient_type, motion_val,
            directionality=directionality,
            smoothness=smoothness,
        )
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

    # Shape overlay (soft circle or rect) — legacy single overlay
    shape_overlay = getattr(spec, "shape_overlay", "none") or "none"
    overlay_palette = pure_colors if (creation_mode == "pure_per_frame" and pure_colors) else palette
    scene_layers = getattr(spec, "scene_layers", None) or []
    if scene_layers:
        frame = np.stack([r, g, b], axis=-1).astype(np.float32)
        frame = _composite_scene_layers(frame, scene_layers, t, width, height)
        r, g, b = frame[:, :, 0], frame[:, :, 1], frame[:, :, 2]
    elif shape_overlay in ("circle", "rect") and overlay_palette:
        mid = len(overlay_palette) // 2
        cr, cg, cb = overlay_palette[mid][0], overlay_palette[mid][1], overlay_palette[mid][2]
        cx, cy = 0.5, 0.5
        # Drift overlay with directionality
        from .motion import directionality_offsets
        odx, ody = directionality_offsets(directionality, motion_val, smoothness=smoothness)
        cx = (cx + odx) % 1.0
        cy = (cy + ody) % 1.0
        if shape_overlay == "circle":
            dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) * 2
            alpha = np.clip(1 - dist, 0, 1) ** 2 * 0.15
        else:
            edge = 0.25
            mx = np.maximum(np.abs(xx - cx) - (0.5 - edge), 0)
            my = np.maximum(np.abs(yy - cy) - (0.5 - edge), 0)
            dist = np.sqrt(mx * mx + my * my) * 4
            alpha = np.clip(1 - dist, 0, 1) ** 2 * 0.2
        r = np.clip(r * (1 - alpha) + cr * alpha, 0, 255)
        g = np.clip(g * (1 - alpha) + cg * alpha, 0, 255)
        b = np.clip(b * (1 - alpha) + cb * alpha, 0, 255)

    frame = np.stack([r, g, b], axis=-1).astype(np.uint8)

    # Lighting / color grading (Phase 3)
    lighting_preset = getattr(spec, "lighting_preset", "neutral") or "neutral"
    frame = apply_lighting_preset(frame, lighting_preset)

    # Text overlay (Phase 4)
    text_overlay = getattr(spec, "text_overlay", None)
    if text_overlay:
        try:
            from ..graphics.text import render_text_overlay
            text_pos = getattr(spec, "text_position", "center") or "center"
            frame = render_text_overlay(
                frame, text_overlay, position=text_pos, font_size=44
            )
        except ImportError:
            pass

    # Depth parallax (Phase 7) - after text so base is fully composed
    depth_parallax = getattr(spec, "depth_parallax", False)
    if depth_parallax:
        try:
            from ..depth.parallax import apply_parallax
            frame = apply_parallax(frame, t, depth_layers=3, motion_scale=0.05)
        except ImportError:
            pass

    return frame
