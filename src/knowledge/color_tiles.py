"""
Tile extraction: which exact 8-bit colours does a decoded frame really contain, over a meaningful area?

A frame is cut into a regular grid of ``tile`` x ``tile`` blocks. For each block only the interior (``margin`` px
trimmed on every side, to stay clear of codec ringing at tile edges) is examined. A block *qualifies* when at least
``min_pixels`` interior pixels, and at least ``min_flat_frac`` of the interior, lie within ``tol`` of the block's
per-channel median. The median is then the block's colour. With ``tol = 0`` that means a flat, exact patch.

``tol`` is the codec error budget (0 for lossless RGB, 3 for the production H.264 yuv420p profile, see
``src/knowledge/color_survey.py``). Everything is vectorised numpy.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np

from .color_cells import rgb_array_to_ids

DEFAULT_TILE = 32
DEFAULT_MIN_PIXELS = 144        # >= 12 x 12 px of one colour
DEFAULT_MIN_FLAT_FRAC = 0.98


def default_margin(tile: int) -> int:
    return max(2, tile // 8)


@dataclass
class TileGrid:
    """Result for one frame: arrays shaped (rows, cols[, 3])."""

    median: np.ndarray       # uint8 (rows, cols, 3)
    flat_pixels: np.ndarray  # int32 (rows, cols): interior pixels within tol of the median
    interior: int            # interior pixels per tile
    qualifies: np.ndarray    # bool (rows, cols)

    @property
    def ids(self) -> np.ndarray:
        return rgb_array_to_ids(self.median)


def grid_tile_colors(
    frame: np.ndarray,
    tile: int = DEFAULT_TILE,
    *,
    margin: int | None = None,
    tol: int = 0,
    min_pixels: int = DEFAULT_MIN_PIXELS,
    min_flat_frac: float = DEFAULT_MIN_FLAT_FRAC,
) -> TileGrid:
    """Median colour + flatness of every grid tile of one (H, W, 3) uint8 frame (edges that do not fill a tile are ignored)."""
    f = np.asarray(frame)
    if f.ndim != 3 or f.shape[2] != 3:
        raise ValueError("frame must be (H, W, 3)")
    m = default_margin(tile) if margin is None else int(margin)
    if tile - 2 * m < 1:
        raise ValueError("tile too small for margin")
    rows, cols = f.shape[0] // tile, f.shape[1] // tile
    if rows == 0 or cols == 0:
        z = np.zeros((0, 0), dtype=bool)
        return TileGrid(np.zeros((0, 0, 3), np.uint8), np.zeros((0, 0), np.int32), 0, z)
    blocks = f[: rows * tile, : cols * tile].reshape(rows, tile, cols, tile, 3)
    inner = blocks[:, m:tile - m, :, m:tile - m, :]                      # (rows, ih, cols, iw, 3)
    ih, iw = inner.shape[1], inner.shape[3]
    flat = inner.transpose(0, 2, 4, 1, 3).reshape(rows, cols, 3, ih * iw)  # (rows, cols, 3, px)
    med = np.median(flat, axis=-1)
    med_u8 = np.rint(med).astype(np.uint8)
    close = (np.abs(flat.astype(np.int16) - med_u8[..., None].astype(np.int16)) <= tol).all(axis=2)  # (rows, cols, px)
    flat_px = close.sum(axis=-1).astype(np.int32)
    interior = ih * iw
    ok = (flat_px >= min_pixels) & (flat_px >= min_flat_frac * interior)
    return TileGrid(med_u8, flat_px, interior, ok)


def observed_flat_ids(
    frame: np.ndarray,
    tile: int = DEFAULT_TILE,
    *,
    margin: int | None = None,
    tol: int = 0,
    min_pixels: int = DEFAULT_MIN_PIXELS,
    min_flat_frac: float = DEFAULT_MIN_FLAT_FRAC,
) -> np.ndarray:
    """Unique exact colour ids of the qualifying tiles of one frame."""
    g = grid_tile_colors(frame, tile, margin=margin, tol=tol, min_pixels=min_pixels, min_flat_frac=min_flat_frac)
    if g.qualifies.size == 0:
        return np.zeros(0, dtype=np.int64)
    return np.unique(g.ids[g.qualifies]).astype(np.int64)


def observed_flat_ids_video(frames: Iterable[np.ndarray], **kw) -> np.ndarray:
    """Union of ``observed_flat_ids`` over frames (e.g. sampled frames of a creative clip)."""
    seen: list[np.ndarray] = []
    for fr in frames:
        ids = observed_flat_ids(fr, **kw)
        if ids.size:
            seen.append(ids)
    return np.unique(np.concatenate(seen)) if seen else np.zeros(0, dtype=np.int64)