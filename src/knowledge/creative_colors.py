"""Exact-colour extraction from CREATIVE clips (opportunistic, budget-capped).

Survey clips verify cells on purpose; creative clips already contain thousands of colours. This samples a few frames
of a finished creative clip, keeps only FLAT tiles (same flatness rule as the survey's ``observed`` tier), and marks
their median colours ``observed`` in the shared exact-colour store. It never marks ``verified`` (creative clips use the
lossy production codec, so a decoded colour is a real observation of ITS value, not proof a target round-trips).

Budget: local CPU only (``CREATIVE_COLOR_FRAMES`` frames, default 6, and at most ``CREATIVE_COLOR_MAX_NEW`` new cells
per clip, default 2,000). D1 cost is unchanged per clip: new bits reach D1 only through the existing chunked coverage
sync (``color_sync.maybe_sync``: <= 32 changed 64 KiB chunks, rate-limited), which the write budget books separately.
Opt-in with ``LOOP_CREATIVE_COLORS=1``.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import numpy as np

from .color_cells import ColorCellStore, rgb_array_to_ids
from .color_tiles import DEFAULT_MIN_FLAT_FRAC, DEFAULT_MIN_PIXELS, grid_tile_colors

logger = logging.getLogger(__name__)
PRODUCTION_TOL = 4  # flatness tolerance of the lossy production codec (see color_survey.PROFILES["production"])


def enabled() -> bool:
    return (os.environ.get("LOOP_CREATIVE_COLORS") or "").strip().lower() in ("1", "true", "yes")


def _int_env(name: str, default: int) -> int:
    try:
        return max(0, int((os.environ.get(name) or "").strip() or default))
    except ValueError:
        return default


def sample_indices(n_frames: int, k: int) -> list[int]:
    if n_frames <= 0 or k <= 0:
        return []
    if k >= n_frames:
        return list(range(n_frames))
    return sorted({int(round(i * (n_frames - 1) / (k - 1))) for i in range(k)}) if k > 1 else [n_frames // 2]


def flat_tile_ids(frames: np.ndarray, *, tile: int = 16, tol: int = PRODUCTION_TOL) -> np.ndarray:
    """Unique exact-colour ids of the flat tiles' medians over the given (F, H, W, 3) frames."""
    ids: list[np.ndarray] = []
    for fr in frames:
        g = grid_tile_colors(fr, tile, tol=tol, min_pixels=DEFAULT_MIN_PIXELS, min_flat_frac=DEFAULT_MIN_FLAT_FRAC)
        if g.median.size:
            ids.append(rgb_array_to_ids(g.median[g.qualifies]))
    return np.unique(np.concatenate(ids)).astype(np.int64) if ids else np.zeros(0, dtype=np.int64)


def record_frames(store: ColorCellStore, frames: np.ndarray, *, max_new: int | None = None, job_id: str = "") -> dict[str, Any]:
    max_new = _int_env("CREATIVE_COLOR_MAX_NEW", 2000) if max_new is None else max_new
    ids = flat_tile_ids(frames)
    new = ids[~store.covered_mask(ids)] if ids.size else ids
    capped = new[:max_new]
    if capped.size:
        store.record_outcome(observed=capped, ledger={"k": "creative", "n": int(ids.size), "obs": int(capped.size),
                                                      "j": str(job_id)[:40]})
    return {"flat_colors": int(ids.size), "new_cells": int(capped.size), "dropped_over_cap": int(new.size - capped.size)}


def record_clip(path: Path | str, *, store: ColorCellStore | None = None, job_id: str = "") -> dict[str, Any]:
    """Sample frames of a finished creative clip and record new observed cells. Never raises."""
    try:
        import imageio.v2 as imageio

        k = _int_env("CREATIVE_COLOR_FRAMES", 6)
        reader = imageio.get_reader(str(path))
        try:
            try:
                n = reader.count_frames()
            except Exception:
                n = 0
            frames = []
            for i in sample_indices(n, k) if n else range(k):
                try:
                    frames.append(np.asarray(reader.get_data(i))[..., :3])
                except (IndexError, RuntimeError):
                    break
        finally:
            reader.close()
        if not frames:
            return {"error": "no frames"}
        return record_frames(store or ColorCellStore(), np.stack(frames), job_id=job_id)
    except Exception as e:
        logger.debug("creative colour extraction skipped: %s", e)
        return {"error": str(e)[:200]}
