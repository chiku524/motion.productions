"""Photoreal registry consumer + authentic loop wiring."""
from __future__ import annotations

import importlib.util
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from src.creation.builder import build_spec_from_instruction
from src.interpretation.parser import interpret_user_prompt
from src.photoreal import (
    PhotorealRegistryBackend,
    bind_spec_to_registries,
    get_render_backend,
)
from src.photoreal.consumer import catalog_from_knowledge, nearest_registry_color
from src.procedural.parser import SceneSpec


def _load_automate_loop():
    path = Path(__file__).resolve().parents[1] / "scripts" / "automate_loop.py"
    spec = importlib.util.spec_from_file_location("automate_loop_photoreal_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestPhotorealConsumer(unittest.TestCase):
    def test_catalog_and_nearest(self):
        knowledge = {
            "static_colors": {
                "10,20,30": {"r": 10, "g": 20, "b": 30, "name": "color_ink"},
                "200,180,40": {"r": 200, "g": 180, "b": 40, "name": "color_sun"},
            }
        }
        catalog = catalog_from_knowledge(knowledge)
        self.assertEqual(len(catalog), 2)
        self.assertEqual(nearest_registry_color((12, 18, 28), catalog), (10, 20, 30))

    def test_bind_snaps_palette_to_registry(self):
        spec = SceneSpec(
            palette_name="default",
            motion_type="slow",
            intensity=0.7,
            raw_prompt="a realistic forest path",
            palette_colors=[(11, 19, 29), (198, 182, 44)],
            render_engine="procedural",
        )
        knowledge = {
            "static_colors": {
                "10,20,30": {"r": 10, "g": 20, "b": 30, "name": "color_ink"},
                "200,180,40": {"r": 200, "g": 180, "b": 40, "name": "color_sun"},
            }
        }
        bind_spec_to_registries(spec, knowledge)
        self.assertEqual(spec.render_engine, "photoreal")
        self.assertTrue(spec.film_look)
        self.assertTrue(spec.depth_parallax)
        self.assertEqual(spec.palette_colors, [(10, 20, 30), (200, 180, 40)])
        bind = (spec.instance or {}).get("photoreal_bind") or {}
        self.assertTrue(bind.get("bound"))
        self.assertEqual(bind.get("catalog_size"), 2)
        self.assertEqual(bind.get("sky"), (200, 180, 40))
        self.assertEqual(bind.get("ground"), (10, 20, 30))

    def test_bind_resorts_to_learned_lighting(self):
        spec = SceneSpec(
            palette_name="default",
            motion_type="slow",
            intensity=0.7,
            raw_prompt="a forest path",
            lighting_preset="neutral",
            setting="forest",
            palette_colors=[(40, 80, 50)],
        )
        bind_spec_to_registries(spec, {
            "static_colors": {"40,80,50": {"r": 40, "g": 80, "b": 50, "name": "color_moss"}},
            "learned_lighting": [{"preset": "golden_hour"}],
        })
        bind = (spec.instance or {}).get("photoreal_bind") or {}
        self.assertEqual(bind.get("lighting"), "golden_hour")
        self.assertEqual(spec.lighting_preset, "golden_hour")
        self.assertEqual(bind.get("texture"), "noise")

    def test_photoreal_backend_grades_frame(self):
        backend = get_render_backend("photoreal")
        self.assertIsInstance(backend, PhotorealRegistryBackend)
        spec = SceneSpec(
            palette_name="default",
            motion_type="slow",
            intensity=0.8,
            raw_prompt="golden hour forest",
            lighting_preset="golden_hour",
            setting="forest",
            palette_colors=[(210, 170, 80), (40, 80, 50)],
            film_look=False,
            depth_parallax=False,
            render_engine="photoreal",
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
        bind_spec_to_registries(spec, {
            "static_colors": {
                "210,170,80": {"r": 210, "g": 170, "b": 80, "name": "color_amber"},
                "40,80,50": {"r": 40, "g": 80, "b": 50, "name": "color_moss"},
            }
        })
        frame = backend.render_frame(spec, 0.2, 64, 64, seed=5)
        self.assertEqual(frame.shape, (64, 64, 3))
        self.assertEqual(frame.dtype, np.uint8)
        # Grade should not collapse to a single color
        self.assertGreater(len(np.unique(frame.reshape(-1, 3), axis=0)), 20)

    def test_realistic_prompt_selects_photoreal_engine(self):
        instruction = interpret_user_prompt("a photoreal forest path at golden hour")
        instruction.style = "photoreal"
        instruction.setting = "forest"
        instruction.duration_seconds = 5.0
        spec = build_spec_from_instruction(instruction, knowledge={})
        self.assertEqual(spec.render_engine, "photoreal")
        self.assertTrue(spec.film_look)

    def test_entity_setting_scene_selects_photoreal(self):
        instruction = interpret_user_prompt("a person walks through a forest")
        instruction.duration_seconds = 5.0
        spec = build_spec_from_instruction(instruction, knowledge={})
        self.assertEqual(spec.render_engine, "photoreal")
        self.assertTrue(spec.film_look)
        self.assertTrue(spec.scene_layers)

    def test_pixel_pairing_stays_procedural(self):
        instruction = interpret_user_prompt(
            "pixel pairing: color_ink paired with color_sun, static frame"
        )
        instruction.duration_seconds = 1.0
        spec = build_spec_from_instruction(instruction, knowledge={})
        self.assertEqual(spec.render_engine, "procedural")
        self.assertEqual(spec.creation_mode, "pure_per_frame")


class TestPhotorealEnvironment(unittest.TestCase):
    def test_plate_has_sky_over_ground(self):
        from src.photoreal.environment import render_environment_plate

        spec = SceneSpec(
            palette_name="default",
            motion_type="slow",
            intensity=0.8,
            raw_prompt="forest",
            setting="forest",
            lighting_preset="golden_hour",
            palette_colors=[(210, 180, 90), (40, 70, 40)],
            instance={"horizon": 0.60, "photoreal_bind": {
                "sky": (210, 180, 90),
                "ground": (40, 70, 40),
                "setting": "forest",
                "texture": "noise",
                "lighting": "golden_hour",
                "palette": [(210, 180, 90), (40, 70, 40)],
            }},
        )
        plate = render_environment_plate(64, 64, spec, seed=3)
        self.assertEqual(plate.shape, (64, 64, 3))
        top = plate[:16].astype(np.float32).mean()
        bottom = plate[48:].astype(np.float32).mean()
        self.assertGreater(top, bottom, "sky should read brighter than ground")

    def test_composite_keeps_subject(self):
        from src.photoreal.environment import composite_environment, render_environment_plate

        spec = SceneSpec(
            palette_name="default",
            motion_type="slow",
            intensity=0.8,
            raw_prompt="forest",
            setting="forest",
            scene_layers=[{
                "kind": "circle",
                "color": [255, 0, 0],
                "z": 2,
                "keyframes": [
                    {"t": 0, "x": 0.5, "y": 0.45, "scale": 1.6, "rot": 0, "opacity": 1},
                    {"t": 1, "x": 0.5, "y": 0.45, "scale": 1.6, "rot": 0, "opacity": 1},
                ],
            }],
            instance={"photoreal_bind": {
                "sky": (180, 200, 220),
                "ground": (50, 60, 40),
                "setting": "forest",
                "lighting": "neutral",
            }},
        )
        env = render_environment_plate(48, 48, spec, seed=1)
        frame = np.zeros((48, 48, 3), dtype=np.uint8)
        frame[16:32, 16:32] = (255, 0, 0)
        out = composite_environment(frame, env, spec, t=0.2)
        # Center of the stamped subject should stay closer to red than to the env plate
        center = out[24, 24].astype(np.float32)
        self.assertGreater(center[0], 80.0)


class TestPhotorealMesh(unittest.TestCase):
    def test_recipe_loader_scales_with_form(self):
        from src.photoreal.mesh import mesh_recipe_for_kind

        tree = mesh_recipe_for_kind("tree")
        roles = {p["role"] for p in tree}
        self.assertIn("trunk", roles)
        self.assertIn("canopy", roles)
        big = mesh_recipe_for_kind("character", {"radius_mul": 1.4, "head_scale": 0.55})
        small = mesh_recipe_for_kind("character", {"radius_mul": 0.8, "head_scale": 0.38})
        big_head = next(p for p in big if p["role"] == "head")
        small_head = next(p for p in small if p["role"] == "head")
        self.assertGreater(big_head["rx"], small_head["rx"])

    def test_sphere_key_side_is_brighter(self):
        from src.lighting.grading import get_lighting_model
        from src.photoreal.mesh import mesh_recipe_for_kind, rasterize_parts

        h = w = 48
        y = np.linspace(0.0, 1.0, h, dtype=np.float32)
        x = np.linspace(0.0, 1.0, w, dtype=np.float32)
        yy = np.broadcast_to(y[:, None], (h, w))
        xx = np.broadcast_to(x[None, :], (h, w))
        parts = mesh_recipe_for_kind("circle")
        rgb, a = rasterize_parts(
            parts, xx, yy, 0.5, 0.5, 0.28, (200, 80, 60), get_lighting_model("neutral"),
        )
        self.assertGreater(float(a.mean()), 0.08)
        # Key is upper-left — that quadrant should be brighter than lower-right
        ul = rgb[:20, :20][a[:20, :20] > 0.5].mean()
        lr = rgb[28:, 28:][a[28:, 28:] > 0.5].mean()
        self.assertGreater(ul, lr)

    def test_overlay_covers_subject(self):
        from src.photoreal.mesh import overlay_mesh_subjects

        spec = SceneSpec(
            palette_name="default",
            motion_type="slow",
            intensity=0.8,
            raw_prompt="a person in a forest",
            setting="forest",
            lighting_preset="golden_hour",
            scene_layers=[{
                "kind": "character",
                "color": [200, 90, 70],
                "z": 2,
                "form": {"kind": "character", "radius_mul": 1.1, "head_scale": 1.0, "body_scale": 1.0},
                "keyframes": [
                    {"t": 0, "x": 0.5, "y": 0.55, "scale": 1.5, "rot": 0, "opacity": 1},
                    {"t": 1, "x": 0.5, "y": 0.55, "scale": 1.5, "rot": 0, "opacity": 1},
                ],
            }],
        )
        frame = np.zeros((64, 64, 3), dtype=np.uint8)
        out = overlay_mesh_subjects(frame, spec, t=0.2)
        self.assertGreater(float(out.mean()), 4.0)
        self.assertGreater(len(np.unique(out.reshape(-1, 3), axis=0)), 8)


class TestLoopAuthenticityWiring(unittest.TestCase):
    def test_resolve_duration_honors_balanced_env(self):
        mod = _load_automate_loop()
        dur = mod.resolve_loop_duration(
            workflow_type="main",
            api_duration=None,
            learning_duration=1.0,
            run_count=0,
            cli_duration=5.0,
            env_duration="5",
        )
        self.assertEqual(dur, 5.0)

    def test_resolve_duration_explorer_uses_learning(self):
        mod = _load_automate_loop()
        dur = mod.resolve_loop_duration(
            workflow_type="explorer",
            api_duration=None,
            learning_duration=1.0,
            run_count=0,
            cli_duration=5.0,
            env_duration=None,
        )
        self.assertEqual(dur, 1.0)

    def test_resolve_duration_cartoon_clamped(self):
        mod = _load_automate_loop()
        dur = mod.resolve_loop_duration(
            workflow_type="cartoon",
            api_duration=None,
            learning_duration=1.0,
            run_count=0,
            cli_duration=5.0,
            env_duration="2.5",
        )
        self.assertEqual(dur, 2.5)

    def test_window_pick_prompt_prefers_mini_scene(self):
        mod = _load_automate_loop()
        old_focus = os.environ.get("LOOP_EXTRACTION_FOCUS")
        old_wf = os.environ.get("LOOP_WORKFLOW_TYPE")
        os.environ["LOOP_EXTRACTION_FOCUS"] = "window"
        os.environ["LOOP_WORKFLOW_TYPE"] = "main"
        try:
            with patch.object(mod, "secure_random", return_value=0.1):
                with patch(
                    "src.automation.prompt_gen.generate_mini_scene_prompt",
                    return_value="a person walks through a kitchen then opens a window",
                ):
                    prompt, meta = mod.pick_prompt({"recent_prompts": []}, knowledge={}, coverage={})
        finally:
            if old_focus is None:
                os.environ.pop("LOOP_EXTRACTION_FOCUS", None)
            else:
                os.environ["LOOP_EXTRACTION_FOCUS"] = old_focus
            if old_wf is None:
                os.environ.pop("LOOP_WORKFLOW_TYPE", None)
            else:
                os.environ["LOOP_WORKFLOW_TYPE"] = old_wf
        self.assertEqual(meta.get("source"), "mini_scene")
        self.assertTrue(meta.get("use_photoreal"))
        self.assertTrue(meta.get("authentic"))
        self.assertIn("kitchen", prompt)

    def test_evaluate_iteration_requires_novel_and_growth(self):
        from src.knowledge.loop_authenticity import evaluate_iteration

        ok = evaluate_iteration(
            source="mini_scene",
            prompt="a person walks through a sunlit kitchen",
            recent=["ocean dusk, calm"],
            knowledge={"static_colors": {"1,2,3": {}}},
            growth_ran=True,
            growth_added={"narrative": 1},
            render_engine="photoreal",
            worker="main",
        )
        self.assertTrue(ok["authentic"])
        self.assertEqual(ok["novel_rows"], 1)

        dup = evaluate_iteration(
            source="mini_scene",
            prompt="a person walks through a sunlit kitchen",
            recent=["a person walks through a sunlit kitchen"],
            knowledge={"static_colors": {"1,2,3": {}}},
            growth_ran=True,
            growth_added={"narrative": 1},
            render_engine="photoreal",
        )
        self.assertFalse(dup["authentic"])
        self.assertFalse(dup["novel_prompt"])

        missing_engine = evaluate_iteration(
            source="mini_scene",
            prompt="a cyclist rolls past a bakery at dusk",
            recent=[],
            knowledge={"static_colors": {}},
            growth_ran=True,
            growth_added={"narrative": 1},
            render_engine="procedural",
        )
        self.assertFalse(missing_engine["authentic"])
        self.assertFalse(missing_engine["photoreal_bound"])


if __name__ == "__main__":
    unittest.main()
