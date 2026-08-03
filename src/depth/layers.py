"""
Depth layers: create layered content for 2.5D. Phase 7.
"""
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np


def create_depth_layers(
    width: int,
    height: int,
    num_layers: int = 3,
    *,
    seed: int = 0,
    base_rgb: tuple[int, int, int] | None = None,
) -> list[tuple["np.ndarray", float]]:
    """
    Create atmospheric depth plates (image, depth_value) for 2.5D compositing.

    depth_value: 0 = back, 1 = front; used for parallax speed.
    When base_rgb is set, plates are muted tints of that color (usable as haze
    between background and entities). Otherwise a neutral procedural gradient.
    Returns list of (layer_image uint8 HxWx3, depth).
    """
    import numpy as np

    layers: list[tuple[np.ndarray, float]] = []
    rng = np.random.default_rng(seed)
    y = np.linspace(0, 1, height, dtype=np.float32)
    x = np.linspace(0, 1, width, dtype=np.float32)
    xx, yy = np.meshgrid(x, y)
    br, bg, bb = base_rgb if base_rgb else (120, 130, 140)

    for i in range(num_layers):
        depth = (i + 1) / max(1, num_layers)
        # Soft vertical bands + light noise — readable as atmosphere, not rainbow noise
        band = np.clip(1.0 - np.abs(yy - (0.35 + 0.25 * depth)) * 2.2, 0, 1)
        n = rng.random((height, width)).astype(np.float32)
        haze = 0.35 * band + 0.15 * n
        fade = 0.25 + 0.35 * (1.0 - depth)  # farther plates more present
        r = np.clip(br * (0.55 + 0.45 * haze) * fade + br * (1 - fade) * 0.3, 0, 255)
        g = np.clip(bg * (0.55 + 0.45 * haze) * fade + bg * (1 - fade) * 0.3, 0, 255)
        b = np.clip(bb * (0.55 + 0.45 * haze) * fade + bb * (1 - fade) * 0.3, 0, 255)
        img = np.stack([r, g, b], axis=-1).astype(np.uint8)
        layers.append((img, float(depth)))
    return layers
