"""
Procedural frame renderer: spec + time → pixels. Our algorithms only — no external model.
Supports gradients, camera motion, shot types, lighting presets.
"""
from typing import TYPE_CHECKING

import numpy as np

from .data.palettes import PALETTES
from .motion import get_camera_params, get_motion_func, rhythm_modulation, steadiness_shake
from .parser import SceneSpec

if TYPE_CHECKING:
    pass

try:
    from ..cinematography.shot_types import get_shot_params
except ImportError:
    def get_shot_params(_: str):
        return 1.0, 0.1, 0.0

try:
    from ..lighting.grading import (
        apply_color_temperature,
        apply_lighting_preset,
        apply_spatial_layer_lighting,
        apply_style_look,
        get_lighting_model,
    )
except ImportError:
    def apply_lighting_preset(fr: "np.ndarray", _: str):
        return fr

    def apply_color_temperature(fr: "np.ndarray", _: str):
        return fr

    def apply_style_look(fr: "np.ndarray", _: str):
        return fr

    def get_lighting_model(_: str):
        return (1.0, 0.5, 0.2, 0.3)

    def apply_spatial_layer_lighting(color_rgb, mask, xx, yy, cx, cy, radius, lighting_model):
        cr, cg, cb = float(color_rgb[0]), float(color_rgb[1]), float(color_rgb[2])
        ones = np.ones_like(mask, dtype=np.float32)
        return np.stack([cr * ones, cg * ones, cb * ones], axis=-1)


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


def _apply_weather_overlay(
    frame: "np.ndarray",
    setting: str,
    t: float,
    *,
    seed: int = 0,
) -> "np.ndarray":
    """Rain streaks or snow flakes for weather settings (NumPy only)."""
    s = (setting or "").strip().lower()
    if s not in ("rain", "snow"):
        return frame
    h, w = frame.shape[:2]
    out = frame.astype(np.float32)
    rng = np.random.default_rng(abs(int(seed + t * 1000)) % (2**31))
    if s == "rain":
        n = max(40, (h * w) // 900)
        for _ in range(n):
            x = int(rng.integers(0, w))
            y0 = int((rng.random() * 1.2 + (t * 2.5) % 1.0) * h) % h
            length = int(rng.integers(6, 14))
            thickness = 1 if rng.random() < 0.7 else 2
            y1 = min(h, y0 + length)
            alpha = 0.35 + 0.25 * float(rng.random())
            x1 = min(w, x + thickness)
            out[y0:y1, x:x1, :] = out[y0:y1, x:x1, :] * (1 - alpha) + 200.0 * alpha
        # Slight wet ground darken
        yy = np.linspace(0, 1, h, dtype=np.float32)[:, None]
        wet = np.clip((yy - 0.7) / 0.3, 0, 1)
        out = out * (1.0 - 0.12 * wet[..., None])
    else:  # snow
        n = max(50, (h * w) // 700)
        for _ in range(n):
            x = int((rng.random() + 0.15 * float(np.sin(t * 0.8 + rng.random()))) * w) % w
            y = int((rng.random() * 1.1 + (t * 0.35) % 1.0) * h) % h
            r = int(rng.integers(1, 3))
            y0, y1 = max(0, y - r), min(h, y + r + 1)
            x0, x1 = max(0, x - r), min(w, x + r + 1)
            out[y0:y1, x0:x1, :] = np.clip(out[y0:y1, x0:x1, :] * 0.55 + 240.0 * 0.45, 0, 255)
    return np.clip(out, 0, 255).astype(np.uint8)


def _apply_setting_backdrop(
    r: "np.ndarray",
    g: "np.ndarray",
    b: "np.ndarray",
    yy: "np.ndarray",
    setting: str,
    intensity: float,
) -> tuple["np.ndarray", "np.ndarray", "np.ndarray"]:
    """
    Soft horizon / ground / sky bands for setting-themed mini-scene backgrounds.
    Keeps the look procedural and primitive so settings remain discoverable.
    """
    s = (setting or "").strip().lower()
    amp = 0.22 * max(0.3, min(1.0, intensity))
    ground = np.clip((yy - 0.62) / 0.38, 0, 1) ** 1.4
    sky = np.clip((0.38 - yy) / 0.38, 0, 1) ** 1.2
    # (ground_rgb_delta, sky_rgb_delta)
    deltas: dict[str, tuple[tuple[float, float, float], tuple[float, float, float]]] = {
        "city": ((18, 8, 28), (-10, -5, 35)),
        "neon": ((25, 0, 40), (-5, 20, 45)),
        "ocean": ((-15, 10, 35), (-20, 25, 50)),
        "beach": ((40, 28, 8), (20, 35, 55)),
        "underwater": ((-30, 15, 40), (-40, 20, 55)),
        "forest": ((-10, 35, -5), (-15, 20, 10)),
        "night": ((-25, -20, -5), (-35, -25, 15)),
        "noir": ((-30, -30, -25), (-40, -35, -20)),
        "golden_hour": ((45, 22, -5), (50, 30, 5)),
        "day": ((15, 18, 5), (10, 25, 45)),
        "desert": ((50, 30, 5), (35, 40, 20)),
        "mountain": ((10, 15, 20), (5, 20, 40)),
        "space": ((-40, -35, -10), (-50, -40, 20)),
        "studio": ((8, 8, 10), (12, 12, 15)),
        "interior": ((12, 8, 5), (5, 5, 8)),
        "exterior": ((15, 20, 8), (8, 22, 40)),
        "rain": ((-20, -5, 15), (-25, 5, 25)),
        "snow": ((35, 38, 42), (20, 30, 45)),
        "street": ((15, 10, 20), (-5, 5, 30)),
        "park": ((-5, 30, -8), (5, 25, 35)),
        "moody": ((-15, -10, 5), (-25, -15, 20)),
        "abstract": ((20, -10, 35), (10, 15, 40)),
    }
    ground_d, sky_d = deltas.get(s, ((10, 10, 10), (8, 12, 20)))
    r = np.clip(r + ground * (ground_d[0] * amp) + sky * (sky_d[0] * amp), 0, 255)
    g = np.clip(g + ground * (ground_d[1] * amp) + sky * (sky_d[1] * amp), 0, 255)
    b = np.clip(b + ground * (ground_d[2] * amp) + sky * (sky_d[2] * amp), 0, 255)
    return r, g, b


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

def _sample_texture_mod(
    texture: "np.ndarray | None",
    xx: "np.ndarray",
    yy: "np.ndarray",
) -> "np.ndarray | None":
    """Sample HxWx3 uint8 texture at normalized xx,yy → HxW float 0-1 luminance mod."""
    if texture is None:
        return None
    h, w = texture.shape[:2]
    xi = np.clip((xx * (w - 1)).astype(np.int32), 0, w - 1)
    yi = np.clip((yy * (h - 1)).astype(np.int32), 0, h - 1)
    tex = texture[yi, xi].astype(np.float32) / 255.0
    return 0.299 * tex[:, :, 0] + 0.587 * tex[:, :, 1] + 0.114 * tex[:, :, 2]


def _soft_disk(
    xx: "np.ndarray",
    yy: "np.ndarray",
    cx: float,
    cy: float,
    radius: float,
    soft: float = 0.03,
) -> "np.ndarray":
    """Anti-aliased disk mask (1 inside, soft falloff over soft band)."""
    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    band = max(1e-5, float(soft))
    return np.clip((float(radius) + band - dist) / band, 0.0, 1.0)


def _soft_box(
    xx: "np.ndarray",
    yy: "np.ndarray",
    cx: float,
    cy: float,
    half_w: float,
    half_h: float,
    soft: float = 0.025,
) -> "np.ndarray":
    """Anti-aliased axis-aligned box via max-norm distance."""
    dx = np.abs(xx - cx) / max(1e-6, float(half_w))
    dy = np.abs(yy - cy) / max(1e-6, float(half_h))
    m = np.maximum(dx, dy)
    band = max(1e-5, float(soft) / max(min(half_w, half_h), 1e-6))
    return np.clip((1.0 + band - m) / band, 0.0, 1.0)


def _soft_ellipse(
    xx: "np.ndarray",
    yy: "np.ndarray",
    cx: float,
    cy: float,
    rx: float,
    ry: float,
    soft: float = 0.03,
) -> "np.ndarray":
    """Anti-aliased ellipse mask."""
    nx = (xx - cx) / max(1e-6, float(rx))
    ny = (yy - cy) / max(1e-6, float(ry))
    dist = np.sqrt(nx * nx + ny * ny)
    band = max(1e-5, float(soft) / max(min(rx, ry), 1e-6))
    return np.clip((1.0 + band - dist) / band, 0.0, 1.0)


def _blend_shaded_layer(
    out_rgb: "np.ndarray",
    out_a: "np.ndarray",
    mask: "np.ndarray",
    color_rgb: tuple[float, float, float],
    xx: "np.ndarray",
    yy: "np.ndarray",
    cx: float,
    cy: float,
    radius: float,
    lighting_model: tuple[float, float, float, float],
    texture_mod: "np.ndarray | None",
    opacity: float,
    *,
    material: str = "default",
) -> tuple["np.ndarray", "np.ndarray"]:
    """Porter-Duff over: shade flat color with spatial lights, optional texture, onto RGBA."""
    a = np.clip(mask * opacity, 0.0, 1.0)
    if float(np.max(a)) < 0.02:
        return out_rgb, out_a
    lit = apply_spatial_layer_lighting(color_rgb, a, xx, yy, cx, cy, radius, lighting_model)
    # Material-specific surface response (Tier C)
    mat = (material or "default").lower()
    tex_amp = 0.22
    if mat in ("tree", "forest"):
        tex_amp = 0.38  # leafy roughness
    elif mat in ("building", "city"):
        tex_amp = 0.28
    elif mat in ("cloud", "wave"):
        tex_amp = 0.12  # soft / glossy
    elif mat == "character":
        tex_amp = 0.10
    elif mat == "fish":
        tex_amp = 0.18
    if texture_mod is not None:
        lit = lit * (1.0 - tex_amp + tex_amp * (0.45 + 1.1 * texture_mod))[..., None]
    # Extra rim for volumetric-ish props (cloud/tree canopy)
    if mat in ("cloud", "tree", "character"):
        key, _fill, rim, _amb = lighting_model
        gy, gx = np.gradient(a)
        edge = np.clip(np.sqrt(gx * gx + gy * gy) * 5.0, 0.0, 1.0)
        rim_boost = (0.35 + 0.4 * float(rim)) * edge
        lit = lit + (40.0 * float(key) * rim_boost)[..., None]
        lit = np.clip(lit, 0, 255)
    # Key-light specular lobe (glossy materials catch more)
    key, _f, _r, _amb = lighting_model
    r = max(1e-6, float(radius))
    nx = (xx - cx) / r
    ny = (yy - cy) / r
    kx, ky = -0.55, -0.72
    ndot = np.clip(-(nx * kx + ny * ky), 0.0, 1.0)
    spec_pow = {
        "cloud": 26.0, "fish": 22.0, "character": 16.0,
        "building": 11.0, "wave": 20.0, "tree": 5.0, "forest": 5.0,
    }.get(mat, 9.0)
    spec_amp = {
        "cloud": 58.0, "fish": 48.0, "character": 32.0,
        "building": 22.0, "wave": 40.0, "tree": 10.0, "forest": 10.0,
    }.get(mat, 18.0)
    specular = (ndot ** spec_pow) * float(key) * spec_amp
    lit = lit + specular[..., None]
    lit = np.clip(lit, 0, 255)
    a3 = a[..., None]
    out_rgb = out_rgb * (1.0 - a3) + lit * a3
    out_a = out_a * (1.0 - a) + a
    return out_rgb, out_a


def _contact_shadow_mask(
    xx: "np.ndarray",
    yy: "np.ndarray",
    cx: float,
    cy: float,
    radius: float,
    lighting_model: tuple[float, float, float, float],
) -> "np.ndarray":
    """
    Soft elliptical contact shadow opposite the key light (Tier C).
    Key is upper-left → shadow falls down-right, grounded under the subject.
    """
    key, _f, _r, _a = lighting_model
    k = max(0.35, float(key))
    sx = cx + 0.045 * k
    sy = cy + radius * 0.65 + 0.025 * k
    rx = max(0.04, radius * 1.15)
    ry = max(0.02, radius * 0.38)
    d = ((xx - sx) / rx) ** 2 + ((yy - sy) / ry) ** 2
    return np.clip(1.0 - d, 0.0, 1.0) ** 1.8


def _accumulate_contact_shadows(
    layers: list[dict],
    t: float,
    width: int,
    height: int,
    *,
    composition_balance: str = "balanced",
    composition_symmetry: str = "slight",
    lighting_preset: str = "neutral",
) -> "np.ndarray":
    """HxW soft contact-shadow alpha to darken the background before layer over."""
    from ..creation.scene_graph import (
        apply_composition_symmetry_x,
        composition_balance_offset,
        sample_layer_at,
    )

    shadow = np.zeros((height, width), dtype=np.float32)
    if not layers:
        return shadow
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    xx = xx / max(1, width - 1)
    yy = yy / max(1, height - 1)
    dx, dy = composition_balance_offset(composition_balance)
    lighting_model = get_lighting_model(lighting_preset)
    for layer in layers:
        if not isinstance(layer, dict):
            continue
        kind = str(layer.get("kind") or "circle")
        if kind == "cloud":
            continue
        pose = sample_layer_at(layer, t)
        cx = max(0.02, min(0.98, float(pose["x"]) + dx))
        cx = apply_composition_symmetry_x(cx, composition_symmetry)
        cy = max(0.02, min(0.98, float(pose["y"]) + dy))
        scale = max(0.15, float(pose["scale"]))
        opacity = max(0.0, min(1.0, float(pose["opacity"]))) * 0.85
        if opacity < 0.02:
            continue
        radius = 0.12 * scale
        s = _contact_shadow_mask(xx, yy, cx, cy, radius, lighting_model)
        strength = 0.38 if kind in ("tree", "building", "character") else 0.28
        shadow = np.maximum(shadow, s * opacity * strength)
    return np.clip(shadow, 0.0, 1.0)


def _darken_with_shadows(frame: "np.ndarray", shadow_a: "np.ndarray") -> "np.ndarray":
    """Multiply-darken RGB float frame by soft contact shadows."""
    if shadow_a is None or float(np.max(shadow_a)) < 0.01:
        return frame
    factor = 1.0 - 0.55 * shadow_a
    return np.clip(frame * factor[..., None], 0, 255)


def _partition_layers_by_depth(layers: list[dict]) -> list[tuple[list[dict], float]]:
    """Group layers into back / mid / front planes with depth tags for parallax."""
    back: list[dict] = []
    mid: list[dict] = []
    front: list[dict] = []
    for layer in layers:
        if not isinstance(layer, dict):
            continue
        z = int(layer.get("z", 1))
        if z <= 0:
            back.append(layer)
        elif z >= 2:
            front.append(layer)
        else:
            mid.append(layer)
    return [(back, 0.28), (mid, 0.58), (front, 0.92)]


def _render_layers_rgba(
    layers: list[dict],
    t: float,
    width: int,
    height: int,
    *,
    composition_balance: str = "balanced",
    composition_symmetry: str = "slight",
    lighting_preset: str = "neutral",
    texture: "np.ndarray | None" = None,
) -> tuple["np.ndarray", "np.ndarray"]:
    """
    Render stylized layers onto a transparent canvas.
    Returns (rgb float 0-255 HxWx3, alpha float 0-1 HxW).
    Contact shadows are applied separately onto the background.
    """
    from ..creation.scene_graph import (
        apply_composition_symmetry_x,
        composition_balance_offset,
        sample_layer_at,
    )

    out_rgb = np.zeros((height, width, 3), dtype=np.float32)
    out_a = np.zeros((height, width), dtype=np.float32)
    if not layers:
        return out_rgb, out_a

    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    xx = xx / max(1, width - 1)
    yy = yy / max(1, height - 1)
    dx, dy = composition_balance_offset(composition_balance)
    lighting_model = get_lighting_model(lighting_preset)
    texture_mod = _sample_texture_mod(texture, xx, yy)

    sorted_layers = sorted(layers, key=lambda L: int(L.get("z", 1) if isinstance(L, dict) else 1))
    for layer in sorted_layers:
        if not isinstance(layer, dict):
            continue
        pose = sample_layer_at(layer, t)
        kind = pose.get("kind") or layer.get("kind") or "circle"
        cx = max(0.02, min(0.98, float(pose["x"]) + dx))
        cx = apply_composition_symmetry_x(cx, composition_symmetry)
        cy = max(0.02, min(0.98, float(pose["y"]) + dy))
        scale = max(0.15, float(pose["scale"]))
        opacity = max(0.0, min(1.0, float(pose["opacity"]))) * 0.85
        if opacity < 0.02:
            continue
        color = layer.get("color") or [220, 60, 60]
        cr, cg, cb = float(color[0]), float(color[1]), float(color[2])
        radius = 0.12 * scale
        rot = float(pose.get("rot") or 0.0)
        if abs(rot) > 1e-4:
            cos_r, sin_r = float(np.cos(rot)), float(np.sin(rot))
            dxr = xx - cx
            dyr = yy - cy
            xx_l = cx + dxr * cos_r - dyr * sin_r
            yy_l = cy + dxr * sin_r + dyr * cos_r
        else:
            xx_l, yy_l = xx, yy

        if kind == "rect":
            half = radius * 1.1
            mask = _soft_box(xx_l, yy_l, cx, cy, half, half, soft=0.03)
            out_rgb, out_a = _blend_shaded_layer(
                out_rgb, out_a, mask, (cr, cg, cb), xx_l, yy_l, cx, cy, radius,
                lighting_model, texture_mod, opacity, material=kind,
            )
        elif kind == "arrow":
            dxv = xx_l - cx
            dyv = yy_l - cy
            # Soft body via distance to horizontal strip
            body_m = np.clip(1.0 - np.abs(dyv) / max(1e-6, radius * 0.28), 0, 1)
            body_m = body_m * ((dxv > -radius) & (dxv < radius * 0.45)).astype(np.float32)
            head_m = (
                (dxv > radius * 0.15)
                & (dxv < radius)
                & (np.abs(dyv) < (radius - dxv) * 0.95 + 0.02)
            ).astype(np.float32)
            head_soft = head_m * np.clip(1.0 - np.abs(dyv) / max(1e-6, (radius - dxv) * 0.95 + 0.02), 0, 1)
            mask = np.clip(np.maximum(body_m, head_soft), 0, 1)
            out_rgb, out_a = _blend_shaded_layer(
                out_rgb, out_a, mask, (cr, cg, cb), xx_l, yy_l, cx, cy, radius,
                lighting_model, texture_mod, opacity, material=kind,
            )
        elif kind == "character":
            head_r = radius * 0.45
            body_r = radius * 0.7
            head_cy = cy - radius * 0.55
            head_m = _soft_disk(xx_l, yy_l, cx, head_cy, head_r, soft=0.025)
            body_m = _soft_box(xx_l, yy_l, cx, cy + radius * 0.15, body_r * 0.55, body_r, soft=0.03)
            mask = np.clip(np.maximum(head_m, body_m), 0, 1)
            # Inter-layer soft AO under this character onto existing draw
            if float(np.max(out_a)) > 0.05:
                ao = np.clip(np.roll(mask, max(1, int(0.018 * height)), axis=0) * 0.28, 0, 1)
                out_rgb = out_rgb * (1.0 - ao * (out_a > 0.08).astype(np.float32))[..., None]
            eye_y = head_cy - head_r * 0.15
            eye_dx = head_r * 0.35
            eye_r = head_r * 0.12
            gag = str(layer.get("gag") or "none").lower()
            wink = gag == "wink" and (int(t * 8) % 8 == 3)
            expression = str(layer.get("expression") or "neutral").lower()
            # Expression-tuned eye scale
            eye_scale = 1.0
            if expression in ("excited", "happy"):
                eye_scale = 1.2
            elif expression in ("sad", "nervous"):
                eye_scale = 0.85
            elif expression == "angry":
                eye_scale = 0.95
            left_eye_r = eye_r * eye_scale * (0.25 if wink else 1.0)
            right_eye_r = eye_r * eye_scale
            if expression == "angry":
                eye_y = eye_y + head_r * 0.04
            left_eye = _soft_disk(xx_l, yy_l, cx - eye_dx, eye_y, left_eye_r, soft=0.012)
            right_eye = _soft_disk(xx_l, yy_l, cx + eye_dx, eye_y, right_eye_r, soft=0.012)
            # Brows
            brow_y = eye_y - head_r * 0.22
            brow_h = head_r * 0.06
            if expression == "angry":
                # Slanted inward
                left_brow = (
                    (np.abs((yy_l - brow_y) - 0.45 * (xx_l - (cx - eye_dx))) < brow_h)
                    & (np.abs(xx_l - (cx - eye_dx)) < head_r * 0.22)
                ).astype(np.float32)
                right_brow = (
                    (np.abs((yy_l - brow_y) + 0.45 * (xx_l - (cx + eye_dx))) < brow_h)
                    & (np.abs(xx_l - (cx + eye_dx)) < head_r * 0.22)
                ).astype(np.float32)
            elif expression == "sad":
                left_brow = (
                    (np.abs((yy_l - brow_y) + 0.35 * (xx_l - (cx - eye_dx))) < brow_h)
                    & (np.abs(xx_l - (cx - eye_dx)) < head_r * 0.22)
                ).astype(np.float32)
                right_brow = (
                    (np.abs((yy_l - brow_y) - 0.35 * (xx_l - (cx + eye_dx))) < brow_h)
                    & (np.abs(xx_l - (cx + eye_dx)) < head_r * 0.22)
                ).astype(np.float32)
            else:
                left_brow = (
                    (np.abs(yy_l - brow_y) < brow_h)
                    & (np.abs(xx_l - (cx - eye_dx)) < head_r * 0.2)
                ).astype(np.float32)
                right_brow = (
                    (np.abs(yy_l - brow_y) < brow_h)
                    & (np.abs(xx_l - (cx + eye_dx)) < head_r * 0.2)
                ).astype(np.float32)
            brows = np.clip(left_brow + right_brow, 0, 1)
            mouth_y = head_cy + head_r * 0.35
            if expression == "happy":
                mouth = (
                    (np.abs(yy_l - (mouth_y - 0.01 * np.cos((xx_l - cx) / max(1e-6, head_r * 0.5) * 3.14))) < head_r * 0.08)
                    & (np.abs(xx_l - cx) < head_r * 0.45)
                    & (yy_l > mouth_y - head_r * 0.2)
                ).astype(np.float32)
            elif expression == "sad":
                mouth = (
                    (np.abs(yy_l - (mouth_y + 0.012 * np.cos((xx_l - cx) / max(1e-6, head_r * 0.5) * 3.14))) < head_r * 0.08)
                    & (np.abs(xx_l - cx) < head_r * 0.4)
                ).astype(np.float32)
            elif expression == "angry":
                mouth = ((np.abs(yy_l - mouth_y) < head_r * 0.06) & (np.abs(xx_l - cx) < head_r * 0.35)).astype(np.float32)
            elif expression == "excited":
                mouth = _soft_disk(xx_l, yy_l, cx, mouth_y + head_r * 0.02, head_r * 0.2, soft=0.015)
                mouth = mouth * (yy_l > mouth_y - head_r * 0.05).astype(np.float32)
            elif expression == "nervous":
                mouth = ((np.abs(yy_l - mouth_y) < head_r * 0.05) & (np.abs(xx_l - cx) < head_r * 0.2)).astype(np.float32)
            elif expression == "calm":
                mouth = ((np.abs(yy_l - mouth_y) < head_r * 0.05) & (np.abs(xx_l - cx) < head_r * 0.3)).astype(np.float32)
            else:
                mouth = ((np.abs(yy_l - mouth_y) < head_r * 0.05) & (np.abs(xx_l - cx) < head_r * 0.28)).astype(np.float32)
            blush = np.zeros_like(mask)
            if expression in ("happy", "excited"):
                blush = (
                    _soft_disk(xx_l, yy_l, cx - eye_dx * 1.15, mouth_y - head_r * 0.05, head_r * 0.14, soft=0.02)
                    + _soft_disk(xx_l, yy_l, cx + eye_dx * 1.15, mouth_y - head_r * 0.05, head_r * 0.14, soft=0.02)
                )
                blush = np.clip(blush, 0, 1)
            face = np.clip(left_eye + right_eye + mouth + brows, 0, 1)
            mask = np.clip(mask + face * 0.35, 0, 1)
            out_rgb, out_a = _blend_shaded_layer(
                out_rgb, out_a, mask, (cr, cg, cb), xx_l, yy_l, cx, cy, radius,
                lighting_model, texture_mod, opacity, material=kind,
            )
            if float(np.max(blush)) > 0.05:
                out_rgb, out_a = _blend_shaded_layer(
                    out_rgb, out_a, blush * opacity * 0.35, (255.0, 140.0, 150.0),
                    xx_l, yy_l, cx, cy, radius * 0.4, lighting_model, None, 1.0, material=kind,
                )
            feat_a = face * opacity * 0.55
            dark = (cr * 0.35, cg * 0.35, cb * 0.35)
            out_rgb, out_a = _blend_shaded_layer(
                out_rgb, out_a, feat_a, dark, xx_l, yy_l, cx, cy, radius * 0.5,
                lighting_model, None, 1.0, material=kind,
            )
        elif kind == "tree":
            trunk_w, trunk_h = radius * 0.22, radius * 0.85
            trunk = _soft_box(xx_l, yy_l, cx, cy + trunk_h * 0.15, trunk_w * 0.5, trunk_h * 0.55, soft=0.02)
            canopy_cy = cy - radius * 0.35
            canopy = _soft_disk(xx_l, yy_l, cx, canopy_cy, radius * 0.7, soft=0.04)
            # Second canopy lobe + leaf speckles
            canopy2 = _soft_disk(xx_l, yy_l, cx - radius * 0.25, canopy_cy + radius * 0.08, radius * 0.45, soft=0.035)
            canopy3 = _soft_disk(xx_l, yy_l, cx + radius * 0.22, canopy_cy + radius * 0.05, radius * 0.4, soft=0.035)
            canopy = np.clip(np.maximum(np.maximum(canopy, canopy2), canopy3), 0, 1)
            if texture_mod is not None:
                speck = (texture_mod > 0.62).astype(np.float32) * canopy * 0.35
                canopy = np.clip(canopy + speck, 0, 1)
            out_rgb, out_a = _blend_shaded_layer(
                out_rgb, out_a, canopy, (cr, cg, cb), xx_l, yy_l, cx, canopy_cy, radius * 0.7,
                lighting_model, texture_mod, opacity, material=kind,
            )
            out_rgb, out_a = _blend_shaded_layer(
                out_rgb, out_a, trunk, (90.0, 55.0, 30.0), xx_l, yy_l, cx, cy, radius * 0.4,
                lighting_model, texture_mod, opacity * 0.9, material=kind,
            )
        elif kind == "fish":
            body = _soft_ellipse(xx_l, yy_l, cx, cy, radius * 0.9, radius * 0.45, soft=0.03)
            tail_core = (
                (xx_l < cx - radius * 0.55)
                & (xx_l > cx - radius * 1.15)
                & (np.abs(yy_l - cy) < (cx - radius * 0.4 - xx_l) * 0.9 + 0.02)
            ).astype(np.float32)
            mask = np.clip(np.maximum(body, tail_core * 0.9), 0, 1)
            out_rgb, out_a = _blend_shaded_layer(
                out_rgb, out_a, mask, (cr, cg, cb), xx_l, yy_l, cx, cy, radius,
                lighting_model, texture_mod, opacity, material=kind,
            )
            eye = _soft_disk(xx_l, yy_l, cx + radius * 0.35, cy - radius * 0.08, radius * 0.1, soft=0.01)
            out_rgb, out_a = _blend_shaded_layer(
                out_rgb, out_a, eye, (20.0, 20.0, 30.0), xx_l, yy_l, cx, cy, radius * 0.2,
                lighting_model, None, opacity * 0.7, material=kind,
            )
        elif kind == "wave":
            band = np.abs(yy_l - (cy + 0.03 * np.sin(xx_l * 18.0 + t * 3.0))) < radius * 0.35
            fade = np.clip(1.0 - np.abs(xx_l - cx) / max(1e-6, radius * 2.2), 0, 1)
            mask = band.astype(np.float32) * fade
            out_rgb, out_a = _blend_shaded_layer(
                out_rgb, out_a, mask, (cr, cg, cb), xx_l, yy_l, cx, cy, radius,
                lighting_model, texture_mod, opacity * 0.75, material=kind,
            )
        elif kind == "building":
            half_w, half_h = radius * 0.55, radius * 1.2
            body = _soft_box(xx_l, yy_l, cx, cy, half_w, half_h, soft=0.025)
            wx = np.floor((xx_l - (cx - half_w)) / max(1e-6, half_w * 0.35))
            wy = np.floor((yy_l - (cy - half_h)) / max(1e-6, half_h * 0.22))
            windows = (
                (np.mod(wx, 2) == 0)
                & (np.mod(wy, 2) == 0)
                & (np.abs(xx_l - cx) < half_w * 0.85)
                & (np.abs(yy_l - cy) < half_h * 0.85)
            ).astype(np.float32)
            # Neon / night flicker: pulse window brightness with time
            flicker = 0.75 + 0.25 * float(np.sin(t * 4.7 + cx * 9.0))
            if (lighting_preset or "").lower() in ("neon", "noir", "moody"):
                flicker = 0.55 + 0.45 * (0.5 + 0.5 * float(np.sin(t * 7.3 + cx * 5.0)))
            win_color = (220.0 * flicker, 200.0 * flicker, 90.0 + 40.0 * flicker)
            out_rgb, out_a = _blend_shaded_layer(
                out_rgb, out_a, body, (cr, cg, cb), xx_l, yy_l, cx, cy, radius,
                lighting_model, texture_mod, opacity, material=kind,
            )
            out_rgb, out_a = _blend_shaded_layer(
                out_rgb, out_a, windows, win_color, xx_l, yy_l, cx, cy, radius * 0.5,
                lighting_model, None, opacity * 0.45, material=kind,
            )
        elif kind == "cloud":
            c1 = _soft_disk(xx_l, yy_l, cx - radius * 0.45, cy, radius * 0.55, soft=0.05)
            c2 = _soft_disk(xx_l, yy_l, cx, cy - radius * 0.15, radius * 0.65, soft=0.055)
            c3 = _soft_disk(xx_l, yy_l, cx + radius * 0.4, cy, radius * 0.5, soft=0.05)
            mask = np.clip(np.maximum(np.maximum(c1, c2), c3), 0, 1)
            out_rgb, out_a = _blend_shaded_layer(
                out_rgb, out_a, mask, (cr, cg, cb), xx_l, yy_l, cx, cy, radius,
                lighting_model, texture_mod, opacity * 0.7, material=kind,
            )
        else:
            dist = np.sqrt((xx_l - cx) ** 2 + (yy_l - cy) ** 2)
            mask = np.clip(1.0 - dist / max(1e-6, radius), 0, 1) ** 1.5
            out_rgb, out_a = _blend_shaded_layer(
                out_rgb, out_a, mask, (cr, cg, cb), xx_l, yy_l, cx, cy, radius,
                lighting_model, texture_mod, opacity, material=kind,
            )

    return np.clip(out_rgb, 0, 255), np.clip(out_a, 0, 1)


def _composite_scene_layers(
    frame: "np.ndarray",
    layers: list[dict],
    t: float,
    width: int,
    height: int,
    *,
    composition_balance: str = "balanced",
    composition_symmetry: str = "slight",
    lighting_preset: str = "neutral",
    texture: "np.ndarray | None" = None,
) -> "np.ndarray":
    """Composite keyframed stylized layers onto an RGB float frame (over)."""
    bg = frame.astype(np.float32)
    shadow_a = _accumulate_contact_shadows(
        layers, t, width, height,
        composition_balance=composition_balance,
        composition_symmetry=composition_symmetry,
        lighting_preset=lighting_preset,
    )
    bg = _darken_with_shadows(bg, shadow_a)
    fg_rgb, fg_a = _render_layers_rgba(
        layers, t, width, height,
        composition_balance=composition_balance,
        composition_symmetry=composition_symmetry,
        lighting_preset=lighting_preset,
        texture=texture,
    )
    a = fg_a[..., None]
    out = bg * (1.0 - a) + fg_rgb * a
    return np.clip(out, 0, 255)


def _apply_background_texture(
    r: "np.ndarray",
    g: "np.ndarray",
    b: "np.ndarray",
    xx: "np.ndarray",
    yy: "np.ndarray",
    texture: "np.ndarray | None",
    intensity: float,
) -> tuple["np.ndarray", "np.ndarray", "np.ndarray"]:
    """Soft-multiply procedural texture onto background RGB (camera-warped UVs)."""
    mod = _sample_texture_mod(texture, xx, yy)
    if mod is None:
        return r, g, b
    amp = 0.18 * max(0.3, min(1.0, intensity))
    factor = 1.0 - amp + amp * (0.55 + 0.9 * mod)
    return (
        np.clip(r * factor, 0, 255),
        np.clip(g * factor, 0, 255),
        np.clip(b * factor, 0, 255),
    )


def render_frame(
    spec: SceneSpec,
    t: float,
    width: int,
    height: int,
    *,
    seed: int = 0,
    duration_seconds: float | None = None,
    t_content: float | None = None,
) -> "np.ndarray":
    """
    Generate one RGB frame (H, W, 3) uint8 from our procedural algorithms.

    t: camera / motion clock (may be per-shot + paced).
    t_content: clip-global time for script_beats, entity keyframes, and tension.
    When t_content is None, t is used for both (single-shot / short clips).
    """
    t_motion = float(t)
    t_abs = float(t if t_content is None else t_content)
    creation_mode = getattr(spec, "creation_mode", "blended") or "blended"
    pure_colors = getattr(spec, "pure_colors", None) or []

    palette = getattr(spec, "palette_colors", None)
    if not palette:
        palette = PALETTES.get(spec.palette_name, PALETTES["default"])
    motion_fn = get_motion_func(spec.motion_type)
    motion_val = motion_fn(t_motion)
    directionality = getattr(spec, "motion_directionality", "none") or "none"
    smoothness = getattr(spec, "motion_smoothness", "smooth") or "smooth"
    intensity = max(0.1, min(1.0, spec.intensity))
    rhythm = getattr(spec, "motion_rhythm", "steady") or "steady"
    intensity = max(0.1, min(1.0, intensity * rhythm_modulation(rhythm, t_motion)))
    if duration_seconds and duration_seconds > 0:
        try:
            from ..narrative.story import get_tension_at
            t_norm = min(1.0, t_abs / duration_seconds)
            tension = get_tension_at(
                t_norm,
                curve=getattr(spec, "tension_curve", "standard") or "standard",
            )
            intensity = intensity * (0.7 + 0.3 * tension)
            intensity = max(0.1, min(1.0, intensity))
        except ImportError:
            pass
    gradient_type = getattr(spec, "gradient_type", "vertical") or "vertical"
    camera_motion = getattr(spec, "camera_motion", "static") or "static"
    lighting_preset = getattr(spec, "lighting_preset", "neutral") or "neutral"
    composition_balance = getattr(spec, "composition_balance", "balanced") or "balanced"
    composition_symmetry = getattr(spec, "composition_symmetry", "slight") or "slight"
    setting = getattr(spec, "setting", None)

    texture = None
    try:
        from ..depth.assets import get_asset_texture, texture_for_setting
        tex_name = texture_for_setting(setting)
        if tex_name:
            texture = get_asset_texture(tex_name, width, height, seed=seed)
    except ImportError:
        texture = None

    y = np.linspace(0, 1, height, dtype=np.float32)
    x = np.linspace(0, 1, width, dtype=np.float32)
    xx, yy = np.meshgrid(x, y)

    shot_type = getattr(spec, "shot_type", "medium") or "medium"
    shot_zoom, pan_range, handheld = get_shot_params(shot_type)
    zoom, pan_x, pan_y, rotate = get_camera_params(camera_motion, t_motion)
    # Shot pan_range scales camera pans (wide = more roam, close = locked)
    pan_scale = 0.5 + 5.0 * float(pan_range)
    pan_x *= pan_scale
    pan_y *= pan_scale
    sx, sy, srot = steadiness_shake(getattr(spec, "camera_steadiness", "stable") or "stable", t_motion)
    pan_x += sx
    pan_y += sy
    rotate += srot
    zoom = zoom * shot_zoom
    if handheld > 0:
        shake = np.sin(t_motion * 23.7) * handheld * 0.02
        pan_x += shake
        pan_y += np.sin(t_motion * 17.3) * handheld * 0.02
    xx, yy = _apply_camera_transform(xx, yy, zoom, pan_x, pan_y, rotate)

    if creation_mode == "pure_per_frame" and pure_colors:
        r, g, b = _render_pure_per_frame(xx, yy, pure_colors, t_abs, seed, intensity)
    else:
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

        n = np.sin(xx * 12.9898 + yy * 78.233 + (seed + t_abs * 100) * 43758.5453) * 43758.5453
        n = n - np.floor(n)
        amp = 20 * intensity
        r = np.clip(r + (n - 0.5) * amp, 0, 255)
        g = np.clip(g + (n - 0.5) * amp, 0, 255)
        b = np.clip(b + (n - 0.5) * amp, 0, 255)

        if setting:
            r, g, b = _apply_setting_backdrop(r, g, b, yy, str(setting), intensity)

    r, g, b = _apply_background_texture(r, g, b, xx, yy, texture, intensity)
    background = np.stack([r, g, b], axis=-1).astype(np.float32)

    shape_overlay = getattr(spec, "shape_overlay", "none") or "none"
    overlay_palette = pure_colors if (creation_mode == "pure_per_frame" and pure_colors) else palette
    scene_layers = getattr(spec, "scene_layers", None) or []
    # Apply active-beat expression onto character layers (timed faces)
    beat_expression = None
    depth_parallax = bool(getattr(spec, "depth_parallax", False))
    film_look = bool(getattr(spec, "film_look", False))
    render_engine = (getattr(spec, "render_engine", None) or "procedural").lower()
    if render_engine in ("enhanced", "photoreal", "realistic"):
        film_look = True
        depth_parallax = True

    script_beats_early = getattr(spec, "script_beats", None)
    if script_beats_early:
        try:
            from ..creation.narrative_script import resolve_overlay_at_time
            ov = resolve_overlay_at_time(script_beats_early, t_abs)
            beat_expression = ov.get("expression")
        except ImportError:
            pass
    if beat_expression and scene_layers:
        scene_layers = [
            ({**L, "expression": beat_expression} if isinstance(L, dict) and L.get("kind") == "character" else L)
            for L in scene_layers
        ]

    if scene_layers and depth_parallax:
        from ..depth.parallax import composite_depth_planes
        from ..depth.layers import create_depth_layers

        mid = palette[len(palette) // 2] if palette else (120, 130, 140)
        base_rgb = (int(mid[0]), int(mid[1]), int(mid[2]))
        # Contact shadows on the far background before depth planes
        background = _darken_with_shadows(
            background,
            _accumulate_contact_shadows(
                scene_layers, t_abs, width, height,
                composition_balance=composition_balance,
                composition_symmetry=composition_symmetry,
                lighting_preset=lighting_preset,
            ),
        )
        planes: list[tuple[np.ndarray, np.ndarray, float]] = []
        for img, depth in create_depth_layers(
            width, height, num_layers=2, seed=seed, base_rgb=base_rgb, setting=setting,
        ):
            haze_a = np.full((height, width), 0.10 * (1.15 - float(depth)), dtype=np.float32)
            planes.append((img.astype(np.float32), haze_a, float(depth) * 0.35))
        for group, depth in _partition_layers_by_depth(scene_layers):
            if not group:
                continue
            fg_rgb, fg_a = _render_layers_rgba(
                group, t_abs, width, height,
                composition_balance=composition_balance,
                composition_symmetry=composition_symmetry,
                lighting_preset=lighting_preset,
                texture=texture,
            )
            planes.append((fg_rgb, fg_a, depth))
        frame = composite_depth_planes(
            background, planes, t_motion,
            motion_scale=0.06,
            camera_pan_x=float(pan_x),
            camera_pan_y=float(pan_y),
        )
    elif scene_layers:
        frame = _composite_scene_layers(
            background, scene_layers, t_abs, width, height,
            composition_balance=composition_balance,
            composition_symmetry=composition_symmetry,
            lighting_preset=lighting_preset,
            texture=texture,
        )
    elif shape_overlay in ("circle", "rect") and overlay_palette:
        frame = background.copy()
        mid_i = len(overlay_palette) // 2
        cr = float(overlay_palette[mid_i][0])
        cg = float(overlay_palette[mid_i][1])
        cb = float(overlay_palette[mid_i][2])
        cx, cy = 0.5, 0.5
        from .motion import directionality_offsets
        from ..creation.scene_graph import composition_balance_offset
        odx, ody = directionality_offsets(directionality, motion_val, smoothness=smoothness)
        cdx, cdy = composition_balance_offset(composition_balance)
        cx = (cx + odx + cdx) % 1.0
        cy = (cy + ody + cdy) % 1.0
        if shape_overlay == "circle":
            dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) * 2
            alpha = np.clip(1 - dist, 0, 1) ** 2 * 0.15
        else:
            edge = 0.25
            mx = np.maximum(np.abs(xx - cx) - (0.5 - edge), 0)
            my = np.maximum(np.abs(yy - cy) - (0.5 - edge), 0)
            dist = np.sqrt(mx * mx + my * my) * 4
            alpha = np.clip(1 - dist, 0, 1) ** 2 * 0.2
        lit = apply_spatial_layer_lighting(
            (cr, cg, cb), alpha, xx, yy, cx, cy, 0.25, get_lighting_model(lighting_preset),
        )
        a3 = alpha[..., None]
        frame = frame * (1.0 - a3) + lit * a3
    else:
        frame = background

    frame = np.clip(frame, 0, 255).astype(np.uint8)
    frame = apply_lighting_preset(frame, lighting_preset)
    frame = apply_color_temperature(frame, getattr(spec, "color_temperature", "neutral") or "neutral")
    frame = apply_style_look(frame, getattr(spec, "style", "cinematic") or "cinematic")
    setting_name = getattr(spec, "setting", None) or ""
    if setting_name in ("rain", "snow"):
        frame = _apply_weather_overlay(frame, setting_name, t_abs, seed=seed)

    text_overlay = getattr(spec, "text_overlay", None)
    text_pos = getattr(spec, "text_position", "center") or "center"
    font_size = 44
    want_callout = False
    want_arrow = False
    script_beats = getattr(spec, "script_beats", None)
    if script_beats:
        try:
            from ..creation.narrative_script import resolve_overlay_at_time
            overlay = resolve_overlay_at_time(
                script_beats, t_abs,
                fallback_text=text_overlay,
                fallback_position=text_pos,
                fallback_font_size=44,
            )
            text_overlay = overlay.get("text") or text_overlay
            text_pos = overlay.get("position") or text_pos
            font_size = int(overlay.get("font_size") or font_size)
            want_callout = bool(overlay.get("callout"))
            want_arrow = bool(overlay.get("arrow"))
        except ImportError:
            pass

    if (want_callout or want_arrow) and scene_layers:
        try:
            from ..graphics.primitives import draw_arrow, draw_callout, draw_spotlight
            from ..creation.scene_graph import (
                apply_composition_symmetry_x,
                composition_balance_offset,
                sample_layer_at,
            )
            # Ring the front-most non-prop-looking layer (highest z)
            target = None
            for layer in sorted(
                [L for L in scene_layers if isinstance(L, dict)],
                key=lambda L: int(L.get("z", 1)),
                reverse=True,
            ):
                if str(layer.get("kind") or "") not in ("cloud", "wave"):
                    target = layer
                    break
            if target is not None:
                pose = sample_layer_at(target, t_abs)
                cdx, cdy = composition_balance_offset(composition_balance)
                px = apply_composition_symmetry_x(
                    max(0.02, min(0.98, float(pose["x"]) + cdx)),
                    composition_symmetry,
                )
                py = max(0.02, min(0.98, float(pose["y"]) + cdy))
                scale = max(0.15, float(pose["scale"]))
                cx_px = int(px * (width - 1))
                cy_px = int(py * (height - 1))
                rad = max(12, int(0.14 * scale * min(width, height)))
                if want_callout:
                    frame = draw_spotlight(frame, (cx_px, cy_px), radius=int(rad * 1.6), darkness=0.4)
                    frame = draw_callout(frame, (cx_px, cy_px), radius=rad)
                if want_arrow:
                    # Arrow from top-center text area toward subject
                    start = (width // 2, max(20, height // 8))
                    frame = draw_arrow(frame, start, (cx_px, max(0, cy_px - rad)), thickness=3)
        except ImportError:
            pass

    if text_overlay:
        try:
            from ..graphics.text import render_text_overlay
            frame = render_text_overlay(
                frame, text_overlay, position=text_pos, font_size=font_size
            )
        except ImportError:
            pass

    if depth_parallax and not scene_layers:
        try:
            from ..depth.parallax import apply_parallax
            frame = apply_parallax(frame, t_motion, depth_layers=3, motion_scale=0.05)
        except ImportError:
            pass

    # Tier E: film camera stack (DoF, grain, motion smear) when film_look / enhanced
    if film_look:
        try:
            from .film import apply_film_look, estimate_depth_map
            # Camera pan delta for smear (finite difference)
            _z2, px2, py2, _r2 = get_camera_params(camera_motion, t_motion + 0.04)
            depth_map = estimate_depth_map(
                height, width,
                scene_layers=scene_layers or None,
                t=t_abs,
                composition_balance=composition_balance,
            )
            # Focus near mid-ground / subject
            focus = 0.55
            if scene_layers:
                focus = 0.62
            frame = apply_film_look(
                frame,
                lighting_preset=lighting_preset,
                seed=seed,
                t=t_abs,
                depth_map=depth_map,
                focus=focus,
                pan_dx=float(px2 - pan_x),
                pan_dy=float(py2 - pan_y),
            )
        except ImportError:
            pass

    return frame
