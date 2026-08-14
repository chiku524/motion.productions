"""Pixel-field emergence: settings/objects from independent pairings."""
from __future__ import annotations

import unittest

import numpy as np

from src.knowledge.pixel_emergence import (
    emerge_from_frame,
    merge_emergence_payloads,
    score_settings,
)


def _ocean_frame() -> np.ndarray:
    frame = np.zeros((64, 64, 3), dtype=np.uint8)
    frame[:18] = (150, 195, 230)
    frame[18:] = (18, 72, 176)
    return frame


def _forest_frame() -> np.ndarray:
    frame = np.zeros((64, 64, 3), dtype=np.uint8)
    frame[:14] = (110, 150, 200)
    frame[14:46] = (28, 138, 36)
    frame[46:] = (82, 48, 22)
    return frame


def _tree_blob() -> np.ndarray:
    frame = np.zeros((64, 64, 3), dtype=np.uint8)
    frame[:] = (46, 44, 52)
    frame[8:50, 27:37] = (22, 148, 32)
    return frame


class TestPixelEmergence(unittest.TestCase):
    def test_ocean_layout_hits_registered_setting(self):
        from src.knowledge.pixel_emergence import _layout_stats

        ranked = score_settings(_layout_stats(_ocean_frame()))
        names = [n for n, _ in ranked]
        self.assertIn("ocean", names)

    def test_forest_layout_hits_forest_setting(self):
        from src.knowledge.pixel_emergence import _layout_stats

        ranked = score_settings(_layout_stats(_forest_frame()))
        names = [n for n, _ in ranked]
        self.assertIn("forest", names)

    def test_emerge_posts_origin_setting_payload(self):
        found = emerge_from_frame(_ocean_frame(), prompt="static frame: independent pixel pairings")
        keys = {e["key"] for e in found["settings"]}
        self.assertIn("ocean", keys)

    def test_green_vertical_mass_can_be_a_tree(self):
        found = emerge_from_frame(_tree_blob(), prompt="pixel field")
        kinds = {e["kind"] for e in found["entities"]}
        self.assertTrue("tree" in kinds or "composed" in kinds, kinds)
        self.assertTrue(found["entities"])
        self.assertTrue(all(e.get("name") or e.get("label") for e in found["entities"]))

    def test_stumbles_onto_already_registered_entity(self):
        knowledge = {
            "learned_entities": [
                {
                    "key": "tree_none_0_forest_none",
                    "kind": "tree",
                    "color_hint": "forest",
                    "name": "Pineveil",
                    "label": "Pineveil",
                    "trajectory": "none",
                    "directionality": "none",
                }
            ]
        }
        found = emerge_from_frame(_tree_blob(), prompt="pixel field", knowledge=knowledge)
        keys = {e["key"] for e in found["entities"]}
        self.assertIn("tree_none_0_forest_none", keys)
        hit = next(e for e in found["entities"] if e["key"] == "tree_none_0_forest_none")
        self.assertEqual(hit["name"], "Pineveil")
        self.assertTrue(hit["entity_json"]["stumbled"])

    def test_novel_mass_gets_a_sensible_name(self):
        frame = np.zeros((64, 64, 3), dtype=np.uint8)
        frame[:] = (30, 30, 34)
        frame[20:40, 18:46] = (210, 90, 40)
        found = emerge_from_frame(frame, prompt="pixel field")
        self.assertTrue(found["entities"] or found["settings"])
        for e in found["entities"]:
            name = str(e.get("name") or e.get("label") or "")
            self.assertGreaterEqual(len(name), 3)
            self.assertFalse(name.isupper())
            self.assertNotIn("_", name)

    def test_merge_unions_emergence_without_dupes(self):
        novel = {
            "narrative": {"settings": [{"key": "ocean", "value": "ocean"}]},
            "entities": [{"key": "a", "kind": "composed"}],
        }
        narr, ents = merge_emergence_payloads(
            novel,
            {"settings": [{"key": "forest", "value": "forest"}]},
            [{"key": "a", "kind": "composed"}],
        )
        setting_keys = {e["key"] for e in narr["settings"]}
        self.assertEqual(setting_keys, {"ocean", "forest"})
        self.assertEqual(len(ents), 1)


if __name__ == "__main__":
    unittest.main()
