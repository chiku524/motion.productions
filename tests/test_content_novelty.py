"""Content-level novelty gate: fingerprints, bounded store, re-roll, authenticity."""
import tempfile
import unittest
from pathlib import Path

import numpy as np

from src.knowledge.content_novelty import (
    NoveltyStore,
    audio_band_energy,
    color_histogram,
    dhash_hex,
    fingerprint_arrays,
    fingerprint_distance,
    hamming_hex,
    is_too_close,
    record_result,
    render_until_novel,
    reroll_seed,
)
from src.knowledge.loop_authenticity import evaluate_iteration


def _frame(kind: int, size: int = 64) -> np.ndarray:
    """Distinct synthetic layouts: gradients / blobs / stripes in different colors."""
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32) / size
    img = np.zeros((size, size, 3), np.float32)
    if kind == 0:
        img[..., 0] = xx * 255
        img[..., 2] = 40
    elif kind == 1:
        img[..., 1] = (np.hypot(xx - 0.3, yy - 0.7) < 0.25) * 220 + 20
        img[..., 2] = 120
    elif kind == 2:
        img[..., 0] = ((yy * 8).astype(int) % 2) * 255
        img[..., 1] = 30
    else:
        img[..., 2] = yy * 255
        img[..., 0] = 200
    return img.astype(np.uint8)


def _tone(freq: float, sr: int = 22050, secs: float = 1.0) -> np.ndarray:
    t = np.arange(int(sr * secs)) / sr
    return (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


class TestFingerprintParts(unittest.TestCase):
    def test_dhash_identical_and_different(self):
        a, b = _frame(0), _frame(2)
        self.assertEqual(hamming_hex(dhash_hex(a), dhash_hex(a)), 0)
        self.assertGreater(hamming_hex(dhash_hex(a), dhash_hex(b)), 20)

    def test_histogram_normalized(self):
        h = color_histogram([_frame(1)])
        self.assertAlmostEqual(sum(h), 1.0, places=6)
        self.assertEqual(len(h), 64)

    def test_audio_bands_separate_low_and_high_tones(self):
        low, _ = audio_band_energy(_tone(120))
        high, _ = audio_band_energy(_tone(4000))
        self.assertAlmostEqual(sum(low), 1.0, places=5)
        self.assertGreater(0.5 * np.abs(np.array(low) - np.array(high)).sum(), 0.8)

    def test_silence_has_zero_bands(self):
        bands, rms = audio_band_energy(np.zeros(22050, np.float32))
        self.assertEqual(sum(bands), 0.0)
        self.assertEqual(rms, 0.0)


class TestDistanceAndGate(unittest.TestCase):
    def _fp(self, kind, freq=200.0):
        frames = [_frame(kind)] * 5
        return fingerprint_arrays(frames, _tone(freq))

    def test_same_clip_is_too_close(self):
        d = fingerprint_distance(self._fp(0), self._fp(0))
        self.assertAlmostEqual(d["combined"], 0.0, places=6)
        self.assertTrue(is_too_close(d))

    def test_different_clips_are_novel(self):
        d = fingerprint_distance(self._fp(0, 200), self._fp(1, 3000))
        self.assertFalse(is_too_close(d), d)
        self.assertGreater(d["combined"], 0.3)

    def test_visual_twin_with_different_audio_still_rejected(self):
        d = fingerprint_distance(self._fp(2, 150), self._fp(2, 5000))
        self.assertTrue(is_too_close(d), d)

    def test_missing_audio_is_handled(self):
        a = fingerprint_arrays([_frame(0)] * 3, None)
        b = fingerprint_arrays([_frame(3)] * 3, None)
        d = fingerprint_distance(a, b)
        self.assertEqual(d["audio"], 0.0)
        self.assertGreater(d["combined"], 0.1)


class TestVideoFile(unittest.TestCase):
    def test_fingerprint_video_reads_real_mp4(self):
        import imageio.v2 as imageio
        from src.knowledge.content_novelty import fingerprint_video

        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "c.mp4"
            w = imageio.get_writer(str(p), fps=12)
            for i in range(12):
                w.append_data(_frame(0 if i < 6 else 3, size=64))
            w.close()
            fp, thumb = fingerprint_video(p)
            self.assertEqual(len(fp.phash), 3)
            self.assertEqual(len(fp.hist), 64)
            self.assertEqual(fp.audio, [])  # no audio stream -> empty, not an error
            self.assertEqual(thumb.shape[2], 3)


class TestStore(unittest.TestCase):
    def test_roundtrip_and_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = NoveltyStore(tmp, max_entries=10)
            fp = fingerprint_arrays([_frame(0)] * 3, _tone(300))
            self.assertTrue(s.check(fp).novel)
            s.add(fp, entry_id="a", prompt="p", seed=1, thumbnail=_frame(0))
            s2 = NoveltyStore(tmp, max_entries=10)  # reload from disk
            self.assertEqual(len(s2), 1)
            v = s2.check(fp)
            self.assertFalse(v.novel)
            self.assertEqual(v.nearest_id, "a")
            self.assertTrue((Path(tmp) / "thumbs" / "a.jpg").exists())

    def test_store_is_bounded_and_prunes_thumbs(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = NoveltyStore(tmp, max_entries=3)
            fp = fingerprint_arrays([_frame(1)] * 3, _tone(500))
            for i in range(7):
                s.add(fp, entry_id=f"c{i}", thumbnail=_frame(1))
            self.assertEqual(len(s), 3)
            self.assertEqual([e["id"] for e in s.entries()], ["c4", "c5", "c6"])
            self.assertEqual(sorted(p.stem for p in (Path(tmp) / "thumbs").glob("*.jpg")), ["c4", "c5", "c6"])

    def test_corrupt_store_file_starts_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "fingerprints.json").write_text("{not json", encoding="utf-8")
            self.assertEqual(len(NoveltyStore(tmp)), 0)


class TestRenderUntilNovel(unittest.TestCase):
    def _fake_fp(self, seed_to_kind):
        def fn(path):
            kind = seed_to_kind[int(Path(path).stem)]
            return fingerprint_arrays([_frame(kind)] * 3, _tone(200 + 700 * kind)), _frame(kind)
        return fn

    def test_rerolls_seed_until_clip_differs(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = NoveltyStore(tmp)
            store.add(fingerprint_arrays([_frame(0)] * 3, _tone(200)), entry_id="seen")
            second = reroll_seed(10, 1)
            kinds = {10: 0, second: 2}
            calls = []

            def render(seed):
                calls.append(seed)
                return Path(tmp) / f"{seed}.mp4"

            res = render_until_novel(render, store, seed=10, max_attempts=4, fingerprint_fn=self._fake_fp(kinds))
            self.assertEqual(calls, [10, second])
            self.assertEqual(res.attempts, 2)
            self.assertTrue(res.verdict.novel)
            self.assertIs(res.content_novel, True)
            self.assertEqual(res.seed, second)
            record_result(store, res, entry_id="job2", prompt="x")
            self.assertEqual(len(store), 2)

    def test_gives_up_after_max_attempts_and_reports_not_novel(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = NoveltyStore(tmp)
            store.add(fingerprint_arrays([_frame(0)] * 3, _tone(200)), entry_id="seen")

            class AllZero(dict):
                def __getitem__(self, k):
                    return 0

            res = render_until_novel(
                lambda s: Path(tmp) / f"{s}.mp4", store, seed=5, max_attempts=3,
                fingerprint_fn=self._fake_fp(AllZero()),
            )
            self.assertEqual(res.attempts, 3)
            self.assertIs(res.content_novel, False)

    def test_fingerprint_failure_is_unchecked_not_novel(self):
        with tempfile.TemporaryDirectory() as tmp:
            def boom(path):
                raise RuntimeError("no codec")

            res = render_until_novel(lambda s: Path(tmp) / "x.mp4", NoveltyStore(tmp), seed=1, fingerprint_fn=boom)
            self.assertIsNone(res.content_novel)
            record_result(NoveltyStore(tmp), res, entry_id="x")  # no-op, must not raise

    def test_reroll_seed_is_deterministic_and_distinct(self):
        seeds = {reroll_seed(123, i) for i in range(1, 20)}
        self.assertEqual(len(seeds), 19)
        self.assertEqual(reroll_seed(123, 3), reroll_seed(123, 3))


class TestAuthenticityRequiresFingerprint(unittest.TestCase):
    BASE = dict(
        source="mission_frame_color", prompt="a unique prompt zzz", recent=[],
        knowledge={"x": 1}, growth_ran=True, growth_added={}, render_engine="procedural",
    )

    def test_default_behaviour_unchanged(self):
        self.assertTrue(evaluate_iteration(**self.BASE)["authentic"])

    def test_required_but_not_run_is_not_authentic(self):
        r = evaluate_iteration(**self.BASE, require_content_novelty=True, content_novel=None)
        self.assertFalse(r["authentic"])
        self.assertFalse(r["content_checked"])

    def test_required_and_duplicate_is_not_authentic(self):
        r = evaluate_iteration(**self.BASE, require_content_novelty=True, content_novel=False)
        self.assertFalse(r["authentic"])
        self.assertTrue(r["novel_prompt"])

    def test_required_and_novel_is_authentic(self):
        r = evaluate_iteration(**self.BASE, require_content_novelty=True, content_novel=True)
        self.assertTrue(r["authentic"])


if __name__ == "__main__":
    unittest.main()