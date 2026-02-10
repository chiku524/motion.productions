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
) -> list[tuple["np.ndarray", float]]:
    """
    Create depth layers (image, depth_value) for 2.5D.
    depth_value: 0 = back, 1 = front; used for parallax speed.
    Returns list of (layer_image, depth).
    """
    import numpy as np

    layers: list[tuple[np.ndarray, float]] = []
    rng = np.random.default_rng(seed)
    for i in range(num_layers):
        depth = (i + 1) / num_layers  # 0.33, 0.66, 1.0
        # Simple gradient per layer (procedural)
        y = np.linspace(0, 1, height)
        x = np.linspace(0, 1, width)
        xx, yy = np.meshgrid(x, y)
        v = (xx * 0.5 + yy * 0.5 + depth * 0.3 + rng.random() * 0.2) % 1.0
        r = (v * 255).astype(np.uint8)
        g = ((1 - v) * 200).astype(np.uint8)
        b = (v * 150).astype(np.uint8)
        img = np.stack([r, g, b], axis=-1)
        alpha = 0.3 + 0.4 * depth
        layers.append((img, depth))
    return layers
