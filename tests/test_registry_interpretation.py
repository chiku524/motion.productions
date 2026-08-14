"""Registry-first interpretation and static RGB palettes."""
import unittest

from src.interpretation.parser import interpret_user_prompt
from src.creation.builder import _build_palette_from_blending, _build_pure_color_pool
from src.interpretation.schema import InterpretedInstruction
from src.knowledge.remote_sync import _flatten_discovery_items, _rebuild_discovery_payload
from src.knowledge.color_space import palette_stops_from_rgb


class TestRegistryInterpretation(unittest.TestCase):
    def test_named_static_color_overrides_keyword_palette(self):
        knowledge = {
            "static_colors": {
                "k1": {"r": 12, "g": 34, "b": 56, "name": "Suntor", "count": 1},
            }
        }
        inst = interpret_user_prompt("a field of Suntor light", knowledge=knowledge)
        self.assertEqual(inst.palette_name, "Suntor")
        self.assertTrue(inst.color_primitive_lists)
        self.assertIn((12, 34, 56), inst.color_primitive_lists[0])

    def test_unknown_prompt_still_uses_keyword_tables(self):
        inst = interpret_user_prompt("ocean at sunset")
        self.assertIn(inst.palette_name, ("ocean", "warm_sunset"))

    def test_palette_from_static_rgb_when_no_hints(self):
        instruction = InterpretedInstruction(
            palette_name="default",
            motion_type="flow",
            intensity=0.5,
            palette_hints=[],
            raw_prompt="untitled",
        )
        knowledge = {
            "static_colors": {
                "a": {"r": 10, "g": 20, "b": 30, "name": "Mistvale", "count": 1},
                "b": {"r": 200, "g": 10, "b": 10, "name": "Emberford", "count": 1},
            }
        }
        colors = _build_palette_from_blending(instruction, knowledge, "default")
        self.assertGreaterEqual(len(colors), 2)
        self.assertTrue(any(c in ((10, 20, 30), (200, 10, 10)) for c in colors))

    def test_pure_pool_skips_learned_when_static_present(self):
        instruction = InterpretedInstruction(
            palette_name="default", motion_type="flow", intensity=0.5, raw_prompt="t",
        )
        knowledge = {
            "static_colors": {"k1": {"r": 10, "g": 20, "b": 30}},
            "learned_colors": {"lc1": {"r": 100, "g": 150, "b": 200}},
        }
        pool = _build_pure_color_pool(knowledge, instruction, avoid_palette=set())
        self.assertIn((10, 20, 30), pool)
        self.assertNotIn((100, 150, 200), pool)

    def test_palette_stops_from_rgb(self):
        stops = palette_stops_from_rgb(80, 40, 200)
        self.assertEqual(len(stops), 4)
        self.assertIn((80, 40, 200), stops)

    def test_discovery_remainder_rebuild(self):
        payload = {
            "static_colors": [{"key": "a"}, {"key": "b"}, {"key": "c"}],
            "motion": [{"key": "m1"}],
        }
        flat = _flatten_discovery_items(payload)
        self.assertEqual(len(flat), 4)
        rest = _rebuild_discovery_payload(flat[2:])
        self.assertEqual(len(rest["static_colors"]), 1)
        self.assertEqual(rest["static_colors"][0]["key"], "c")
        self.assertEqual(rest["motion"][0]["key"], "m1")


if __name__ == "__main__":
    unittest.main()
