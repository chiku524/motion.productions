"""Renderer diversity: different seeds must give different fields, and 1 s must show motion."""
from __future__ import annotations

import unittest

import numpy as np

from src.procedural import renderer as rd
from src.procedural.renderer import _render_pure_per_frame, field_layout


def _grid(size: int = 64):
    return np.meshgrid(np.linspace(0, 1, size), np.linspace(0, 1, size))


def _pool(n: int = 12):
    rng = np.random.default_rng(3)
    return [tuple(int(x) for x in rng.integers(0, 256, 3)) for _ in range(n)]


def _dhash(img: np.ndarray, n: int = 16) -> np.ndarray:
    g = img.mean(axis=-1)
    h, w = g.shape
    ys = np.linspace(0, h - 1, n).astype(int)
    xs = np.linspace(0, w - 1, n + 1).astype(int)
    small = g[np.ix_(ys, xs)]
    return (small[:, 1:] > small[:, :-1]).ravel()


def _frame(seed, t, *, window, colors=None):
    xx, yy = _grid()
    r, g, b = _render_pure_per_frame(
        xx, yy, colors or _pool(), t, seed, 1.0,
        motion_level=16.0 if window else 2.5, motion_val=0.5,
        motion_sync=0.55 if window else 1.0,
    )
    return np.stack([r, g, b], axis=-1)


class TestFieldLayout(unittest.TestCase):
    def test_layout_is_deterministic_per_seed(self):
        a = field_layout(42, 8, 1, window=True)
        b = field_layout(42, 8, 1, window=True)
        np.testing.assert_array_equal(a["sites"], b["sites"])
        self.assertEqual((a["metric"], a["blend"]), (b["metric"], b["blend"]))

    def test_layout_styles_vary_across_seeds(self):
        lays = [field_layout(s, 8, 1, window=False) for s in range(60)]
        self.assertGreaterEqual(len({lay["metric"] for lay in lays}), 3)
        self.assertGreaterEqual(len({lay["blend"] for lay in lays}), 4)
        first = lays[0]["sites"]
        same = sum(np.allclose(lay["sites"], first) for lay in lays)
        self.assertEqual(same, 1)

    def test_site_count_varies_with_seed(self):
        base = rd._mass_count_from_colors(12, 0)
        counts = set()
        for s in range(40):
            jit = int(np.random.default_rng([s % (2**32), 0x51735]).integers(-2, 3))
            counts.add(max(3, min(24, base + jit)))
        self.assertGreaterEqual(len(counts), 3)


class TestPureFieldDiversity(unittest.TestCase):
    def _pairwise_hamming(self, window: bool, n: int = 16) -> np.ndarray:
        hashes = [_dhash(_frame(900 + s * 31, 0.0, window=window)) for s in range(n)]
        return np.array([
            float(np.mean(hashes[i] != hashes[j]))
            for i in range(n) for j in range(i + 1, n)
        ])

    def test_different_seeds_give_different_pictures(self):
        for window in (False, True):
            d = self._pairwise_hamming(window)
            self.assertGreater(float(np.median(d)), 0.2, f"window={window}")
            self.assertGreater(float(d.min()), 0.02, f"window={window}: near-duplicate pair")

    def test_one_second_shows_motion_in_every_seed(self):
        for window, floor in ((True, 6.0), (False, 1.0)):
            for s in range(12):
                a = _frame(300 + s, 0.0, window=window)
                b = _frame(300 + s, 1.0, window=window)
                self.assertGreater(float(np.mean(np.abs(a - b))), floor, f"seed {s} window={window}")

    def test_window_is_not_more_grain_than_structure(self):
        colors = _pool(24)
        for s in range(6):
            img = _frame(50 + s, 0.0, window=True, colors=colors)
            horiz = np.abs(np.diff(img, axis=1)).mean()
            self.assertLess(float(horiz), 60.0, f"seed {s}: window collapsed into grain")

    def test_layout_is_not_forced_regular(self):
        a = field_layout(1, 9, 1, window=False)["sites"]
        b = field_layout(2, 9, 1, window=False)["sites"]
        self.assertFalse(np.allclose(a, b, atol=0.05))


if __name__ == "__main__":
    unittest.main()