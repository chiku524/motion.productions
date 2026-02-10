"""
Asset libraries: procedural textures, shapes. Phase 7.
"""
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

# Registry of asset names → procedural generator
_ASSET_REGISTRY: dict[str, str] = {
    "noise": "noise",
    "grid": "grid",
    "dots": "dots",
    "wave": "wave",
}


def get_asset_texture(
    name: str,
    width: int,
    height: int,
    *,
    seed: int = 0,
) -> "np.ndarray | None":
    """Generate a procedural texture by name."""
    import numpy as np

    name = (name or "").lower()
    if name not in _ASSET_REGISTRY:
        return None

    rng = np.random.default_rng(seed)
    y = np.linspace(0, 1, height)
    x = np.linspace(0, 1, width)
    xx, yy = np.meshgrid(x, y)

    if name == "noise":
        n = rng.random((height, width))
        v = (n * 255).astype(np.uint8)
        return np.stack([v, v, v], axis=-1)
    if name == "grid":
        scale = 8
        gx = (xx * scale * 2) % 1
        gy = (yy * scale * 2) % 1
        v = (np.minimum(gx, 1 - gx) + np.minimum(gy, 1 - gy)) * 255
        v = np.clip(v, 0, 255).astype(np.uint8)
        return np.stack([v, v, v], axis=-1)
    if name == "dots":
        scale = 12
        gx = (xx * scale) % 1
        gy = (yy * scale) % 1
        dist = np.sqrt((gx - 0.5) ** 2 + (gy - 0.5) ** 2) * 4
        v = np.clip(255 * (1 - dist), 0, 255).astype(np.uint8)
        return np.stack([v, v, v], axis=-1)
    if name == "wave":
        v = 128 + 80 * np.sin(xx * 6 + yy * 4 + seed)
        v = np.clip(v, 0, 255).astype(np.uint8)
        return np.stack([v, v, v], axis=-1)
    return None


def list_assets() -> list[str]:
    """List available asset names."""
    return list(_ASSET_REGISTRY.keys())
