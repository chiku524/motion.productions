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


def get_lighting_model(preset: str) -> tuple[float, float, float, float]:
    """Return (key, fill, rim, ambient) for a preset."""
    preset = (preset or "neutral").lower().replace(" ", "_")
    return LIGHTING_MODEL_DEFAULTS.get(preset, LIGHTING_MODEL_DEFAULTS["neutral"])
