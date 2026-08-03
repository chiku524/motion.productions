"""Gags, tension curves, weather SFX, spotlight, style, multi-shot duration."""
from __future__ import annotations

import unittest

import numpy as np

from src.audio.event_sfx import infer_weather_events
from src.creation.builder import build_spec_from_instruction
from src.creation.scene_script import build_scene_script_from_instruction
from src.depth.layers import create_depth_layers
from src.graphics.primitives import draw_spotlight
from src.interpretation.parser import interpret_user_prompt
from src.lighting.grading import apply_style_look
from src.narrative.story import get_tension_at
from src.procedural.renderer import render_frame


class TestFidelityPass(unittest.TestCase):
    def test_tension_curves_differ(self):
        mid_std = get_tension_at(0.5, "standard")
        mid_flat = get_tension_at(0.5, "flat")
        early_imm = get_tension_at(0.2, "immediate")
        late_slow = get_tension_at(0.2, "slow_build")
        self.assertAlmostEqual(mid_flat, 0.55, places=2)
        self.assertGreater(early_imm, late_slow)
        self.assertNotAlmostEqual(mid_std, mid_flat, places=2)

    def test_rain_weather_drips(self):
        ev = infer_weather_events("rain", 5.0)
        self.assertTrue(ev)
        self.assertTrue(all(e["kind"] == "drip" for e in ev))
        snow = infer_weather_events("snow", 5.0)
        self.assertTrue(all(e["kind"] == "rustle" for e in snow))

    def test_spin_gag_not_wiped_by_walk_cycle(self):
        instruction = interpret_user_prompt("a character flourishes and spins left")
        # Force character + spin gag
        instruction.entities = [{
            "id": "c0",
            "kind": "character",
            "trajectory": "left",
            "gag": "spin",
            "expression": "excited",
            "personality": "playful",
        }]
        instruction.duration_seconds = 5.0
        spec = build_spec_from_instruction(instruction, knowledge={})
        chars = [L for L in (spec.scene_layers or []) if L.get("kind") == "character"]
        self.assertTrue(chars)
        # Spin gag should keep rotation keyframes (not flat walk)
        rots = [abs(float(k.get("rot") or 0)) for L in chars for k in (L.get("keyframes") or [])]
        self.assertGreater(max(rots or [0]), 0.5)

    def test_multi_shot_duration_sums(self):
        instruction = interpret_user_prompt("educational documentary about cities")
        instruction.genre = "educational"
        instruction.duration_seconds = 12.0
        script = build_scene_script_from_instruction(instruction, duration_seconds=12.0)
        total = sum(s.duration_seconds for s in script.shots)
        self.assertAlmostEqual(total, 12.0, places=1)
        self.assertGreaterEqual(len(script.shots), 2)

    def test_atmosphere_setting_tint(self):
        forest = create_depth_layers(24, 24, num_layers=1, seed=1, base_rgb=(100, 100, 100), setting="forest")
        rain = create_depth_layers(24, 24, num_layers=1, seed=1, base_rgb=(100, 100, 100), setting="rain")
        self.assertFalse(np.array_equal(forest[0][0], rain[0][0]))

    def test_spotlight_darkens_edges(self):
        frame = np.full((48, 48, 3), 180, dtype=np.uint8)
        out = draw_spotlight(frame, (24, 24), radius=10, darkness=0.5)
        self.assertLess(int(out[0, 0, 0]), int(out[24, 24, 0]))

    def test_anime_style_look(self):
        frame = np.full((20, 20, 3), [80, 120, 160], dtype=np.uint8)
        anime = apply_style_look(frame, "anime")
        minimal = apply_style_look(frame, "minimal")
        self.assertFalse(np.array_equal(frame, anime))
        self.assertFalse(np.array_equal(anime, minimal))

    def test_rain_spec_includes_drip_sfx(self):
        instruction = interpret_user_prompt("a red ball bouncing in the rain")
        instruction.duration_seconds = 5.0
        instruction.setting = "rain"
        spec = build_spec_from_instruction(instruction, knowledge={})
        kinds = [e.get("kind") for e in (spec.sfx_events or []) if isinstance(e, dict)]
        self.assertIn("drip", kinds)
        frame = render_frame(spec, 0.4, 64, 64, seed=1)
        self.assertEqual(frame.shape, (64, 64, 3))


if __name__ == "__main__":
    unittest.main()
