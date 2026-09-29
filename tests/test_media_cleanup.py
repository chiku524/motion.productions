"""Scratch renders are deleted after discovery, with a hard cap if a run fails."""
import tempfile
import unittest
from pathlib import Path


class TestMediaCleanup(unittest.TestCase):
    def test_prune_keeps_newest_only(self):
        from src.media_cleanup import prune_render_scratch

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            older = root / "loop_old.mp4"
            newer = root / "loop_new.mp4"
            older.write_bytes(b"old")
            newer.write_bytes(b"new")
            import os
            os.utime(older, (1_000_000_000, 1_000_000_000))
            os.utime(newer, (1_700_000_000, 1_700_000_000))
            removed = prune_render_scratch(root, keep=1)
            self.assertEqual(removed, 1)
            self.assertFalse(older.exists())
            self.assertTrue(newer.exists())
            self.assertEqual(prune_render_scratch(root, keep=0), 1)
            self.assertFalse(newer.exists())


if __name__ == "__main__":
    unittest.main()
