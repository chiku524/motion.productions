"""Opacity plane (first slice): which (colour, opacity) combinations have been declared / observed.

The exact-colour space ``color.L2.a20`` is RGB only. Full RGBA at 8 bits would be 2^32 cells (512 MiB per bitset
plane), so this slice records opacity on a coarse but exact-to-the-bin grid:

* colour: 5 bits per channel (32,768 RGB bins; bin = channel >> 3)
* opacity: 16 levels (alpha >> 4; alpha 0..255)

= 524,288 cells = one 64 KiB plane per tier (``declared``: a spec asked for it; ``observed``: measured in output).
Local only (``<store>/opacity_{tier}.bits`` next to the colour planes); nothing is posted to D1 in this slice.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np

from .color_cells import _FileLock, atomic_write_bytes, default_store_dir, popcount

SPACE_ID = "color.L1.a4o"
RGB_BITS = 5
ALPHA_LEVELS = 16
RGB_BINS = 1 << (3 * RGB_BITS)          # 32,768
SPACE_SIZE = RGB_BINS * ALPHA_LEVELS     # 524,288
PLANE_BYTES = SPACE_SIZE // 8            # 65,536
TIERS = ("declared", "observed")


def alpha_level(alpha: float | int) -> int:
    """0..15 from an opacity in [0, 1] (float) or 0..255 (int)."""
    if isinstance(alpha, float) and 0.0 <= alpha <= 1.0:
        a = int(round(alpha * 255))
    else:
        a = int(alpha)
    return max(0, min(255, a)) >> 4


def cell_id(r: int, g: int, b: int, alpha: float | int) -> int:
    shift = 8 - RGB_BITS
    rgb = ((int(r) >> shift) << (2 * RGB_BITS)) | ((int(g) >> shift) << RGB_BITS) | (int(b) >> shift)
    return alpha_level(alpha) * RGB_BINS + rgb


class OpacityPlane:
    def __init__(self, directory: Path | str | None = None):
        self.dir = Path(directory) if directory else default_store_dir()
        self.dir.mkdir(parents=True, exist_ok=True)
        self._lock = self.dir / "store.lock"
        self.planes = {t: self._read(t) for t in TIERS}

    def _path(self, tier: str) -> Path:
        return self.dir / f"opacity_{tier}.bits"

    def _read(self, tier: str) -> np.ndarray:
        try:
            raw = self._path(tier).read_bytes()
            if len(raw) == PLANE_BYTES:
                return np.frombuffer(raw, dtype=np.uint8).copy()
        except OSError:
            pass
        return np.zeros(PLANE_BYTES, dtype=np.uint8)

    def mark(self, tier: str, ids: Iterable[int]) -> int:
        """Set bits; returns how many were new."""
        if tier not in TIERS:
            raise ValueError(f"unknown tier: {tier}")
        arr = np.unique(np.asarray(list(ids), dtype=np.int64))
        if arr.size == 0:
            return 0
        if arr.min() < 0 or arr.max() >= SPACE_SIZE:
            raise ValueError("opacity cell out of range")
        p = self.planes[tier]
        byte, bit = arr >> 3, (arr & 7).astype(np.uint8)
        was = (p[byte] >> bit) & 1
        np.bitwise_or.at(p, byte, (1 << bit).astype(np.uint8))
        return int((was == 0).sum())

    def save(self) -> None:
        with _FileLock(self._lock):
            for t in TIERS:
                disk = self._read(t)
                np.bitwise_or(self.planes[t], disk, out=self.planes[t])
                atomic_write_bytes(self._path(t), self.planes[t].tobytes())

    def counts(self) -> dict:
        d, o = self.planes["declared"], self.planes["observed"]
        per_level = []
        lvl_bytes = RGB_BINS // 8
        for lv in range(ALPHA_LEVELS):
            sl = slice(lv * lvl_bytes, (lv + 1) * lvl_bytes)
            per_level.append(popcount(d[sl] | o[sl]))
        return {"space": SPACE_ID, "size": SPACE_SIZE, "declared": popcount(d), "observed": popcount(o),
                "covered": popcount(d | o), "per_alpha_level": per_level}


def ids_from_layers(layers: list[dict] | None) -> list[int]:
    """(colour, opacity) cells a spec's scene layers declare. Accepts ``color``/``rgb`` as (r,g,b) or '#rrggbb'
    and ``opacity``/``alpha``; a layer without an explicit opacity is not recorded (it says nothing about opacity)."""
    out: list[int] = []
    for lay in layers or []:
        if not isinstance(lay, dict):
            continue
        a = lay.get("opacity", lay.get("alpha"))
        c = lay.get("color", lay.get("rgb"))
        if a is None or c is None:
            continue
        try:
            if isinstance(c, str) and c.startswith("#") and len(c) == 7:
                rgb = (int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16))
            else:
                rgb = tuple(int(v) for v in c)[:3]
            out.append(cell_id(*rgb, float(a) if isinstance(a, float) else int(a)))
        except (TypeError, ValueError):
            continue
    return out
