"""Tile extraction on synthetic frames."""
from __future__ import annotations

import numpy as np

from src.knowledge.color_cells import rgb_to_id
from src.knowledge.color_tiles import grid_tile_colors, observed_flat_ids, observed_flat_ids_video


def _frame(tile=32, rows=4, cols=4):
    f = np.zeros((rows * tile, cols * tile, 3), dtype=np.uint8)
    for r in range(rows):
        for c in range(cols):
            f[r * tile:(r + 1) * tile, c * tile:(c + 1) * tile] = (r * 50 + 3, c * 60 + 7, 99)
    return f


def test_flat_tiles_are_read_exactly():
    g = grid_tile_colors(_frame(), 32)
    assert g.qualifies.all()
    assert tuple(g.median[2, 3]) == (103, 187, 99)
    assert int(g.ids[1, 1]) == rgb_to_id(53, 67, 99)
    assert g.interior == 24 * 24


def test_noisy_tile_is_rejected_unless_tolerated():
    f = _frame()
    rng = np.random.default_rng(0)
    f[0:32, 0:32] = np.clip(f[0:32, 0:32].astype(int) + rng.integers(-6, 7, (32, 32, 3)), 0, 255)
    strict = grid_tile_colors(f, 32, tol=0)
    assert not strict.qualifies[0, 0] and strict.qualifies.sum() == 15
    assert grid_tile_colors(f, 32, tol=6).qualifies[0, 0]


def test_edge_ringing_outside_interior_is_ignored():
    f = _frame()
    f[0:32, 0:2] = 255  # trimmed margin (tile // 8 = 4 px)
    assert grid_tile_colors(f, 32).qualifies[0, 0]
    f[0:32, 0:8] = 255  # reaches into the interior
    assert not grid_tile_colors(f, 32).qualifies[0, 0]


def test_min_pixels_means_a_meaningful_area():
    f = _frame()
    assert not grid_tile_colors(f, 32, min_pixels=577).qualifies.any()  # interior is 576 px
    assert grid_tile_colors(f, 32, min_pixels=576).qualifies.all()


def test_partial_tiles_and_unique_ids():
    f = np.zeros((70, 100, 3), dtype=np.uint8)
    f[:] = (9, 9, 9)
    assert grid_tile_colors(f, 32).median.shape[:2] == (2, 3)
    assert observed_flat_ids(f, 32).tolist() == [rgb_to_id(9, 9, 9)]
    assert observed_flat_ids(np.zeros((8, 8, 3), np.uint8), 32).size == 0


def test_video_union():
    a, b = _frame(), _frame()
    b[:] = 200
    ids = observed_flat_ids_video([a, b, a])
    assert len(ids) == 17 and rgb_to_id(200, 200, 200) in set(ids.tolist())