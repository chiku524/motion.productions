from __future__ import annotations

import json

from src.knowledge import keyspace as K
from src.knowledge import sound_v2 as V
from src.knowledge.dynamic_registry import load_dynamic_registry, save_dynamic_registry
from src.knowledge.tier_report import local_tier_coverage


def test_report_splits_tiers_and_declared_never_covers(tmp_path):
    cfg = {"output": {"dir": str(tmp_path / "output")}}
    reg = load_dynamic_registry("camera", cfg)
    reg["entries"] = [
        {"key": "pan", "count": 3, "sources": ["clip 1"]},
        {"key": "tilt", "count": 1, "sources": ["primitive_seed"]},
    ]
    save_dynamic_registry("camera", reg, cfg)
    reg = load_dynamic_registry("motion", cfg)
    reg["entries"] = [
        {"key": "fast", "count": 2, "sources": ["clip 1"]},
        {"key": "slow", "count": 1, "sources": ["seed"]},
        {"key": "v", "count": 1, "sources": ["clip 2"], "evidence_tier": "verified"},
    ]
    save_dynamic_registry("motion", reg, cfg)
    cell = K.sound_v2_cell_center(77)
    V.record_clip_cells(
        [{"amplitude": cell["amplitude"], "peak_hz": cell["peak_hz"], "v2_key": K.sound_v2_ordinal_to_key(77)}],
        config=cfg,
    )
    r = local_tier_coverage(cfg)
    cam = r["categories"]["camera"]
    assert cam["declared"] == 2 and cam["covered"] == 0  # camera is guessed from motion: never coverage
    mot = r["categories"]["motion"]
    assert (mot["observed"], mot["verified"], mot["declared"], mot["covered"]) == (1, 1, 1, 2)
    assert r["sound_v2"]["covered"] == 1 and r["sound_v2"]["by_tier"]["observed"] == 1
    assert r["totals"]["covered"] >= 2
    json.dumps(r)  # additive, JSON-serialisable


def test_exact_color_section_reads_local_bitsets_and_never_creates_the_store(tmp_path):
    from src.knowledge.color_cells import ColorCellStore, rgb_to_id
    from src.knowledge.tier_report import exact_color_coverage

    missing = tmp_path / "nope"
    assert exact_color_coverage(missing) == {"available": False}
    assert not missing.exists()  # reporting must not create state

    store = ColorCellStore(tmp_path / "cc")
    store.mark("verified", [rgb_to_id(1, 2, 3), rgb_to_id(4, 5, 6)])
    store.mark("observed", [rgb_to_id(7, 8, 9)])
    store.mark("declared", [rgb_to_id(10, 11, 12)])
    store.save()
    r = exact_color_coverage(tmp_path / "cc")
    assert r["available"] and r["size"] == 1 << 24
    assert (r["verified"], r["observed"], r["declared"], r["covered"], r["declared_only"]) == (2, 1, 1, 3, 1)
    json.dumps(r)


def test_exact_color_remote_counts_are_optional_and_failure_tolerant(tmp_path):
    from src.knowledge.tier_report import exact_color_coverage

    ok = exact_color_coverage(tmp_path / "x", "http://api", get=lambda *a, **k: {"covered": 5})
    assert ok["remote"] == {"covered": 5}

    def boom(*a, **k):
        raise OSError("offline")

    assert exact_color_coverage(tmp_path / "x", "http://api", get=boom)["remote"] is None


def test_local_report_includes_exact_color_key(tmp_path, monkeypatch):
    monkeypatch.setenv("COLOR_CELLS_DIR", str(tmp_path / "empty"))
    r = local_tier_coverage({"output": {"dir": str(tmp_path / "output")}})
    assert r["exact_color"] == {"available": False}