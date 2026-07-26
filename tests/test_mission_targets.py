"""Unit tests for mission-aware growth targeting helpers."""
from __future__ import annotations

import unittest


class TestMissionTargets(unittest.TestCase):
    def test_underfilled_prefers_low_counts(self):
        from src.knowledge.mission_targets import underfilled_color_families

        mission = {
            "colors": {
                "families": [
                    {"id": "blue", "count": 50},
                    {"id": "teal", "count": 2},
                    {"id": "pink", "count": 0},
                ]
            }
        }
        under = underfilled_color_families(mission, max_n=2)
        self.assertEqual(under[0], "pink")
        self.assertIn("teal", under)

    def test_missing_sound_origins(self):
        from src.knowledge.mission_targets import missing_sound_origins
        from src.knowledge.blend_depth import SOUND_ORIGIN_PRIMITIVES

        mission = {"sound": {"origins_present": ["silence", "rumble"]}}
        missing = missing_sound_origins(mission)
        self.assertNotIn("silence", missing)
        self.assertNotIn("rumble", missing)
        self.assertIn("tone", missing)
        for p in missing:
            self.assertIn(p, SOUND_ORIGIN_PRIMITIVES)

    def test_color_family_prompt_bits(self):
        from src.knowledge.mission_targets import color_family_prompt_bits

        subject, cue = color_family_prompt_bits("blue", "light")
        self.assertTrue(subject)
        self.assertTrue(cue)


class TestParityClassify(unittest.TestCase):
    def test_classify_blueish(self):
        from src.knowledge.mission_targets import classify_color_family_rgb

        self.assertEqual(classify_color_family_rgb(40, 80, 200), "blue")
        self.assertEqual(classify_color_family_rgb(250, 250, 250), "white")
        self.assertEqual(classify_color_family_rgb(10, 10, 10), "black")


if __name__ == "__main__":
    unittest.main()
