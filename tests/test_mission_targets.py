"""Unit tests for mission-aware growth targeting helpers."""
from __future__ import annotations

import unittest


class TestMissionTargets(unittest.TestCase):
    def test_underfilled_prefers_low_counts(self):
        from src.knowledge.mission_targets import underfilled_color_families

        from src.knowledge.mission_targets import FAMILY_SUBJECTS

        counts = {fid: 100 for fid in FAMILY_SUBJECTS}
        counts.update({"blue": 50, "teal": 2, "pink": 0})
        mission = {"colors": {"families": [{"id": k, "count": v} for k, v in counts.items()]}}
        under = underfilled_color_families(mission, max_n=2)
        self.assertEqual(under[0], "pink")
        self.assertIn("teal", under)

    def test_families_missing_from_payload_count_as_empty(self):
        """Older Workers dropped zero-count families (white); they must still be targetable."""
        from src.knowledge.mission_targets import FAMILY_SUBJECTS, color_family_counts

        mission = {"colors": {"families": [{"id": "blue", "count": 9}]}}
        counts = color_family_counts(mission)
        self.assertEqual(set(counts), set(FAMILY_SUBJECTS))
        self.assertEqual(counts["white"], 0)
        self.assertEqual(counts["blue"], 9)

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


class TestWeightedTargets(unittest.TestCase):
    def _mission(self):
        from src.knowledge.mission_targets import FAMILY_SUBJECTS

        fams = [{"id": f, "count": 400} for f in FAMILY_SUBJECTS]
        for f in fams:
            if f["id"] == "white":
                f["count"] = 0
        return {
            "colors": {"families": fams},
            "sound": {
                "origins_present": ["tone", "hum"],
                "origin_counts": {"tone": 5000, "hum": 3, "drip": 0},
            },
        }

    def test_underfill_weights_monotonic(self):
        from src.knowledge.mission_targets import underfill_weights

        w = underfill_weights({"a": 0, "b": 10, "c": 1000})
        self.assertGreater(w["a"], w["b"])
        self.assertGreater(w["b"], w["c"])
        self.assertGreater(w["c"], 0)

    def test_color_family_weighted_not_deterministic_but_favours_empty(self):
        import random as _r

        from src.knowledge.mission_targets import pick_target_color_family

        rng = _r.Random(7)
        picks = [pick_target_color_family("", self._mission(), rng) for _ in range(600)]
        self.assertGreater(picks.count("white"), 600 * 0.2)  # empty family ~3x uniform share
        self.assertGreater(len(set(picks)), 6)  # but the filled ones still appear

    def test_lead_sound_drawn_from_all_primitives(self):
        import random as _r

        from src.knowledge.blend_depth import SOUND_ORIGIN_PRIMITIVES
        from src.knowledge.mission_targets import pick_target_sound_origin

        rng = _r.Random(3)
        picks = {pick_target_sound_origin("", self._mission(), rng) for _ in range(800)}
        self.assertGreaterEqual(len(picks), len(SOUND_ORIGIN_PRIMITIVES) - 2)
        self.assertNotIn(None, picks)
        # tone (heavily filled) should be rare as a lead
        tone = sum(
            pick_target_sound_origin("", self._mission(), rng) == "tone" for _ in range(800)
        )
        self.assertLess(tone, 40)


class TestParityClassify(unittest.TestCase):
    def test_classify_blueish(self):
        from src.knowledge.mission_targets import classify_color_family_rgb

        self.assertEqual(classify_color_family_rgb(40, 80, 200), "blue")
        self.assertEqual(classify_color_family_rgb(250, 250, 250), "white")
        self.assertEqual(classify_color_family_rgb(10, 10, 10), "black")

class TestColorQueueTargeting(unittest.TestCase):
    """LOOP_COLOR_QUEUE / queue=: deterministic stride queue replaces weighted sampling for the colour axis."""

    def setUp(self):
        import tempfile

        from src.knowledge import mission_targets as mt
        from src.knowledge.color_cells import ColorCellStore

        self.mt = mt
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ColorCellStore(self.tmp.name)
        mt._color_calls = 0

    def tearDown(self):
        self.tmp.cleanup()

    def _queue(self, i, n):
        from src.knowledge.color_cells import ColorWorkQueue

        return ColorWorkQueue(self.store, i, n)

    def test_families_are_deterministic_and_need_no_mission_or_rng(self):
        def run():
            self.mt._color_calls = 0
            return [self.mt.pick_target_color_family("", None, None, queue=self._queue(0, 4)) for _ in range(12)]

        a, b = run(), run()
        self.assertEqual(a, b)
        self.assertTrue(set(a) <= set(self.mt.FAMILY_SUBJECTS))
        self.assertGreater(len(set(a)), 2)  # steps through the lookahead rather than repeating one family

    def test_containers_get_disjoint_cells(self):
        cells = [set(self.mt.pick_target_color_cells(200, queue=self._queue(i, 4))) for i in range(4)]
        for i in range(4):
            for j in range(i + 1, 4):
                self.assertFalse(cells[i] & cells[j])

    def test_covered_cells_are_skipped(self):
        q = self._queue(1, 3)
        first = self.mt.pick_target_color_cells(10, queue=q)
        self.store.mark("verified", first[:5])
        self.assertEqual(self.mt.pick_target_color_cells(5, queue=q), first[5:10])

    def test_env_flag_selects_queue_and_default_stays_weighted(self):
        import os
        from unittest import mock

        from src.knowledge.mission_targets import FAMILY_SUBJECTS

        mission = {"colors": {"families": [{"id": k, "count": 999 if k != "pink" else 0} for k in FAMILY_SUBJECTS]}}
        self.assertFalse(self.mt.color_queue_enabled())
        rng = __import__("random").Random(1)
        picks = {self.mt.pick_target_color_family("", mission, rng) for _ in range(40)}
        self.assertIn("pink", picks)  # weighted behaviour unchanged by default
        with mock.patch.dict(os.environ, {"LOOP_COLOR_QUEUE": "1", "COLOR_CELLS_DIR": self.tmp.name}):
            self.mt._COLOR_STORE = None
            self.assertTrue(self.mt.color_queue_enabled())
            fam = self.mt.pick_target_color_family("", mission, None)
            self.assertIn(fam, FAMILY_SUBJECTS)
            self.mt._COLOR_STORE = None

    def test_queue_failure_falls_back_to_weighted(self):
        class Broken:
            def next_cells(self, *a, **k):
                raise RuntimeError("no store")

        fam = self.mt.pick_target_color_family("", {"colors": {"families": []}}, __import__("random").Random(2), queue=Broken())
        self.assertIn(fam, self.mt.FAMILY_SUBJECTS)

if __name__ == "__main__":
    unittest.main()
