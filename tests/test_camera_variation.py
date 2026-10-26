"""Opt-in seeded camera variation for pixel-field clips (LOOP_CAMERA_VARIATION, default off)."""
from __future__ import annotations

import os
import unittest
from unittest import mock

import numpy as np

from src.procedural.camera_variation import (
    FIELD_CAMERA_CHOICES,
    camera_variation_enabled,
    field_camera_params,
    pick_field_camera,
)

_PROMPT = (
    "pixel pairing frame of red and blue with a thump sound pairing"
)


def _build(seed: int, duration: float = 1.0):
    from src.creation.builder import build_spec_from_instruction
    from src.interpretation.parser import interpret_user_prompt

    inst = interpret_user_prompt(_PROMPT)
    inst.duration_seconds = duration
    return build_spec_from_instruction(inst, knowledge={}, creation_seed=seed)


def _window_spec(seed: int):
    """A field spec that is clearly in the pairing path (colors + pure_per_frame)."""
    from src.procedural.parser import SceneSpec

    return SceneSpec(
        palette_name="default",
        motion_type="drift",
        palette_colors=[(200, 30, 30), (30, 30, 200)],
        intensity=0.6,
        raw_prompt="field",
        pure_colors=[(200, 30, 30), (30, 30, 200), (240, 220, 40)],
        creation_mode="pure_per_frame",
        motion_level=9.0,
        camera_motion="static",
    )


class FlagTests(unittest.TestCase):
    def test_default_off(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LOOP_CAMERA_VARIATION", None)
            self.assertFalse(camera_variation_enabled())

    def test_truthy_values(self):
        for v in ("1", "true", "YES", "on"):
            with mock.patch.dict(os.environ, {"LOOP_CAMERA_VARIATION": v}):
                self.assertTrue(camera_variation_enabled(), v)
        for v in ("", "0", "false", "no"):
            with mock.patch.dict(os.environ, {"LOOP_CAMERA_VARIATION": v}):
                self.assertFalse(camera_variation_enabled(), v)


class PickAndParamsTests(unittest.TestCase):
    def test_pick_is_seeded_and_varied(self):
        picks = [pick_field_camera(s) for s in range(200)]
        self.assertEqual(picks, [pick_field_camera(s) for s in range(200)])
        self.assertTrue(set(picks) <= set(FIELD_CAMERA_CHOICES))
        self.assertGreaterEqual(len(set(picks)), 6)
        self.assertLess(picks.count("static") / len(picks), 0.25)

    def test_static_is_identity(self):
        self.assertEqual(field_camera_params("static", 0.7, 3), (1.0, 0.0, 0.0, 0.0))
        self.assertEqual(field_camera_params("nonsense", 0.7, 3), (1.0, 0.0, 0.0, 0.0))

    def test_moves_are_visible_within_one_second(self):
        for cam in FIELD_CAMERA_CHOICES:
            if cam == "static":
                continue
            p0 = field_camera_params(cam, 0.0, 11)
            p1 = field_camera_params(cam, 1.0, 11)
            delta = max(abs(a - b) for a, b in zip(p0, p1))
            self.assertGreater(delta, 0.03, cam)

    def test_params_deterministic_and_seed_dependent(self):
        self.assertEqual(field_camera_params("pan", 0.5, 1), field_camera_params("pan", 0.5, 1))
        seen = {field_camera_params("pan", 1.0, s) for s in range(20)}
        self.assertGreater(len(seen), 10)


class BuilderTests(unittest.TestCase):
    def test_flag_off_stays_static(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LOOP_CAMERA_VARIATION", None)
            for seed in range(12):
                spec = _build(seed)
                self.assertEqual(spec.camera_motion, "static")
                self.assertFalse((spec.instance or {}).get("camera_variation"))

    def test_flag_on_varies_and_is_reproducible(self):
        with mock.patch.dict(os.environ, {"LOOP_CAMERA_VARIATION": "1"}):
            first = [_build(s) for s in range(40)]
            again = [_build(s) for s in range(40)]
        cams = [s.camera_motion for s in first]
        self.assertEqual(cams, [s.camera_motion for s in again])
        self.assertGreaterEqual(len(set(cams)), 5)
        for s in first:
            self.assertEqual(s.camera_steadiness, "locked")
            moving = s.camera_motion != "static"
            self.assertEqual(bool((s.instance or {}).get("camera_variation")), moving)


class RendererTests(unittest.TestCase):
    W, H = 48, 32

    def _frame(self, spec, t):
        from src.procedural.renderer import render_frame

        return render_frame(spec, t, self.W, self.H, seed=77, duration_seconds=1.0)

    def test_variation_flag_on_spec_moves_the_field(self):
        base = _window_spec(1)
        moved = _window_spec(1)
        moved.camera_motion = "zoom"
        moved.instance = {"camera_variation": True}
        a0, b0 = self._frame(base, 0.0), self._frame(moved, 0.0)
        a1, b1 = self._frame(base, 0.9), self._frame(moved, 0.9)
        self.assertTrue(np.array_equal(a0, b0))  # zoom starts at identity
        self.assertFalse(np.array_equal(a1, b1))  # and has moved by t=0.9

    def test_without_instance_flag_camera_is_ignored(self):
        """Legacy behaviour: a non-static camera on a field spec does not change pixels."""
        base = _window_spec(1)
        other = _window_spec(1)
        other.camera_motion = "pan"
        self.assertTrue(np.array_equal(self._frame(base, 0.8), self._frame(other, 0.8)))

    def test_deterministic_and_each_move_differs(self):
        frames = {}
        for cam in FIELD_CAMERA_CHOICES:
            spec = _window_spec(1)
            spec.camera_motion = cam
            spec.instance = {"camera_variation": True}
            f = self._frame(spec, 0.8)
            self.assertTrue(np.array_equal(f, self._frame(spec, 0.8)))
            frames[cam] = f
        legacy = frames["static"]
        for cam, f in frames.items():
            if cam != "static":
                self.assertFalse(np.array_equal(f, legacy), cam)

    def test_end_to_end_flag_on(self):
        from src.procedural.renderer import render_frame

        with mock.patch.dict(os.environ, {"LOOP_CAMERA_VARIATION": "1"}):
            specs = [_build(s) for s in range(30)]
        moving = [s for s in specs if (s.instance or {}).get("camera_variation")]
        self.assertTrue(moving)
        s = moving[0]
        again = render_frame(s, 0.9, self.W, self.H, seed=5, duration_seconds=1.0)
        s.instance = {**s.instance, "camera_variation": False}
        flat = render_frame(s, 0.9, self.W, self.H, seed=5, duration_seconds=1.0)
        self.assertFalse(np.array_equal(again, flat))


if __name__ == "__main__":
    unittest.main()