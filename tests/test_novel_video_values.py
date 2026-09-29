"""Each video stamps unique color and sound values for discovery."""
import unittest


class TestNovelVideoValues(unittest.TestCase):
    def test_same_seed_reproduces_stamp(self):
        from src.creation.novelty import stamp_unique_discovery_values

        colors = [(255, 0, 0), (0, 0, 255)]
        sounds = [{"name": "hum", "tone": "low", "timbre": "hum", "amplitude": 0.55, "weight": 0.55}]
        a_colors, a_sounds, a_disc = stamp_unique_discovery_values(colors, sounds, None, 11)
        b_colors, b_sounds, b_disc = stamp_unique_discovery_values(colors, sounds, None, 11)
        self.assertEqual(a_colors, b_colors)
        self.assertEqual(a_sounds, b_sounds)
        self.assertEqual(a_disc, b_disc)
        self.assertEqual(len(a_disc["colors"]), 2)
        self.assertEqual(len(a_disc["sounds"]), 1)

    def test_different_seeds_stamp_different_colors(self):
        from src.creation.novelty import stamp_unique_discovery_values

        colors = [(255, 0, 0), (0, 0, 255)]
        sounds = [{"name": "tone", "tone": "mid", "timbre": "tone", "amplitude": 0.4, "weight": 0.4}]
        _, _, a = stamp_unique_discovery_values(colors, sounds, None, 3)
        _, _, b = stamp_unique_discovery_values(colors, sounds, None, 99)
        self.assertNotEqual(a["colors"], b["colors"])
        self.assertNotEqual(
            round(a["sounds"][0]["amplitude"], 2),
            round(b["sounds"][0]["amplitude"], 2),
        )

    def test_spec_carries_discovery_values(self):
        from src.creation.builder import build_spec_from_instruction
        from src.interpretation.schema import InterpretedInstruction
        from src.knowledge.blend_depth import COLOR_ORIGIN_PRIMITIVES

        instruction = InterpretedInstruction(
            raw_prompt="static frame pairing",
            palette_name="default",
            motion_type="flow",
            intensity=0.5,
        )
        spec = build_spec_from_instruction(instruction, knowledge={}, creation_seed=21)
        payload = (spec.instance or {}).get("discovery_values") or {}
        colors = payload.get("colors") or []
        sounds = payload.get("sounds") or []
        self.assertEqual(len(colors), 2)
        self.assertEqual(len(sounds), 1)
        origins = {tuple(int(c) for c in rgb) for _n, rgb in COLOR_ORIGIN_PRIMITIVES}
        for c in colors:
            rgb = (int(c["r"]), int(c["g"]), int(c["b"]))
            self.assertNotIn(rgb, origins)
            self.assertIn(rgb, spec.pure_colors)
        self.assertLessEqual(len(spec.pure_colors), 12)
        self.assertEqual(len(spec.pure_sounds), 2)
        self.assertEqual(spec.pure_sounds[-1]["amplitude"], sounds[0]["amplitude"])


if __name__ == "__main__":
    unittest.main()
