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
