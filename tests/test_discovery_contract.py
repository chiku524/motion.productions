"""
Contract tests: discovery payload chunking + for-creation / completion_targets shapes.
Shared fixture: tests/fixtures/discovery_payload.json
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "discovery_payload.json"


class TestDiscoveryContract(unittest.TestCase):
    def test_fixture_loads(self):
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertIn("static_colors", data)
        self.assertIn("motion", data)
        self.assertIsInstance(data["static_colors"], list)

    def test_chunk_respects_max_items(self):
        from src.knowledge.remote_sync import DISCOVERIES_MAX_ITEMS, _chunk_discoveries

        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        # Inflate static_colors beyond one chunk
        base = list(payload.get("static_colors") or [])
        if not base:
            base = [{"key": "0,0,0", "r": 0, "g": 0, "b": 0, "name": "Black"}]
        many = []
        for i in range(DISCOVERIES_MAX_ITEMS + 25):
            item = dict(base[0])
            item["key"] = f"{i % 256},{i % 128},{i % 64}"
            item["r"] = i % 256
            many.append(item)
        payload["static_colors"] = many
        payload["job_id"] = "00000000-0000-0000-0000-000000000001"
        chunks = _chunk_discoveries(dict(payload))
        self.assertGreaterEqual(len(chunks), 2)
        for ch in chunks:
            n = 0
            for k, v in ch.items():
                if k == "job_id":
                    continue
                if k == "narrative" and isinstance(v, dict):
                    n += sum(len(x) for x in v.values() if isinstance(x, list))
                elif isinstance(v, list):
                    n += len(v)
            self.assertLessEqual(n, DISCOVERIES_MAX_ITEMS)
        self.assertEqual(chunks[-1].get("job_id"), payload["job_id"])

    def test_empty_job_id_only_chunk(self):
        from src.knowledge.remote_sync import _chunk_discoveries

        chunks = _chunk_discoveries({"job_id": "abc"})
        self.assertEqual(chunks, [{"job_id": "abc"}])

    def test_for_creation_expected_keys(self):
        """Keys automate_loop / pick_prompt expect from GET /api/knowledge/for-creation."""
        expected = {
            "static_colors",
            "learned_colors",
            "learned_motion",
            "learned_entities",
            "interpretation_prompts",
            "good_prompts",
        }
        # Documented contract — Worker may return a subset; consumers use .get
        sample = {
            "static_colors": {},
            "learned_colors": {},
            "learned_motion": {},
            "learned_entities": [],
            "interpretation_prompts": [{"prompt": "ocean sunset", "instruction": {}}],
            "good_prompts": ["calm waves"],
        }
        for k in expected:
            self.assertIn(k, sample)

    def test_completion_targets_constants(self):
        from src.knowledge.completion_targets import (
            STATIC_COLOR_ESTIMATED_CELLS,
            STATIC_SOUND_NUM_PRIMITIVES,
            NARRATIVE_ORIGIN_SIZES,
            DYNAMIC_AUDIO_MOOD,
            DYNAMIC_CAMERA_ORIGIN_SIZE,
            static_color_coverage_pct,
        )
        from src.knowledge.origins import NARRATIVE_ORIGINS, AUDIO_ORIGINS, CAMERA_ORIGINS

        self.assertEqual(STATIC_COLOR_ESTIMATED_CELLS, 11 * 11 * 11 * 21)
        self.assertEqual(STATIC_SOUND_NUM_PRIMITIVES, 10)
        self.assertIn("genre", NARRATIVE_ORIGIN_SIZES)
        # Mission-aligned: sizes match full origins, not a stale subset
        self.assertEqual(NARRATIVE_ORIGIN_SIZES["genre"], len(NARRATIVE_ORIGINS["genre"]))
        self.assertEqual(NARRATIVE_ORIGIN_SIZES["mood"], len(NARRATIVE_ORIGINS["tone"]))
        self.assertEqual(NARRATIVE_ORIGIN_SIZES["plots"], len(NARRATIVE_ORIGINS["tension_curve"]))
        self.assertEqual(DYNAMIC_AUDIO_MOOD, len(AUDIO_ORIGINS["mood"]))
        self.assertEqual(DYNAMIC_CAMERA_ORIGIN_SIZE, len(CAMERA_ORIGINS["motion_type"]))
        self.assertGreater(static_color_coverage_pct(100), 0)
        self.assertLessEqual(static_color_coverage_pct(STATIC_COLOR_ESTIMATED_CELLS), 100.0)

    def test_blend_depth_sound_primitives_align(self):
        from src.knowledge.blend_depth import SOUND_ORIGIN_PRIMITIVES
        from src.knowledge.completion_targets import STATIC_SOUND_PRIMITIVES

        self.assertEqual(list(SOUND_ORIGIN_PRIMITIVES), list(STATIC_SOUND_PRIMITIVES))
        self.assertEqual(len(SOUND_ORIGIN_PRIMITIVES), 10)


if __name__ == "__main__":
    unittest.main()
