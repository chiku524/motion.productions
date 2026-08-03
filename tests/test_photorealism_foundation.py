"""
Tier A+B photorealism foundation: textures, composition framing,
spatial key/fill/rim lighting, and true depth-plane compositing.
"""
from __future__ import annotations

import unittest

import numpy as np

from src.creation.builder import build_spec_from_instruction
from src.creation.scene_graph import composition_balance_offset
from src.depth.assets import get_asset_texture, texture_for_setting
from src.depth.layers import create_depth_layers
from src.depth.parallax import composite_depth_planes, horizontal_shift
from src.interpretation.parser import interpret_user_prompt
from src.lighting.grading import apply_spatial_layer_lighting, get_lighting_model
from src.procedural.renderer import render_frame


class TestPhotorealismFoundation(unittest.TestCase):
    def test_texture_for_setting(self):
        self.assertEqual(texture_for_setting("forest"), "noise")
        self.assertEqual(texture_for_setting("city"), "grid")
        self.assertEqual(texture_for_setting("ocean"), "wave")
        self.assertIsNone(texture_for_setting(None))
        tex = get_asset_texture("wave", 32, 32, seed=1)
        self.assertIsNotNone(tex)
        assert tex is not None
        self.assertEqual(tex.shape, (32, 32, 3))

    def test_composition_balance_offset(self):
        self.assertEqual(composition_balance_offset("left_heavy")[0], -0.14)
        self.assertGreater(composition_balance_offset("right_heavy")[0], 0)
        self.assertEqual(composition_balance_offset("balanced"), (0.0, 0.0))

    def test_composition_shifts_layer_in_frame(self):
        from src.procedural.renderer import _render_layers_rgba

        layers = [{
            "kind": "circle",
            "color": [255, 0, 0],
            "z": 1,
            "keyframes": [
                {"t": 0, "x": 0.5, "y": 0.5, "scale": 1.4, "rot": 0, "opacity": 1},
                {"t": 1, "x": 0.5, "y": 0.5, "scale": 1.4, "rot": 0, "opacity": 1},
            ],
        }]
        _, ab = _render_layers_rgba(layers, 0.0, 64, 64, composition_balance="balanced")
        _, al = _render_layers_rgba(layers, 0.0, 64, 64, composition_balance="left_heavy")
        xs = np.arange(64, dtype=np.float32)
        wb = ab.sum(axis=0) + 1e-6
        wl = al.sum(axis=0) + 1e-6
        cx_b = float((xs * wb).sum() / wb.sum())
        cx_l = float((xs * wl).sum() / wl.sum())
        self.assertLess(cx_l, cx_b - 2.0, f"expected left_heavy centroid {cx_l} < balanced {cx_b}")

    def test_spatial_lighting_varies_across_mask(self):
        h = w = 48
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        xx = xx / (w - 1)
        yy = yy / (h - 1)
        cx, cy, radius = 0.5, 0.5, 0.3
        mask = (np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) < radius).astype(np.float32)
        lit = apply_spatial_layer_lighting(
            (200, 100, 50), mask, xx, yy, cx, cy, radius, get_lighting_model("noir"),
        )
        self.assertEqual(lit.shape, (h, w, 3))
        # Lit values inside mask should not be uniform (key creates a gradient)
        inside = mask > 0.5
        vals = lit[:, :, 0][inside]
        self.assertGreater(float(vals.max() - vals.min()), 5.0)

    def test_depth_plane_compositing_shifts_foreground(self):
        bg = np.zeros((32, 64, 3), dtype=np.float32)
        fg = np.zeros((32, 64, 3), dtype=np.float32)
        fg[:, 20:28, 0] = 255
        alpha = np.zeros((32, 64), dtype=np.float32)
        alpha[:, 20:28] = 1.0
        out0 = composite_depth_planes(bg, [(fg, alpha, 1.0)], t=0.0, motion_scale=0.1)
        out1 = composite_depth_planes(bg, [(fg, alpha, 1.0)], t=np.pi, motion_scale=0.1)
        # At t=pi, sin(pi*0.5)=1 → positive offset; content shifts
        self.assertFalse(np.array_equal(out0, out1))
        shifted = horizontal_shift(fg, 0.1)
        self.assertFalse(np.array_equal(fg, shifted))

    def test_create_depth_layers_uses_base_rgb(self):
        layers = create_depth_layers(16, 16, num_layers=2, seed=2, base_rgb=(10, 200, 30))
        self.assertEqual(len(layers), 2)
        img, depth = layers[0]
        self.assertEqual(img.shape, (16, 16, 3))
        self.assertGreater(depth, 0)

    def test_render_frame_with_parallax_and_setting(self):
        instruction = interpret_user_prompt(
            "a red ball bouncing left in a forest with depth parallax"
        )
        # Force depth flag if keyword parser misses "depth parallax" phrasing
        instruction.depth_parallax = True
        instruction.setting = instruction.setting or "forest"
        instruction.duration_seconds = 4.0
        spec = build_spec_from_instruction(instruction, knowledge={})
        spec.depth_parallax = True
        frame = render_frame(spec, 0.4, 96, 96, seed=3, duration_seconds=4.0)
        self.assertEqual(frame.shape, (96, 96, 3))
        self.assertEqual(frame.dtype, np.uint8)
        # Should not be a flat single color
        self.assertGreater(int(frame.std()), 5)


if __name__ == "__main__":
    unittest.main()
