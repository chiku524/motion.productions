"""Tier C–E + photoreal backend scaffold tests."""
from __future__ import annotations

import unittest

import numpy as np

from src.creation.builder import build_spec_from_instruction
from src.interpretation.parser import interpret_user_prompt
from src.photoreal import EnhancedProceduralBackend, get_render_backend
from src.procedural.film import (
    apply_depth_of_field,
    apply_film_grain,
    apply_film_look,
    apply_motion_smear,
    box_blur,
    estimate_depth_map,
)
from src.procedural.parser import SceneSpec
from src.procedural.renderer import render_frame
from src.lighting.grading import get_lighting_model


class TestFilmAndMaterials(unittest.TestCase):
    def test_box_blur_softens(self):
        img = np.zeros((32, 32, 3), dtype=np.uint8)
        img[10:14, 10:14] = 255
        blurred = box_blur(img, radius=2)
        self.assertEqual(blurred.shape, img.shape)
        # Energy spreads — max drops, neighborhood rises
        self.assertLess(int(blurred[11, 11, 0]), 255)
        self.assertGreater(int(blurred[9, 11, 0]), 0)

    def test_contact_shadow_exists(self):
        from src.procedural.renderer import _contact_shadow_mask

        h = w = 48
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        xx /= w - 1
        yy /= h - 1
        shadow = _contact_shadow_mask(xx, yy, 0.5, 0.5, 0.2, get_lighting_model("noir"))
        self.assertGreater(float(shadow.max()), 0.5)
        # Shadow center below subject
        ys = np.arange(h)
        cy = float((shadow.sum(axis=1) * ys).sum() / (shadow.sum() + 1e-6))
        self.assertGreater(cy, h * 0.5)

    def test_shadow_darkens_background(self):
        from src.procedural.renderer import _accumulate_contact_shadows, _darken_with_shadows

        layers = [{
            "kind": "circle",
            "color": [255, 40, 40],
            "z": 1,
            "keyframes": [
                {"t": 0, "x": 0.5, "y": 0.5, "scale": 1.3, "rot": 0, "opacity": 1},
                {"t": 1, "x": 0.5, "y": 0.5, "scale": 1.3, "rot": 0, "opacity": 1},
            ],
        }]
        shadow = _accumulate_contact_shadows(layers, 0.0, 64, 64, lighting_preset="noir")
        self.assertGreater(float(shadow.max()), 0.15)
        bg = np.full((64, 64, 3), 180.0, dtype=np.float32)
        darkened = _darken_with_shadows(bg, shadow)
        self.assertLess(float(darkened.min()), 180.0)

    def test_dof_and_grain(self):
        frame = np.full((48, 48, 3), 120, dtype=np.uint8)
        frame[20:28, 20:28] = 220
        depth = estimate_depth_map(48, 48)
        out = apply_depth_of_field(frame, depth, focus=0.5, blur_radius=2, strength=1.5)
        self.assertEqual(out.shape, frame.shape)
        grainy = apply_film_grain(frame, "noir", seed=1, t=0.2)
        self.assertFalse(np.array_equal(frame, grainy))
        smeared = apply_motion_smear(frame, pan_dx=0.02, pan_dy=0.0)
        self.assertEqual(smeared.shape, frame.shape)

    def test_film_look_pipeline(self):
        frame = np.random.default_rng(0).integers(0, 255, (40, 40, 3), dtype=np.uint8)
        depth = estimate_depth_map(40, 40)
        out = apply_film_look(
            frame, lighting_preset="moody", seed=2, t=0.1,
            depth_map=depth, pan_dx=0.01, pan_dy=-0.005,
        )
        self.assertEqual(out.dtype, np.uint8)

    def test_realistic_style_enables_film_look(self):
        instruction = interpret_user_prompt("a realistic forest scene with soft light")
        instruction.style = "realistic"
        instruction.setting = "forest"
        instruction.duration_seconds = 4.0
        # Ensure entities so layers exist
        if not instruction.entities:
            instruction.entities = [{
                "id": "t0", "kind": "tree", "is_prop": True,
                "prop_x": 0.4, "prop_y": 0.65, "prop_scale": 1.0, "z": 0,
            }]
        spec = build_spec_from_instruction(instruction, knowledge={})
        self.assertTrue(spec.film_look)
        self.assertEqual(spec.render_engine, "enhanced")

    def test_enhanced_backend(self):
        backend = get_render_backend("photoreal")
        self.assertIsInstance(backend, EnhancedProceduralBackend)
        spec = SceneSpec(
            palette_name="default",
            motion_type="slow",
            intensity=0.7,
            raw_prompt="test",
            film_look=False,
            depth_parallax=False,
            render_engine="procedural",
            setting="forest",
            scene_layers=[{
                "kind": "tree",
                "color": [40, 140, 60],
                "z": 0,
                "keyframes": [
                    {"t": 0, "x": 0.4, "y": 0.65, "scale": 1.0, "rot": 0, "opacity": 1},
                    {"t": 1, "x": 0.4, "y": 0.65, "scale": 1.0, "rot": 0, "opacity": 1},
                ],
            }],
        )
        frame = backend.render_frame(spec, 0.2, 64, 64, seed=5)
        self.assertEqual(frame.shape, (64, 64, 3))

    def test_render_frame_film_look_flag(self):
        spec = SceneSpec(
            palette_name="default",
            motion_type="pan",
            intensity=0.8,
            raw_prompt="test",
            film_look=True,
            depth_parallax=True,
            lighting_preset="noir",
            setting="city",
            scene_layers=[{
                "kind": "building",
                "color": [80, 80, 100],
                "z": 0,
                "keyframes": [
                    {"t": 0, "x": 0.5, "y": 0.55, "scale": 1.2, "rot": 0, "opacity": 1},
                    {"t": 1, "x": 0.5, "y": 0.55, "scale": 1.2, "rot": 0, "opacity": 1},
                ],
            }],
        )
        frame = render_frame(spec, 0.3, 72, 72, seed=9)
        self.assertEqual(frame.shape, (72, 72, 3))
        self.assertGreater(int(frame.std()), 3)

    def test_composition_symmetry_pulls_center(self):
        from src.creation.scene_graph import apply_composition_symmetry_x

        self.assertAlmostEqual(apply_composition_symmetry_x(0.8, "bilateral"), 0.5 + 0.3 * 0.55, places=5)
        self.assertGreater(abs(apply_composition_symmetry_x(0.65, "asymmetric") - 0.5), abs(0.65 - 0.5))

    def test_enhanced_engine_config_sets_flags(self):
        from src.procedural.generator import ProceduralVideoGenerator
        from pathlib import Path
        import tempfile

        gen = ProceduralVideoGenerator(config={
            "output": {"width": 512, "height": 512, "fps": 24, "quality": "draft"},
            "render": {"engine": "enhanced", "upgrade_resolution": False},
        })
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "t.mp4"
            # Short clip; draft quality keeps 512
            gen.generate_clip(
                "a red ball bouncing left in a forest",
                out,
                0.5,
                seed=1,
                config={
                    "output": {"width": 512, "height": 512, "fps": 12, "quality": "draft", "dir": tmp},
                    "render": {"engine": "enhanced", "upgrade_resolution": False},
                },
            )
            spec = gen._last_spec
            self.assertEqual(spec.render_engine, "enhanced")
            self.assertTrue(spec.film_look)
            self.assertTrue(spec.depth_parallax)
            self.assertTrue(out.exists() and out.stat().st_size > 100)


if __name__ == "__main__":
    unittest.main()
