"""
Parallax effect: layers move at different speeds for depth. Phase 7.
"""
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np


def apply_parallax(
    frame: "np.ndarray",
    t: float,
    *,
    depth_layers: int = 3,
    motion_scale: float = 0.1,
) -> "np.ndarray":
    """
    Apply parallax-style motion: simulate depth by offsetting layers.
    Foreground (center) moves faster, background moves slower.
    """
    import numpy as np

    h, w = frame.shape[:2]
    if depth_layers < 2:
        return frame

    # Simple parallax: horizontal offset that varies by "depth" (y-position as proxy)
    # Top of frame = background (slow), center = foreground (fast)
    y = np.linspace(0, 1, h, dtype=np.float32)
    x = np.linspace(0, 1, w, dtype=np.float32)
    xx, yy = np.meshgrid(x, y)

    # Depth factor: 0 at top (far), 1 at center (near)
    depth = np.sin(np.pi * yy)  # 0 at top/bottom edges, 1 at vertical center
    offset = motion_scale * np.sin(t * 0.5) * depth
    xx_shifted = xx + offset

    # Sample with wrapping
    xx_shifted = np.clip(xx_shifted, 0, 1)
    xi = (xx_shifted * (w - 1)).astype(np.int32)
    yi = (yy * (h - 1)).astype(np.int32)
    xi = np.clip(xi, 0, w - 1)
    yi = np.clip(yi, 0, h - 1)

    out = frame[yi, xi]
    return out
