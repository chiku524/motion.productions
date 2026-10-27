"""Registry lookup for video generation: local bitsets, snapshot export/import, input parsing."""
from __future__ import annotations

import numpy as np
import pytest

from src.knowledge.color_cells import ColorCellStore, rgb_to_id
from src.knowledge.registry_lookup import (
    SNAPSHOT_MAGIC,
    RegistryLookup,
    parse_cell,
)


@pytest.fixture()
def reg(tmp_path):
    store = ColorCellStore(tmp_path / "store")
    store.mark("verified", [rgb_to_id(255, 0, 0)])
    store.mark("observed", [rgb_to_id(0, 255, 0), rgb_to_id(0, 0, 255)])
    store.mark("declared", [rgb_to_id(1, 2, 3), rgb_to_id(255, 0, 0)])
    return RegistryLookup.from_store(store)


def test_parse_cell_forms():
    cid = rgb_to_id(18, 52, 86)
    for form in (cid, "#123456", "123456", "18,52,86", (18, 52, 86), [18, 52, 86], f"id:{cid}"):
        assert parse_cell(form) == cid
    for bad in (-1, 1 << 24, "zz", "12345", "1,2", (1, 2, 256), "#12345"):
        with pytest.raises(ValueError):
            parse_cell(bad)


def test_tiers_and_recorded(reg):
    assert reg.tier("#ff0000") == "verified"  # verified beats declared
    assert reg.tier((0, 255, 0)) == "observed"
    assert reg.tier((1, 2, 3)) == "declared"
    assert reg.tier((9, 9, 9)) == "none"
    assert reg.is_recorded("#ff0000") and reg.is_recorded("#00ff00")
    assert not reg.is_recorded((1, 2, 3))  # declared alone is not coverage
    assert not reg.is_recorded((9, 9, 9))


def test_lookup_records_and_vectorised(reg):
    rows = reg.lookup(["#ff0000", "1,2,3"])
    assert rows[0] == {"id": 0xFF0000, "rgb": [255, 0, 0], "hex": "#ff0000", "tier": "verified", "recorded": True}
    assert rows[1]["tier"] == "declared" and rows[1]["recorded"] is False
    ids = np.array([0xFF0000, 0x00FF00, 0x010203, 0x090909])
    assert reg.tier_codes(ids).tolist() == [3, 2, 1, 0]
    assert reg.recorded_mask(ids).tolist() == [True, True, False, False]


def test_palette_coverage(reg):
    frame = np.zeros((2, 3, 3), dtype=np.uint8)
    frame[0, 0] = (255, 0, 0)
    frame[0, 1] = (0, 255, 0)
    frame[0, 2] = (0, 255, 0)  # duplicates count once
    frame[1, 0] = (1, 2, 3)
    frame[1, 1] = (7, 7, 7)
    frame[1, 2] = (7, 7, 7)
    cov = reg.palette_coverage(frame)
    assert cov["distinct"] == 4 and cov["recorded"] == 2
    assert (cov["verified"], cov["observed"], cov["declared"], cov["none"]) == (1, 1, 1, 1)
    assert cov["fraction_recorded"] == 0.5


def test_snapshot_roundtrip_is_compact_and_exact(reg, tmp_path):
    path = tmp_path / "snap.mpcs"
    header = reg.export_snapshot(path)
    assert path.read_bytes().startswith(SNAPSHOT_MAGIC)
    assert header["bytes"] < 16 * 1024  # sparse registry compresses to almost nothing
    back = RegistryLookup.from_snapshot(path)
    assert back.meta["source"] == "snapshot"
    for p in ("observed", "verified", "declared"):
        assert np.array_equal(back.planes[p], reg.planes[p])
    assert back.counts() == reg.counts()
    assert back.tier("#00ff00") == "observed"


def test_snapshot_rejects_corruption(reg, tmp_path):
    path = tmp_path / "snap.mpcs"
    reg.export_snapshot(path)
    raw = bytearray(path.read_bytes())
    with pytest.raises(ValueError):
        RegistryLookup.from_snapshot(_write(tmp_path / "bad_magic", b"XXXXX" + bytes(raw[5:])))
    bad = bytearray(raw)
    bad[-3] ^= 0xFF
    with pytest.raises(Exception):  # zlib error or checksum mismatch, never a silent wrong answer
        RegistryLookup.from_snapshot(_write(tmp_path / "bad_body", bytes(bad)))


def _write(path, data):
    path.write_bytes(data)
    return path


def test_reflects_other_containers_bits_after_refresh(tmp_path):
    a = ColorCellStore(tmp_path / "s")
    b = ColorCellStore(tmp_path / "s")
    a.mark("observed", [rgb_to_id(10, 20, 30)])
    a.save()
    reg = RegistryLookup.from_store(b)  # refresh picks up a's bits
    assert reg.is_recorded((10, 20, 30))