"""
Parallax / 2.5D depth compositing. Phase 7.

True multi-plane path: background + depth-tagged RGBA planes with independent
horizontal offsets (foreground moves more). Legacy UV-warp kept as fallback.
"""
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np


def horizontal_shift(img: "np.ndarray", offset_norm: float) -> "np.ndarray":
    """
    Shift an HxW or HxWxC array horizontally by offset_norm (fraction of width).
    Positive offset moves content to the right (samples from the left).
    """
    import numpy as np

    h, w = img.shape[:2]
    if abs(offset_norm) < 1e-8:
        return img
    xs = (np.arange(w, dtype=np.float32) - offset_norm * (w - 1))
    xs = np.clip(xs, 0, w - 1).astype(np.int32)
    return img[:, xs]


def composite_depth_planes(
    background: "np.ndarray",
    planes: list[tuple["np.ndarray", "np.ndarray", float]],
    t: float,
    *,
    motion_scale: float = 0.06,
) -> "np.ndarray":
    """
    Composite RGB background with (rgb, alpha, depth) planes.

    depth in [0, 1]: 0 = far (slow), 1 = near (fast). Each plane is shifted
    horizontally by motion_scale * sin(t*0.5) * depth before alpha-over.
    background and plane rgb are float 0-255; alpha is float 0-1 HxW.
    """
    import numpy as np

    out = background.astype(np.float32).copy()
    if out.ndim == 2:
        out = np.stack([out, out, out], axis=-1)
    phase = float(np.sin(t * 0.5))
    for rgb, alpha, depth in planes:
        d = float(max(0.0, min(1.0, depth)))
        offset = motion_scale * phase * d
        rgb_s = horizontal_shift(np.asarray(rgb, dtype=np.float32), offset)
        a = horizontal_shift(np.asarray(alpha, dtype=np.float32), offset)
        if a.ndim == 3:
            a = a[..., 0]
        a = np.clip(a, 0.0, 1.0)[..., None]
        out = out * (1.0 - a) + rgb_s * a
    return np.clip(out, 0, 255)


def apply_parallax(
    frame: "np.ndarray",
    t: float,
    *,
    depth_layers: int = 3,
    motion_scale: float = 0.1,
) -> "np.ndarray":
    """
    Legacy single-buffer UV warp (y-as-depth proxy).

    Prefer composite_depth_planes when discrete planes are available; this
    remains for callers that only have a flat frame.
    """
    import numpy as np

    h, w = frame.shape[:2]
    if depth_layers < 2:
        return frame

    y = np.linspace(0, 1, h, dtype=np.float32)
    x = np.linspace(0, 1, w, dtype=np.float32)
    xx, yy = np.meshgrid(x, y)

    depth = np.sin(np.pi * yy)
    offset = motion_scale * np.sin(t * 0.5) * depth
    xx_shifted = np.clip(xx + offset, 0, 1)
    xi = (xx_shifted * (w - 1)).astype(np.int32)
    yi = (yy * (h - 1)).astype(np.int32)
    xi = np.clip(xi, 0, w - 1)
    yi = np.clip(yi, 0, h - 1)

    return frame[yi, xi]
