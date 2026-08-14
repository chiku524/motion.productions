"""Sound pairings: unique registry instants (frame) vs rematch over windows."""
from __future__ import annotations

import unittest

from src.audio.pairing import (
    named_registry_sounds,
    pairing_kind_from_prompt,
    sample_sound_pairing,
    sound_label,
)


class TestSoundPairing(unittest.TestCase):
    def test_sample_named_pair_from_prompt(self):
        knowledge = {
            "static_sound": [
                {"name": "hum", "tone": "low", "timbre": "hum", "amplitude": 0.5, "count": 8},
                {"name": "rustle", "tone": "mid", "timbre": "rustle", "amplitude": 0.4, "count": 3},
                {"name": "hiss", "tone": "high", "timbre": "hiss", "amplitude": 0.6, "count": 40},
            ]
        }
        pair = sample_sound_pairing(
            knowledge,
            prompt="static sound pairing of hum with rustle",
            pair_count=2,
            seed=3,
        )
        labels = {sound_label(e) for e in pair}
        self.assertEqual(len(pair), 2)
        self.assertIn("hum", labels)
        self.assertIn("rustle", labels)

    def test_falls_back_to_primitives(self):
        pair = sample_sound_pairing(None, prompt="", pair_count=2, seed=1)
        self.assertGreaterEqual(len(pair), 2)
        labels = [sound_label(e) for e in pair]
        self.assertEqual(len(labels), len(set(labels)))

    def test_window_pair_is_unique_four(self):
        pair = sample_sound_pairing(None, prompt="", pair_count=4, seed=7)
        labels = [sound_label(e) for e in pair]
        self.assertEqual(len(pair), 4)
        self.assertEqual(len(labels), len(set(labels)))

    def test_named_registry_sounds_falls_back_to_origins(self):
        names = named_registry_sounds(None)
        self.assertIn("hum", names)
        self.assertNotIn("silence", names)

    def test_pairing_kind_from_prompt(self):
        self.assertEqual(pairing_kind_from_prompt("static sound pairing of hum with click"), "frame")
        self.assertEqual(pairing_kind_from_prompt("dynamic sound pairing of whoosh with drip"), "window")
        self.assertEqual(pairing_kind_from_prompt("motion window: amber paired with teal"), "window")

    def test_window_mix_changes_more_than_static(self):
        try:
            from src.audio.sound import generate_audio_from_pure_sounds
        except Exception:
            self.skipTest("pydub not available")
        pair = sample_sound_pairing(None, prompt="hum with click", pair_count=2, seed=2)
        try:
            frame = generate_audio_from_pure_sounds(pair, duration_ms=2000, pairing_kind="frame")
            window = generate_audio_from_pure_sounds(pair + pair[:1], duration_ms=2000, pairing_kind="window")
        except RuntimeError as e:
            if "pydub" in str(e).lower():
                self.skipTest("pydub not available")
            raise
        # Window rematch should not be byte-identical to a held pairing
        self.assertNotEqual(frame.raw_data, window.raw_data)


if __name__ == "__main__":
    unittest.main()
