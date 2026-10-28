"""Survey clips: layout, H.264 round-trip tolerance, end-to-end verification into the store."""
from __future__ import annotations

import numpy as np
import pytest

from src.knowledge import color_survey as cs
from src.knowledge.color_cells import ColorCellStore, ColorWorkQueue, ids_to_rgb_array

SMALL = cs.SurveySettings(tile=16, rows=4, cols=4, fps=4, seconds=1.0)  # 4 frames x 16 tiles = 64 cells
pytestmark = pytest.mark.skipif(
    pytest.importorskip("imageio_ffmpeg", reason="needs imageio-ffmpeg") is None, reason="ffmpeg"
)


def test_layout_and_frames():
    ids = np.arange(70, dtype=np.int64) * 1000
    tid, valid = cs.layout_cells(ids, SMALL)
    assert tid.shape == (4, 4, 4) and valid.sum() == 64  # extra cells ignored, never dropped silently by the queue
    short_ids, short_valid = cs.layout_cells(ids[:10], SMALL)
    assert short_valid.sum() == 10
    frames = cs.build_frames(short_ids, short_valid, SMALL)
    assert frames.shape == (4, 64, 64, 3) and frames.dtype == np.uint8
    assert tuple(frames[0, 0, 0]) == tuple(ids_to_rgb_array(short_ids)[0, 0, 0])
    assert tuple(frames[3, 63, 63]) == (128, 128, 128)  # padding is grey


def _roundtrip(profile, n=300):
    return cs.measure_codec_tolerance(profile, n_colors=n, seed=3, st=SMALL.__class__(tile=32, rows=8, cols=8, fps=8))


def test_lossless_profile_roundtrips_exactly():
    m = _roundtrip("lossless")
    assert m["max_abs_err"] == 0 and m["exact_fraction"] == 1.0 and m["colors"] > 250


def test_production_profile_error_is_bounded_by_its_tolerance():
    m = _roundtrip("production")
    assert 0 < m["max_abs_err"] <= cs.PROFILES["production"].tol  # not exact: yuv420p limited range
    assert m["exact_fraction"] < 0.5


def test_survey_clip_marks_verified_and_cleans_up(tmp_path):
    store = ColorCellStore(tmp_path / "store")
    q = ColorWorkQueue(store, 0, 1)
    work = tmp_path / "work"
    work.mkdir()
    res = cs.run_survey_clip(store, q, SMALL, tmp_dir=work)
    assert (res.targets, res.verified, res.failed, res.mismatches, res.max_err) == (64, 64, 0, 0, 0)
    assert res.profile == "lossless" and not res.fallback
    assert not list(work.iterdir()), "survey clip must not be kept"
    c = ColorCellStore(tmp_path / "store").counts()
    assert c["verified"] == 64 and c["covered"] == 64 and c["declared_only"] == 0
    nxt = q.next_cells(64, consume=False)
    assert not store.covered_mask(nxt).any()  # the queue moved on to unseen cells


def test_production_profile_verifies_within_tolerance(tmp_path):
    st = cs.SurveySettings(tile=16, rows=4, cols=4, fps=4, profile="production")
    store = ColorCellStore(tmp_path)
    res = cs.run_survey_clip(store, ColorWorkQueue(store, 0, 1), st)
    assert res.profile == "production" and res.targets == 64
    assert res.max_err <= cs.PROFILES["production"].tol
    assert res.verified + res.failed == 64
    # anything off-target by >0 was still recorded as the decoded (observed) colour
    assert store.counts()["covered"] >= res.verified


def test_codec_damage_marks_observed_and_failed(tmp_path, monkeypatch):
    store = ColorCellStore(tmp_path)
    q = ColorWorkQueue(store, 0, 1)
    real = cs.decode_frames

    def damaged(path):
        d = real(path).copy()
        d[:, 0:16, 0:16] = (d[:, 0:16, 0:16].astype(int) + 9).clip(0, 255).astype(np.uint8)  # tile (0,0): shifted colour
        d[:, 16:32, 0:16] = np.random.default_rng(0).integers(0, 256, d[:, 16:32, 0:16].shape, dtype=np.uint8)  # (1,0): noise
        return d

    monkeypatch.setattr(cs, "decode_frames", damaged)
    res = cs.run_survey_clip(store, q, SMALL)
    assert res.targets == 64 and res.failed == 8 and res.mismatches > 0
    assert res.verified == 56
    c = store.counts()
    assert c["verified"] == 56 and c["observed"] >= 1 and c["declared_only"] >= 1


def test_encoder_failure_falls_back_to_production(tmp_path, monkeypatch):
    store = ColorCellStore(tmp_path)
    real = cs.encode_frames

    def flaky(frames, path, profile, fps):
        if profile.name == "lossless":
            raise RuntimeError("no libx264rgb")
        return real(frames, path, profile, fps)

    monkeypatch.setattr(cs, "encode_frames", flaky)
    monkeypatch.setattr(cs, "_BROKEN_PROFILES", set())
    res = cs.run_survey_clip(store, ColorWorkQueue(store, 0, 1), SMALL)
    assert res.fallback and res.profile == "production"


def test_iteration_never_raises_and_respects_env(tmp_path, monkeypatch):
    monkeypatch.setenv("COLOR_CELLS_DIR", str(tmp_path))
    monkeypatch.setenv("COLOR_SURVEY_GRID", "4")
    monkeypatch.setenv("COLOR_SURVEY_TILE", "16")
    monkeypatch.setenv("COLOR_SURVEY_FPS", "4")
    monkeypatch.setenv("CONTAINER_INDEX", "1")
    monkeypatch.setenv("CONTAINER_COUNT", "2")
    out = cs.run_survey_iteration("", clips=2, sync=False)
    assert out["clips"] == 2 and out["verified"] == 128 and out["stride"] == [1, 2]
    monkeypatch.setattr(cs, "SurveySettings", None)  # force an exception inside
    assert "error" in cs.run_survey_iteration("", clips=1, sync=False)


def test_survey_enabled_flag(monkeypatch):
    monkeypatch.delenv("LOOP_COLOR_SURVEY", raising=False)
    assert not cs.survey_enabled()
    monkeypatch.setenv("LOOP_COLOR_SURVEY", "1")
    assert cs.survey_enabled()