"""
Unit tests for critical registry-affecting paths (CODEBASE_AUDIT_MISSION_ALIGNMENT §5.1).
Run from project root: python -m pytest tests/ -v
Or: python -m unittest discover -s tests -p "test_*.py" -v
"""
import sys
import unittest
from pathlib import Path

# Project root on path so "from src. ..." works
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


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

    def test_build_pure_color_pool_with_static_and_learned(self):
        """_build_pure_color_pool merges origin + static_colors + learned_colors without duplicates."""
        from src.creation.builder import _build_pure_color_pool
        from src.interpretation.schema import InterpretedInstruction

        instruction = InterpretedInstruction(raw_prompt="test", palette_name="default", motion_type="flow", intensity=0.5)
        knowledge = {
            "static_colors": {
                "key1": {"r": 10, "g": 20, "b": 30},
                "key2": {"r": 255, "g": 0, "b": 0},  # red - may duplicate origin
            },
            "learned_colors": {
                "lc1": {"r": 100, "g": 150, "b": 200},
            },
        }
        pool = _build_pure_color_pool(knowledge, instruction, avoid_palette=set())
        self.assertIn((10, 20, 30), pool)
        self.assertIn((100, 150, 200), pool)
        self.assertTrue(any(c == (255, 0, 0) for c in pool))
        self.assertGreaterEqual(len(pool), 17)

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
