"""Look-matching algorithms: Oklab color, keyframe easing, subject camera lock."""
from __future__ import annotations

import unittest

import numpy as np

from src.creation.builder import build_spec_from_instruction
from src.creation.scene_graph import sample_layer_at
from src.interpretation.parser import interpret_user_prompt
from src.knowledge.blending import blend_colors
from src.knowledge.color_space import lerp_rgb_oklab, nearest_palette_color
from src.lighting.grading import apply_style_look
from src.procedural.look import camera_for_subject_motion, composition_offset, ease_unit


class TestLookAlgorithms(unittest.TestCase):
    def test_oklab_roundtrip_primary(self):
        for rgb in ((255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255), (0, 0, 0)):
            back = lerp_rgb_oklab(rgb, rgb, 0.0)
            self.assertEqual(back, rgb)

    def test_oklab_blue_yellow_stays_chromatic(self):
        """RGB lerp of blue+yellow is gray; Oklab should keep chroma (greenish)."""
        mid = lerp_rgb_oklab((0, 0, 255), (255, 255, 0), 0.5)
        chroma = abs(mid[0] - mid[1]) + abs(mid[1] - mid[2]) + abs(mid[0] - mid[2])
        self.assertGreater(chroma, 40, f"expected chromatic midpoint, got {mid}")
        # Should not collapse to near-gray
        self.assertFalse(all(abs(c - 128) < 20 for c in mid))

    def test_blend_colors_linear_uses_oklab(self):
        blended = blend_colors((0, 0, 255), (255, 255, 0), weight=0.5, approach="linear")
        rgb_mid = (127, 127, 127)
        self.assertNotEqual(blended, rgb_mid)

    def test_nearest_palette_prefers_same_hue(self):
        pal = [(20, 40, 180), (40, 160, 70), (220, 50, 40)]
        self.assertEqual(nearest_palette_color((230, 40, 40), pal), (220, 50, 40))

    def test_ease_jerky_is_stepped(self):
        self.assertEqual(ease_unit(0.42, "jerky"), 0.4)
        self.assertEqual(ease_unit(0.49, "jerky"), 0.4)
        self.assertAlmostEqual(ease_unit(0.5, "smooth"), 0.5)
        self.assertLess(ease_unit(0.25, "smooth"), 0.25)

    def test_sample_layer_easing_differs_from_linear_ends(self):
        layer = {
            "kind": "circle",
            "bounce": False,
            "keyframes": [
                {"t": 0.0, "x": 0.0, "y": 0.5, "scale": 1.0, "rot": 0.0, "opacity": 1.0},
                {"t": 1.0, "x": 1.0, "y": 0.5, "scale": 1.0, "rot": 0.0, "opacity": 1.0},
            ],
        }
        mid_smooth = sample_layer_at(layer, 0.25, smoothness="smooth")
        mid_jerky = sample_layer_at(layer, 0.25, smoothness="jerky")
        self.assertLess(mid_smooth["x"], 0.25)
        self.assertEqual(mid_jerky["x"], 0.2)

    def test_composition_thirds(self):
        dx, _ = composition_offset("left_heavy")
        self.assertAlmostEqual(dx, -1.0 / 6.0, places=5)
        self.assertLess(abs(composition_offset("left_heavy", "close")[0]), abs(dx))

    def test_camera_for_walk_is_tracking(self):
        self.assertEqual(
            camera_for_subject_motion([{"kind": "character", "trajectory": "left"}]),
            "tracking",
        )
        self.assertEqual(
            camera_for_subject_motion([{"kind": "circle", "trajectory": "left", "bounce": True}]),
            "static",
        )
        self.assertEqual(
            camera_for_subject_motion([{"kind": "character", "trajectory": "toward"}]),
            "dolly",
        )

    def test_builder_locks_camera_for_walk(self):
        instruction = interpret_user_prompt("a person walking left")
        instruction.duration_seconds = 5.0
        spec = build_spec_from_instruction(instruction, knowledge={})
        self.assertEqual(spec.camera_motion, "tracking")

    def test_builder_locks_camera_for_bounce(self):
        instruction = interpret_user_prompt("a red ball bouncing left")
        instruction.duration_seconds = 5.0
        spec = build_spec_from_instruction(instruction, knowledge={})
        self.assertEqual(spec.camera_motion, "static")

    def test_builder_setting_gradient_ocean(self):
        instruction = interpret_user_prompt("waves in the ocean")
        instruction.setting = "ocean"
        instruction.duration_seconds = 4.0
        spec = build_spec_from_instruction(instruction, knowledge={})
        self.assertEqual(spec.gradient_type, "horizontal")
        self.assertEqual(spec.lighting_preset, "documentary")

    def test_anime_style_adds_ink_edges(self):
        frame = np.zeros((24, 24, 3), dtype=np.uint8)
        frame[8:16, 8:16] = [80, 140, 200]
        anime = apply_style_look(frame, "anime")
        # Interior of the square should differ from a flat grade of the same fill
        self.assertFalse(np.array_equal(frame, anime))
        # Edge pixels around the square should be darker than the fill center
        center = int(anime[12, 12].mean())
        edge = int(anime[8, 12].mean())
        self.assertLess(edge, center)

    def test_oklab_palette_lerp_vectorized(self):
        from src.knowledge.color_space import lerp_palette_oklab_arrays

        pal = [(0, 0, 255), (255, 255, 0)]
        i0 = np.zeros((4, 4), dtype=np.int32)
        i1 = np.ones((4, 4), dtype=np.int32)
        frac = np.full((4, 4), 0.5, dtype=np.float32)
        r, g, b = lerp_palette_oklab_arrays(pal, i0, i1, frac)
        chroma = abs(float(r[0, 0]) - float(g[0, 0])) + abs(float(g[0, 0]) - float(b[0, 0]))
        self.assertGreater(chroma, 40)


if __name__ == "__main__":
    unittest.main()
