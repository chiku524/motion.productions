"""
Graphics primitives: arrows, callouts, highlights.
Phase 4. Uses Pillow/numpy only (no OpenCV).
"""
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np


def draw_arrow(
    frame: "np.ndarray",
    start: tuple[int, int],
    end: tuple[int, int],
    *,
    color: tuple[int, int, int] = (255, 255, 0),
    thickness: int = 4,
) -> "np.ndarray":
    """Draw an arrow from start to end using Pillow."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return frame

    import numpy as np

    pil = Image.fromarray(frame)
    draw = ImageDraw.Draw(pil)
    x0, y0 = int(start[0]), int(start[1])
    x1, y1 = int(end[0]), int(end[1])
    draw.line([(x0, y0), (x1, y1)], fill=color, width=thickness)
    # Arrowhead (simple triangle)
    import math
    angle = math.atan2(y1 - y0, x1 - x0)
    tip_len = 20
    a1 = (x1 - tip_len * math.cos(angle - 0.5), y1 - tip_len * math.sin(angle - 0.5))
    a2 = (x1 - tip_len * math.cos(angle + 0.5), y1 - tip_len * math.sin(angle + 0.5))
    draw.polygon([(x1, y1), a1, a2], outline=color, fill=color)
    return np.array(pil)


def draw_callout(
    frame: "np.ndarray",
    center: tuple[int, int],
    radius: int = 40,
    *,
    color: tuple[int, int, int] = (255, 200, 0),
    thickness: int = 3,
    highlight: bool = True,
) -> "np.ndarray":
    """Draw a callout circle (e.g. to highlight a region)."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return frame

    import numpy as np

    pil = Image.fromarray(frame)
    draw = ImageDraw.Draw(pil)
    x, y = int(center[0]), int(center[1])
    box = [x - radius, y - radius, x + radius, y + radius]
    draw.ellipse(box, outline=color, width=thickness)
    if highlight:
        arr = np.array(pil)
        yy, xx = np.ogrid[: arr.shape[0], : arr.shape[1]]
        dist = np.sqrt((xx - x) ** 2 + (yy - y) ** 2)
        mask = (dist <= radius) & (dist > radius - thickness)
        alpha = 0.15
        for c in range(3):
            arr[:, :, c] = np.where(
                mask,
                np.clip(arr[:, :, c] * (1 - alpha) + color[c] * alpha, 0, 255).astype(np.uint8),
                arr[:, :, c],
            )
        return arr
    return np.array(pil)
