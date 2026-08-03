"""
Depth layers: create layered content for 2.5D. Phase 7.
"""
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np


# Soft atmosphere tint deltas by setting (added to base_rgb)
SETTING_ATMOSPHERE: dict[str, tuple[float, float, float]] = {
    "forest": (-15, 25, -8),
    "park": (-8, 22, -5),
    "rain": (-20, 5, 20),
    "snow": (25, 28, 35),
    "ocean": (-25, 15, 40),
    "beach": (20, 15, 5),
    "neon": (30, -5, 45),
    "city": (10, 5, 25),
    "street": (12, 8, 22),
    "night": (-30, -25, 10),
    "noir": (-35, -30, -15),
    "golden_hour": (45, 25, -5),
    "desert": (40, 25, 5),
    "mountain": (5, 15, 25),
}


def create_depth_layers(
    width: int,
    height: int,
    num_layers: int = 3,
    *,
    seed: int = 0,
    base_rgb: tuple[int, int, int] | None = None,
    setting: str | None = None,
) -> list[tuple["np.ndarray", float]]:
    """
    Create atmospheric depth plates (image, depth_value) for 2.5D compositing.

    depth_value: 0 = back, 1 = front; used for parallax speed.
    When base_rgb is set, plates are muted tints of that color (usable as haze
    between background and entities). Setting tints the atmosphere further.
    Returns list of (layer_image uint8 HxWx3, depth).
    """
    import numpy as np

    layers: list[tuple[np.ndarray, float]] = []
    rng = np.random.default_rng(seed)
    y = np.linspace(0, 1, height, dtype=np.float32)
    x = np.linspace(0, 1, width, dtype=np.float32)
    xx, yy = np.meshgrid(x, y)
    br, bg, bb = base_rgb if base_rgb else (120, 130, 140)
    tint = SETTING_ATMOSPHERE.get((setting or "").strip().lower(), (0.0, 0.0, 0.0))
    br = float(np.clip(br + tint[0] * 0.45, 0, 255))
    bg = float(np.clip(bg + tint[1] * 0.45, 0, 255))
    bb = float(np.clip(bb + tint[2] * 0.45, 0, 255))

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
