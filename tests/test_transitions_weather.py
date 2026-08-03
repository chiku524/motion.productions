"""Transitions, weather, steadiness, rhythm, temperature improvements."""
from __future__ import annotations

import unittest

import numpy as np

from src.cinematography.transitions import apply_transition, cross_blend
from src.creation.builder import build_spec_from_instruction
from src.interpretation.parser import interpret_user_prompt
from src.procedural.motion import get_camera_params, rhythm_modulation, steadiness_shake
from src.procedural.renderer import _apply_weather_overlay, render_frame
from src.audio.event_sfx import cut_accent_events
from src.lighting.grading import apply_color_temperature


class TestNextPassImprovements(unittest.TestCase):
    def test_cross_dissolve_differs_from_fade(self):
        a = np.full((24, 32, 3), 10, dtype=np.uint8)
        b = np.full((24, 32, 3), 200, dtype=np.uint8)
        mid = cross_blend(a, b, 0.5, "dissolve")
        self.assertGreater(int(mid.mean()), 80)
        self.assertLess(int(mid.mean()), 140)
        faded = apply_transition(b, 0.5, 1.0, "fade", is_in=True)
        # Dissolve mid blends two frames; fade only scales toward black from one
        self.assertFalse(np.array_equal(mid, faded))
        # With dark partner, dissolve sits between 10 and 200
        self.assertAlmostEqual(int(mid.mean()), 105, delta=5)

    def test_cross_wipe_reveals_incoming(self):
        a = np.zeros((20, 40, 3), dtype=np.uint8)
        b = np.full((20, 40, 3), 255, dtype=np.uint8)
        out = cross_blend(a, b, 0.5, "wipe")
        self.assertGreater(int(out[:, :15].mean()), 200)
        self.assertLess(int(out[:, 25:].mean()), 30)

    def test_rain_overlay_changes_pixels(self):
        frame = np.full((64, 64, 3), 80, dtype=np.uint8)
        wet = _apply_weather_overlay(frame, "rain", 0.4, seed=3)
        self.assertFalse(np.array_equal(frame, wet))
        snow = _apply_weather_overlay(frame, "snow", 0.4, seed=3)
        self.assertFalse(np.array_equal(frame, snow))

    def test_handheld_and_steadiness(self):
        z, px, py, r = get_camera_params("handheld", 0.7)
        self.assertNotEqual((px, py, r), (0.0, 0.0, 0.0))
        sx, sy, sr = steadiness_shake("shaky", 0.5)
        self.assertGreater(abs(sx) + abs(sy) + abs(sr), 0.01)
        self.assertEqual(steadiness_shake("locked", 0.5), (0.0, 0.0, 0.0))

    def test_rhythm_modulation(self):
        self.assertEqual(rhythm_modulation("steady", 0.3), 1.0)
        self.assertNotEqual(rhythm_modulation("pulsing", 0.3), 1.0)

    def test_cut_accents_by_transition(self):
        events = cut_accent_events([1.0, 2.0, 3.0], transition_types=["cut", "dissolve", "wipe"])
        kinds = [e["kind"] for e in events]
        self.assertEqual(kinds[0], "click")
        self.assertEqual(kinds[1], "whoosh")
        self.assertEqual(kinds[2], "whoosh")

    def test_color_temperature_warm_vs_cool(self):
        frame = np.full((16, 16, 3), 128, dtype=np.uint8)
        warm = apply_color_temperature(frame, "warm")
        cool = apply_color_temperature(frame, "cool")
        self.assertGreater(int(warm[..., 0].mean()), int(cool[..., 0].mean()))

    def test_snow_setting_and_steadiness_on_spec(self):
        instruction = interpret_user_prompt("a red ball bouncing in the snow with handheld camera")
        instruction.duration_seconds = 4.0
        spec = build_spec_from_instruction(instruction, knowledge={})
        self.assertEqual(spec.setting, "snow")
        self.assertIn(spec.camera_steadiness, ("handheld", "shaky", "stable"))
        frame = render_frame(spec, 0.3, 64, 64, seed=2)
        self.assertEqual(frame.shape, (64, 64, 3))

    def test_educational_arrow_flag(self):
        instruction = interpret_user_prompt("explain gravity in 2 minutes")
        instruction.duration_seconds = 120.0
        spec = build_spec_from_instruction(instruction, knowledge={})
        self.assertTrue(any(b.get("arrow") for b in (spec.script_beats or [])))


if __name__ == "__main__":
    unittest.main()
