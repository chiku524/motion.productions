"""Primitive diversity: weighted sampling, caps, and spread resolution (no whoosh dominance)."""
from __future__ import annotations

import collections
import unittest

from src.audio.pairing import (
    AUDIBLE_PRIMITIVES,
    entry_primitive,
    recent_primitive_history,
    reset_primitive_history,
    sample_sound_pairing,
)


def _skewed_registry() -> dict:
    """Mimics the live registry: least-used entries are mostly 'whoosh' (old strict sort -> whoosh everywhere)."""
    rows = []
    for i in range(40):
        rows.append({"name": f"Wsh{i}", "tone": "high", "timbre": "whoosh", "amplitude": 0.04, "count": 100 + i})
    for i, prim in enumerate(AUDIBLE_PRIMITIVES):
        if prim == "whoosh":
            continue
        for j in range(4):
            rows.append({"name": f"{prim}{j}x", "tone": "mid", "timbre": prim, "amplitude": 0.04, "count": 900 + 40 * i + j})
    rows.append({"name": "Hush", "tone": "silent", "timbre": "silence", "amplitude": 0.0, "count": 5})
    return {"static_sound": rows}


def _prims(pair):
    return [entry_primitive(e) for e in pair]


class TestPrimitiveSpread(unittest.TestCase):
    def setUp(self):
        reset_primitive_history()

    def test_lead_pick_not_dominated_by_any_primitive(self):
        kn = _skewed_registry()
        leads = collections.Counter(
            _prims(sample_sound_pairing(kn, pair_count=4, seed=s, use_history=False))[0] for s in range(900)
        )
        self.assertEqual(set(leads), set(AUDIBLE_PRIMITIVES))  # every audible primitive reachable
        self.assertLessEqual(max(leads.values()) / 900, 0.35)

    def test_all_layers_spread_and_whoosh_share_bounded(self):
        kn = _skewed_registry()
        layers = collections.Counter()
        for s in range(600):
            layers.update(_prims(sample_sound_pairing(kn, pair_count=4, seed=s, use_history=False)))
        total = sum(layers.values())
        self.assertLessEqual(layers["whoosh"] / total, 0.25)
        self.assertLessEqual(max(layers.values()) / total, 0.25)

    def test_no_primitive_repeats_within_a_clip(self):
        kn = _skewed_registry()
        for s in range(200):
            for n in (2, 4, 6):
                prims = _prims(sample_sound_pairing(kn, pair_count=n, seed=s, use_history=False))
                self.assertEqual(len(prims), n)
                self.assertEqual(len(prims), len(set(prims)), prims)

    def test_never_picks_silence(self):
        kn = _skewed_registry()
        for s in range(300):
            self.assertNotIn("silence", _prims(sample_sound_pairing(kn, pair_count=4, seed=s, use_history=False)))

    def test_same_seed_is_reproducible_without_history(self):
        kn = _skewed_registry()
        a = sample_sound_pairing(kn, pair_count=4, seed=77, use_history=False)
        b = sample_sound_pairing(kn, pair_count=4, seed=77, use_history=False)
        self.assertEqual(a, b)

    def test_strict_least_used_order_is_gone(self):
        kn = _skewed_registry()
        picks = {tuple(sorted(_prims(sample_sound_pairing(kn, pair_count=4, seed=s, use_history=False)))) for s in range(60)}
        self.assertGreater(len(picks), 20)

    def test_history_spreads_consecutive_clips(self):
        kn = _skewed_registry()
        counts = collections.Counter()
        for s in range(120):
            counts.update(_prims(sample_sound_pairing(kn, pair_count=4, seed=s)))
        hist = recent_primitive_history()
        self.assertLessEqual(len(hist), 24)
        self.assertLessEqual(max(counts.values()) / sum(counts.values()), 0.2)
        self.assertLessEqual(collections.Counter(hist).most_common(1)[0][1] / len(hist), 0.25)

    def test_named_sounds_still_come_first(self):
        kn = _skewed_registry()
        pair = sample_sound_pairing(kn, prompt="sound pairing of hum with click", pair_count=4, seed=5, use_history=False)
        self.assertEqual({entry_primitive(e) for e in pair[:2]}, {"hum", "click"})
        self.assertEqual(len(set(_prims(pair))), 4)

    def test_without_registry_uses_all_primitives(self):
        seen = set()
        for s in range(200):
            seen.update(_prims(sample_sound_pairing(None, pair_count=3, seed=s, use_history=False)))
        self.assertEqual(seen, set(AUDIBLE_PRIMITIVES))


class TestEntryPrimitive(unittest.TestCase):
    def test_explicit_timbre_wins(self):
        self.assertEqual(entry_primitive({"name": "Humbert", "timbre": "drip", "tone": "low"}), "drip")

    def test_name_substring_resolves(self):
        self.assertEqual(entry_primitive({"name": "soft rustle", "tone": "high"}), "rustle")

    def test_unresolved_names_spread_inside_tone_band(self):
        mid = collections.Counter(
            entry_primitive({"name": f"Zq{i}vo", "tone": "mid", "timbre": "mid"}) for i in range(300)
        )
        self.assertEqual(set(mid), {"tone", "rustle", "whoosh"})
        self.assertLessEqual(max(mid.values()) / 300, 0.5)
        low = {entry_primitive({"name": f"Zq{i}vo", "tone": "low"}) for i in range(300)}
        high = {entry_primitive({"name": f"Zq{i}vo", "tone": "high"}) for i in range(300)}
        self.assertEqual(low, {"rumble", "hum", "thump"})
        self.assertEqual(high, {"hiss", "click", "drip"})

    def test_bare_tone_keeps_legacy_default(self):
        self.assertEqual(entry_primitive({"tone": "mid"}), "tone")
        self.assertEqual(entry_primitive({"tone": "silent"}), "silence")

    def test_audio_resolution_matches(self):
        try:
            from src.audio.sound import _primitive_from_entry
        except Exception:
            self.skipTest("sound module unavailable")
        for e in ({"name": "Qzx", "tone": "high"}, {"timbre": "click"}, {"tone": "low"}):
            self.assertEqual(_primitive_from_entry(e), entry_primitive(e))


if __name__ == "__main__":
    unittest.main()