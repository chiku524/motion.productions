"""
Procedural frame renderer: spec + time → pixels. Our algorithms only — no external model.
Uses our data (palettes) and our motion functions.
"""
from typing import TYPE_CHECKING

from .data.palettes import PALETTES
from .motion import get_motion_func
from .parser import SceneSpec

if TYPE_CHECKING:
    import numpy as np


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
    No neural network — gradient + noise + motion from our data.
    """
    import numpy as np

    palette = PALETTES.get(spec.palette_name, PALETTES["default"])
    motion_fn = get_motion_func(spec.motion_type)
    motion_val = motion_fn(t)
    intensity = max(0.1, min(1.0, spec.intensity))

    # Grid of coordinates 0..1
    y = np.linspace(0, 1, height, dtype=np.float32)
    x = np.linspace(0, 1, width, dtype=np.float32)
    xx, yy = np.meshgrid(x, y)

    # Gradient: blend palette colors by vertical position + time
    v = (yy + motion_val * 0.3) % 1.0
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

    frame = np.stack([r, g, b], axis=-1).astype(np.uint8)
    return frame
