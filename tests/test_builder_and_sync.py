"""
Unit tests for critical registry-affecting paths (REGISTRY_AND_WORKFLOW_IMPROVEMENTS Part 0 §2.7).
Run from project root: python -m pytest tests/ -v
Or: python -m unittest discover -s tests -p "test_*.py" -v
"""
import unittest


class TestBuilderAndSync(unittest.TestCase):
    """Registry-affecting creation and sync (builder pure color pool, growth_metrics)."""

    def test_build_pure_color_pool_empty_knowledge(self):
        """_build_pure_color_pool with no knowledge returns at least origin primitives."""
        from src.creation.builder import _build_pure_color_pool
        from src.interpretation.schema import InterpretedInstruction

        instruction = InterpretedInstruction(raw_prompt="test", palette_name="default", motion_type="flow", intensity=0.5)
        pool = _build_pure_color_pool(None, instruction, avoid_palette=set())
        self.assertIsInstance(pool, list)
        self.assertGreaterEqual(len(pool), 16)  # COLOR_ORIGIN_PRIMITIVES has 16
        for item in pool:
            self.assertIsInstance(item, tuple)
            self.assertEqual(len(item), 3)
            self.assertTrue(all(0 <= c <= 255 for c in item))

    def test_build_pure_color_pool_pair_count_is_unique_combo(self):
        from src.creation.builder import _build_pure_color_pool
        from src.interpretation.schema import InterpretedInstruction

        instruction = InterpretedInstruction(
            raw_prompt="static frame: amber veil paired with teal mist",
            palette_name="default",
            motion_type="flow",
            intensity=0.5,
        )
        knowledge = {
            "color_by_name": {
                "amber veil": {"r": 200, "g": 140, "b": 40},
                "teal mist": {"r": 20, "g": 160, "b": 170},
            },
            "static_colors": {
                "k1": {"r": 200, "g": 140, "b": 40, "name": "amber veil", "count": 1},
                "k2": {"r": 20, "g": 160, "b": 170, "name": "teal mist", "count": 1},
                "k3": {"r": 9, "g": 9, "b": 9, "name": "void ink", "count": 40},
            },
        }
        pool = _build_pure_color_pool(
            knowledge, instruction, avoid_palette=set(), pair_count=2, seed=11
        )
        self.assertEqual(len(pool), 2)
        self.assertEqual(len(set(pool)), 2)
        self.assertIn((200, 140, 40), pool)
        self.assertIn((20, 160, 170), pool)

    def test_build_pure_color_pool_with_static_and_learned(self):
        """_build_pure_color_pool prefers static_colors; learned_colors only if static is empty."""
        from src.creation.builder import _build_pure_color_pool
        from src.interpretation.schema import InterpretedInstruction

        instruction = InterpretedInstruction(raw_prompt="test", palette_name="default", motion_type="flow", intensity=0.5)
        knowledge = {
            "static_colors": {
                "key1": {"r": 10, "g": 20, "b": 30},
                "key2": {"r": 255, "g": 0, "b": 0},
            },
            "learned_colors": {
                "lc1": {"r": 100, "g": 150, "b": 200},
            },
        }
        pool = _build_pure_color_pool(knowledge, instruction, avoid_palette=set())
        self.assertIn((10, 20, 30), pool)
        self.assertNotIn((100, 150, 200), pool)
        self.assertTrue(any(c == (255, 0, 0) for c in pool))
        self.assertGreaterEqual(len(pool), 17)

        learned_only = {
            "static_colors": {},
            "learned_colors": {"lc1": {"r": 100, "g": 150, "b": 200}},
        }
        pool2 = _build_pure_color_pool(learned_only, instruction, avoid_palette=set())
        self.assertIn((100, 150, 200), pool2)

    def test_build_pure_color_pool_clamps_rgb(self):
        """_build_pure_color_pool clamps RGB to 0-255."""
        from src.creation.builder import _build_pure_color_pool
        from src.interpretation.schema import InterpretedInstruction

        instruction = InterpretedInstruction(raw_prompt="test", palette_name="default", motion_type="flow", intensity=0.5)
        knowledge = {
            "static_colors": {
                "k1": {"r": -1, "g": 300, "b": 128},
            },
        }
        pool = _build_pure_color_pool(knowledge, instruction, avoid_palette=set())
        self.assertIn((0, 255, 128), pool)  # clamped

    def test_growth_metrics(self):
        """growth_metrics returns total, static, dynamic, and by_aspect."""
        from src.knowledge.remote_sync import growth_metrics

        added = {
            "static_colors": 2,
            "static_sound": 1,
            "dynamic_motion": 3,
            "dynamic_lighting": 0,
            "dynamic_gradient": 1,
        }
        m = growth_metrics(added)
        self.assertEqual(m["total_added"], 2 + 1 + 3 + 1)
        self.assertEqual(m["static_added"], 3)
        self.assertEqual(m["dynamic_added"], 4)
        self.assertEqual(m["by_aspect"]["static_colors"], 2)
        self.assertEqual(m["by_aspect"]["dynamic_motion"], 3)
        self.assertNotIn("dynamic_lighting", m["by_aspect"])


class TestMotionRecipes(unittest.TestCase):
    """Numeric motion recipes must not collapse learned_motion onto five enum labels."""

    def test_learned_level_copied_onto_spec(self):
        from src.creation.builder import build_spec_from_instruction
        from src.interpretation.schema import InterpretedInstruction

        instruction = InterpretedInstruction(
            raw_prompt="abstract color field",
            palette_name="default",
            motion_type="flow",
            intensity=0.5,
        )
        knowledge = {
            "learned_motion": [
                {
                    "motion_level": 22.4,
                    "motion_std": 4.1,
                    "motion_trend": "steady",
                    "motion_direction": "horizontal",
                    "motion_rhythm": "pulsing",
                    "count": 1,
                },
            ],
        }
        spec = build_spec_from_instruction(instruction, knowledge=knowledge)
        self.assertAlmostEqual(spec.motion_level, 22.4, places=1)
        self.assertAlmostEqual(spec.motion_std, 4.1, places=1)
        self.assertEqual(spec.motion_rhythm, "pulsing")
        self.assertEqual(spec.motion_directionality, "horizontal")
        self.assertEqual(spec.motion_type, "pulse")

    def test_explicit_motion_keeps_label_recipe(self):
        from src.creation.builder import build_spec_from_instruction
        from src.interpretation.schema import InterpretedInstruction

        instruction = InterpretedInstruction(
            raw_prompt="slow pulse",
            palette_name="default",
            motion_type="pulse",
            intensity=0.5,
        )
        knowledge = {
            "learned_motion": [{"motion_level": 22.4, "motion_std": 1.0, "motion_trend": "steady", "count": 1}],
        }
        spec = build_spec_from_instruction(instruction, knowledge=knowledge)
        self.assertEqual(spec.motion_type, "pulse")
        self.assertAlmostEqual(spec.motion_level, 10.0, places=1)

    def test_recipe_value_varies_with_level(self):
        from src.procedural.motion import get_motion_func, motion_recipe_value

        slow = [motion_recipe_value(t, level=2.0) for t in (0.0, 0.5, 1.0, 2.0)]
        fast = [motion_recipe_value(t, level=22.0) for t in (0.0, 0.5, 1.0, 2.0)]
        self.assertNotEqual(slow, fast)
        pulse = get_motion_func("pulse")(0.25)
        self.assertGreaterEqual(pulse, 0.0)
        self.assertLessEqual(pulse, 1.0)

