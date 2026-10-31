import numpy as np
import pytest

from src.knowledge import creative_colors, cross_axis, opacity_plane
from src.knowledge.color_cells import ColorCellStore, rgb_to_id


def test_opacity_cell_ids_and_levels():
    assert opacity_plane.alpha_level(0) == 0
    assert opacity_plane.alpha_level(255) == 15
    assert opacity_plane.alpha_level(1.0) == 15
    assert opacity_plane.alpha_level(0.5) == 8
    a = opacity_plane.cell_id(255, 255, 255, 255)
    assert a == opacity_plane.SPACE_SIZE - 1
    assert opacity_plane.cell_id(0, 0, 0, 0) == 0
    assert opacity_plane.cell_id(7, 7, 7, 0) == 0  # same 5-bit bin


def test_opacity_plane_mark_save_reload(tmp_path):
    op = opacity_plane.OpacityPlane(tmp_path)
    ids = opacity_plane.ids_from_layers([
        {"color": [255, 0, 0], "opacity": 0.5},
        {"color": "#00ff00", "alpha": 255},
        {"color": [0, 0, 255]},          # no opacity -> ignored
        {"opacity": 0.3},                # no colour -> ignored
    ])
    assert len(ids) == 2
    assert op.mark("declared", ids) == 2
    assert op.mark("declared", ids) == 0
    op.save()
    c = opacity_plane.OpacityPlane(tmp_path).counts()
    assert c["declared"] == 2 and c["covered"] == 2
    assert c["per_alpha_level"][15] == 1 and c["per_alpha_level"][8] == 1
    with pytest.raises(ValueError):
        op.mark("nope", [1])


def test_creative_flat_tiles_recorded_observed_with_cap(tmp_path):
    store = ColorCellStore(tmp_path)
    fr = np.zeros((64, 64, 3), dtype=np.uint8)
    fr[:32, :32] = (10, 20, 30)
    fr[:32, 32:] = (200, 100, 50)
    fr[32:, :32] = (1, 2, 3)
    fr[32:, 32:] = np.random.default_rng(0).integers(0, 256, (32, 32, 3), dtype=np.uint8)  # noisy, not flat
    frames = np.stack([fr, fr])
    res = creative_colors.record_frames(store, frames, max_new=2)
    assert res["flat_colors"] == 3 and res["new_cells"] == 2 and res["dropped_over_cap"] == 1
    again = creative_colors.record_frames(store, frames, max_new=10)
    assert again["new_cells"] == 1
    for rgb in [(10, 20, 30), (200, 100, 50), (1, 2, 3)]:
        assert store.tier_of(rgb_to_id(*rgb)) == "observed"


def test_sample_indices():
    assert creative_colors.sample_indices(0, 6) == []
    assert creative_colors.sample_indices(3, 6) == [0, 1, 2]
    assert creative_colors.sample_indices(100, 3) == [0, 50, 99]
    assert creative_colors.sample_indices(100, 1) == [50]


def test_creative_disabled_by_default(monkeypatch):
    monkeypatch.delenv("LOOP_CREATIVE_COLORS", raising=False)
    assert not creative_colors.enabled()
    monkeypatch.setenv("LOOP_CREATIVE_COLORS", "1")
    assert creative_colors.enabled()


def test_record_clip_never_raises(tmp_path):
    out = creative_colors.record_clip(tmp_path / "missing.mp4", store=ColorCellStore(tmp_path))
    assert "error" in out


def test_cross_axis_tracking(tmp_path):
    t = cross_axis.CrossAxisTracker(tmp_path)
    new = t.record({"palette_name": "Warm", "motion_type": "slow"})
    assert new == {"motion_typexpalette_name": 1}
    assert t.record({"palette_name": "warm", "motion_type": "slow"}) == {}
    t.record({"palette_name": "cool", "motion_type": "fast", "audio_mood": "calm"})
    r = t.report()
    assert r["clips"] == 3
    p = r["pairs"]["motion_typexpalette_name"]
    assert p == {"seen": 2, "universe": 4, "pct": 50.0}
    miss = t.missing_combinations("palette_name", "motion_type")
    assert sorted(miss) == [("fast", "warm"), ("slow", "cool")]


def test_cross_axis_reads_dataclass_attrs(tmp_path):
    class S:
        palette_name = "a"
        motion_type = "b"
        camera_motion = ""
    assert cross_axis.axis_values(S()) == {"palette_name": "a", "motion_type": "b"}
