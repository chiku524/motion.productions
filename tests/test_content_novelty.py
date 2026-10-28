"""Content-level novelty gate: fingerprints, bounded store, re-roll, authenticity."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

import numpy as np

from src.knowledge.content_novelty import (
    ClipFingerprint,
    NoveltyStore,
    audio_band_energy,
    color_histogram,
    dhash_hex,
    fingerprint_arrays,
    fingerprint_distance,
    hamming_hex,
    is_too_close,
    default_store_dir,
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


def _rand_fp(rng: np.random.Generator, audio: bool = True) -> ClipFingerprint:
    hist = rng.random(64)
    aud = rng.random(12)
    return ClipFingerprint(
        phash=[format(int(rng.integers(0, 2 ** 62)) << 64 | int(rng.integers(0, 2 ** 62)), "064x") for _ in range(3)],
        hist=(hist / hist.sum()).tolist(),
        audio=(aud / aud.sum()).tolist() if audio else [],
    )


_WORKER = """
import sys
import numpy as np
from src.knowledge.content_novelty import NoveltyStore, fingerprint_arrays
d, name, n, cap = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
s = NoveltyStore(d, max_entries=cap)
rng = np.random.default_rng(abs(hash(name)) % 1000)
for i in range(n):
    fr = (rng.random((32, 32, 3)) * 255).astype('uint8')
    s.add(fingerprint_arrays([fr] * 3), entry_id=f"{name}-{i}", prompt=name)
"""


class TestSharedStore(unittest.TestCase):
    """The store is shared by every loop container: writers must merge, never overwrite."""

    def test_two_instances_see_each_others_entries_without_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = NoveltyStore(tmp), NoveltyStore(tmp)
            rng = np.random.default_rng(1)
            fa, fb = _rand_fp(rng), _rand_fp(rng)
            a.add(fa, entry_id="from-a")
            b.add(fb, entry_id="from-b")  # b never reloaded manually; add must merge a's entry
            self.assertEqual([e["id"] for e in NoveltyStore(tmp).entries()], ["from-a", "from-b"])
            self.assertFalse(a.check(fb).novel)  # a notices b's clip via tail-reload
            self.assertEqual(a.check(fb).nearest_id, "from-b")
            self.assertFalse(b.check(fa).novel)

    def test_concurrent_threads_lose_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            stores = [NoveltyStore(tmp, max_entries=1000) for _ in range(4)]
            errs: list[Exception] = []

            def work(k: int) -> None:
                rng = np.random.default_rng(k)
                try:
                    for i in range(15):
                        stores[k].add(_rand_fp(rng), entry_id=f"t{k}-{i}")
                except Exception as e:  # pragma: no cover
                    errs.append(e)

            ts = [threading.Thread(target=work, args=(k,)) for k in range(4)]
            [t.start() for t in ts]
            [t.join() for t in ts]
            self.assertEqual(errs, [])
            ids = [e["id"] for e in NoveltyStore(tmp, max_entries=1000).entries()]
            self.assertEqual(len(ids), 60)
            self.assertEqual(len(set(ids)), 60)

    def test_concurrent_processes_lose_nothing_even_across_compaction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(__file__).resolve().parent.parent
            env = {**os.environ, "PYTHONPATH": str(root)}
            procs = [
                subprocess.Popen([sys.executable, "-c", _WORKER, tmp, f"w{k}", "12", "30"], cwd=str(root), env=env,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                for k in range(4)
            ]
            for p in procs:
                out, err = p.communicate(timeout=120)
                self.assertEqual(p.returncode, 0, err.decode(errors="replace")[-400:])
            # 48 adds, window 30: compaction ran under contention; the newest 30 must all survive intact
            entries = NoveltyStore(tmp, max_entries=30).entries()
            ids = [e["id"] for e in entries]
            self.assertEqual(len(ids), 30)
            self.assertEqual(len(set(ids)), 30)
            lines = (Path(tmp) / "fingerprints.jsonl").read_text(encoding="utf-8").splitlines()
            for ln in lines:
                json.loads(ln)  # no torn / interleaved lines
            # per-writer order is preserved
            for k in range(4):
                mine = [int(i.split("-")[1]) for i in ids if i.startswith(f"w{k}-")]
                self.assertEqual(mine, sorted(mine))

    def test_compaction_by_one_process_is_seen_by_another(self):
        with tempfile.TemporaryDirectory() as tmp:
            reader = NoveltyStore(tmp, max_entries=4)
            writer = NoveltyStore(tmp, max_entries=4)
            rng = np.random.default_rng(3)
            for i in range(12):
                writer.add(_rand_fp(rng), entry_id=f"c{i}")
            self.assertEqual([e["id"] for e in reader.entries()], ["c8", "c9", "c10", "c11"])
            self.assertFalse(reader.check(ClipFingerprint.from_dict(writer.entries()[-1]["fp"])).novel)

    def test_stale_lock_is_stolen(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / "fingerprints.lock"
            lock.write_text("999999")
            old = time.time() - 600
            os.utime(lock, (old, old))
            NoveltyStore(tmp).add(_rand_fp(np.random.default_rng(0)), entry_id="x")
            self.assertEqual(len(NoveltyStore(tmp)), 1)
            self.assertFalse(lock.exists())

    def test_legacy_json_store_is_imported_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            rng = np.random.default_rng(5)
            legacy = [{"id": f"old{i}", "t": 1, "seed": i, "prompt": "", "fp": _rand_fp(rng).to_dict()} for i in range(3)]
            (Path(tmp) / "fingerprints.json").write_text(json.dumps({"version": 1, "entries": legacy}), encoding="utf-8")
            s = NoveltyStore(tmp)
            self.assertEqual([e["id"] for e in s.entries()], ["old0", "old1", "old2"])
            s.add(_rand_fp(rng), entry_id="new")
            self.assertEqual(len(NoveltyStore(tmp)), 4)

    def test_default_window_is_5000_and_env_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = os.environ.pop("NOVELTY_STORE_MAX", None)
            try:
                self.assertEqual(NoveltyStore(tmp).max_entries, 5000)
                os.environ["NOVELTY_STORE_MAX"] = "123"
                self.assertEqual(NoveltyStore(tmp).max_entries, 123)
            finally:
                os.environ.pop("NOVELTY_STORE_MAX", None)
                if old is not None:
                    os.environ["NOVELTY_STORE_MAX"] = old

    def test_default_store_dir_honours_env(self):
        old = os.environ.get("NOVELTY_STORE_DIR")
        os.environ["NOVELTY_STORE_DIR"] = "/app/knowledge/novelty"
        try:
            self.assertEqual(default_store_dir(), Path("/app/knowledge/novelty"))
        finally:
            if old is None:
                os.environ.pop("NOVELTY_STORE_DIR")
            else:
                os.environ["NOVELTY_STORE_DIR"] = old

    def test_vectorised_distance_matches_scalar_distance(self):
        with tempfile.TemporaryDirectory() as tmp:
            rng = np.random.default_rng(9)
            s = NoveltyStore(tmp, max_entries=100)
            fps = [_rand_fp(rng, audio=(i % 3 != 0)) for i in range(25)]
            for i, f in enumerate(fps):
                s.add(f, entry_id=str(i))
            stored = [ClipFingerprint.from_dict(f.to_dict()) for f in fps]  # store rounds to 4 dp
            for q in (_rand_fp(rng), _rand_fp(rng, audio=False), fps[4]):
                d = s._distances(q)
                for i, f in enumerate(stored):
                    ref = fingerprint_distance(q, f)
                    for k in ("visual_hash", "palette", "audio", "combined"):
                        self.assertAlmostEqual(float(d[k][i]), ref[k], places=4, msg=f"{k}[{i}]")

    def test_5000_clip_window_check_is_fast(self):
        with tempfile.TemporaryDirectory() as tmp:
            rng = np.random.default_rng(11)
            lines = ['{"gen":"g","version":1}']
            for i in range(5000):
                lines.append(json.dumps({"id": f"e{i}", "t": 1, "seed": i, "prompt": "", "fp": _rand_fp(rng).to_dict()}))
            (Path(tmp) / "fingerprints.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
            s2 = NoveltyStore(tmp, max_entries=5000)
            self.assertEqual(len(s2), 5000)
            q = _rand_fp(rng)
            s2.check(q)  # builds the index
            t0 = time.perf_counter()
            for _ in range(5):
                s2.check(q)
            self.assertLess((time.perf_counter() - t0) / 5, 0.5)


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
            self.assertFalse(res.rejected)
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
            self.assertTrue(res.rejected)  # caller must skip: never publish a still-duplicate clip

    def test_fingerprint_failure_is_unchecked_not_novel(self):
        with tempfile.TemporaryDirectory() as tmp:
            def boom(path):
                raise RuntimeError("no codec")

            res = render_until_novel(lambda s: Path(tmp) / "x.mp4", NoveltyStore(tmp), seed=1, fingerprint_fn=boom)
            self.assertIsNone(res.content_novel)
            self.assertFalse(res.rejected)  # unchecked != duplicate
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