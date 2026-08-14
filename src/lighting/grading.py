"""
Color grading: lighting presets, LUT-style transforms, and lighting model.
Phase 3: key/fill/rim/ambient as first-class parameters.
"""
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

# Lighting model: key (main), fill (soften shadows), rim (edge), ambient (base)
# Each 0-1; combined with presets for final look
LIGHTING_MODEL_DEFAULTS: dict[str, tuple[float, float, float, float]] = {
    "neutral": (1.0, 0.5, 0.2, 0.3),
    "noir": (0.9, 0.2, 0.1, 0.2),
    "golden_hour": (1.0, 0.6, 0.5, 0.4),
    "neon": (1.0, 0.4, 0.8, 0.25),
    "documentary": (1.0, 0.6, 0.15, 0.35),
    "moody": (0.85, 0.3, 0.25, 0.25),
}

# Lighting presets: (contrast, saturation, lift, gamma, gain)
# lift: shadows; gamma: midtones; gain: highlights
LIGHTING_PRESETS: dict[str, tuple[float, float, float, float, float]] = {
    "neutral": (1.0, 1.0, 0.0, 1.0, 1.0),
    "noir": (1.3, 0.6, -0.1, 1.1, 0.9),
    "golden_hour": (1.1, 1.2, 0.02, 0.95, 1.1),
    "neon": (1.2, 1.4, 0.0, 1.0, 1.15),
    "documentary": (1.05, 0.95, 0.0, 1.0, 1.0),
    "moody": (1.25, 0.8, -0.05, 1.15, 0.95),
}


def apply_lighting_preset(
    frame: "np.ndarray",
    preset: str,
) -> "np.ndarray":
    """
    Apply lighting preset to RGB frame (0-255).
    Uses lift/gamma/gain and contrast/saturation.
    """
    import numpy as np

    preset = (preset or "neutral").lower().replace(" ", "_")
    params = LIGHTING_PRESETS.get(preset, LIGHTING_PRESETS["neutral"])
    contrast, saturation, lift, gamma, gain = params

    out = frame.astype(np.float64) / 255.0

    # Lift/gamma/gain (simplified)
    out = (out + lift) * gain
    out = np.clip(out, 0, 1) ** (1.0 / max(0.1, gamma))

    # Contrast (pivot 0.5)
    out = (out - 0.5) * contrast + 0.5

    # Saturation
    gray = 0.299 * out[:, :, 0] + 0.587 * out[:, :, 1] + 0.114 * out[:, :, 2]
    gray = np.stack([gray, gray, gray], axis=-1)
    out = gray + (out - gray) * saturation

    out = np.clip(out, 0, 1) * 255
    return out.astype(np.uint8)


def apply_lut_params(
    frame: "np.ndarray",
    *,
    contrast: float = 1.0,
    saturation: float = 1.0,
    lift: float = 0.0,
    gamma: float = 1.0,
    gain: float = 1.0,
) -> "np.ndarray":
    """
    Apply LUT-style parameters: lift/gamma/gain, contrast, saturation.
    """
    import numpy as np

    out = frame.astype(np.float64) / 255.0
    out = (out + lift) * gain
    out = np.clip(out, 0, 1) ** (1.0 / max(0.1, gamma))
    out = (out - 0.5) * contrast + 0.5
    gray = 0.299 * out[:, :, 0] + 0.587 * out[:, :, 1] + 0.114 * out[:, :, 2]
    gray = np.stack([gray, gray, gray], axis=-1)
    out = gray + (out - gray) * saturation
    out = np.clip(out, 0, 1) * 255
    return out.astype(np.uint8)


def apply_color_temperature(
    frame: "np.ndarray",
    temperature: str,
) -> "np.ndarray":
    """Nudge frame toward warm or cool using lift/gain on channels."""
    import numpy as np

    t = (temperature or "neutral").lower()
    if t == "neutral" or t == "":
        return frame
    out = frame.astype(np.float32)
    if t == "warm":
        out[..., 0] = np.clip(out[..., 0] * 1.06 + 4, 0, 255)
        out[..., 1] = np.clip(out[..., 1] * 1.02, 0, 255)
        out[..., 2] = np.clip(out[..., 2] * 0.94 - 2, 0, 255)
    elif t == "cool":
        out[..., 0] = np.clip(out[..., 0] * 0.94 - 2, 0, 255)
        out[..., 1] = np.clip(out[..., 1] * 1.0, 0, 255)
        out[..., 2] = np.clip(out[..., 2] * 1.07 + 5, 0, 255)
    if frame.dtype == np.uint8:
        return out.astype(np.uint8)
    return out


def apply_style_look(
    frame: "np.ndarray",
    style: str,
) -> "np.ndarray":
    """NumPy grades so anime / minimal / abstract actually read as those looks."""
    import numpy as np

    s = (style or "cinematic").lower()
    if s in ("cinematic", "realistic", "photoreal", ""):
        return frame
    out = frame.astype(np.float32)
    gray = 0.299 * out[..., 0] + 0.587 * out[..., 1] + 0.114 * out[..., 2]
    gray3 = gray[..., None]
    if s == "anime":
        # Harder chroma, posterize, ink-line edges
        out = gray3 + (out - gray3) * 1.55
        out = np.round(out / 32.0) * 32.0
        gy, gx = np.gradient(gray)
        edge = np.clip(np.sqrt(gx * gx + gy * gy) / 18.0, 0.0, 1.0)
        out = out * (1.0 - 0.55 * edge[..., None])
        # Mild cel highlight on bright regions
        hi = np.clip((gray - 160.0) / 80.0, 0.0, 1.0)
        out = out + (18.0 * hi)[..., None]
    elif s == "minimal":
        out = gray3 + (out - gray3) * 0.35
        out = (out - 128.0) * 0.7 + 140.0
    elif s in ("abstract", "experimental"):
        n = np.sin(out[..., 0] * 0.07 + out[..., 2] * 0.05) * 28.0
        out[..., 0] = out[..., 0] + n
        out[..., 2] = out[..., 2] - n * 0.7
        out = gray3 + (out - gray3) * 1.45
        # Hue-rotate-ish channel swap on a slice of luma
        mask = (gray > 90) & (gray < 180)
        swapped = out.copy()
        swapped[..., 0], swapped[..., 2] = out[..., 2], out[..., 0]
        out = np.where(mask[..., None], swapped * 0.55 + out * 0.45, out)
    if frame.dtype == np.uint8:
        return np.clip(out, 0, 255).astype(np.uint8)
    return np.clip(out, 0, 255)


def get_lighting_model(preset: str) -> tuple[float, float, float, float]:
    """Return (key, fill, rim, ambient) for a preset."""
    preset = (preset or "neutral").lower().replace(" ", "_")
    return LIGHTING_MODEL_DEFAULTS.get(preset, LIGHTING_MODEL_DEFAULTS["neutral"])


def apply_spatial_layer_lighting(
    color_rgb: tuple[float, float, float] | list[float],
    mask: "np.ndarray",
    xx: "np.ndarray",
    yy: "np.ndarray",
    cx: float,
    cy: float,
    radius: float,
    lighting_model: tuple[float, float, float, float],
) -> "np.ndarray":
    """
    Shade a flat layer color with fake normals + key/fill/rim/ambient.

    mask: HxW alpha (0-1). Returns HxWx3 float lit color in the same units as color_rgb (typically 0-255).
    Key from upper-left; fill softens the opposite side; rim brightens soft silhouette edges.
    """
    import numpy as np

    key, fill, rim, ambient = lighting_model
    r = max(1e-6, float(radius))
    # Fake surface normal from offset relative to layer center (outward on a sphere)
    nx = (xx - cx) / r
    ny = (yy - cy) / r
    # Key light direction (from upper-left toward subject)
    kx, ky = -0.55, -0.72
    # Facing key: how much the outward normal points toward the light
    ndot_key = np.clip(-(nx * kx + ny * ky), 0.0, 1.0)
    # Fill from opposite softer direction
    fx, fy = 0.45, 0.35
    ndot_fill = np.clip(-(nx * fx + ny * fy), 0.0, 1.0)
    # Rim: soft edge of the mask (silhouette)
    m = np.asarray(mask, dtype=np.float32)
    # Finite-difference edge magnitude
    gy, gx = np.gradient(m)
    edge = np.clip(np.sqrt(gx * gx + gy * gy) * 4.0, 0.0, 1.0)

    light = (
        float(ambient) * 0.55
        + float(key) * ndot_key
        + float(fill) * ndot_fill * 0.55
        + float(rim) * edge * 0.85
    )
    # Keep midtones readable; avoid crushing to black
    light = np.clip(light, 0.25, 1.85)
    cr, cg, cb = float(color_rgb[0]), float(color_rgb[1]), float(color_rgb[2])
    lit = np.stack([cr * light, cg * light, cb * light], axis=-1)
    return lit
