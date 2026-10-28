"""Exact 8-bit colour cells: ids, Feistel permutation, bitset store, stride queue."""
from __future__ import annotations

import json
import threading
from pathlib import Path

import numpy as np
import pytest

from src.knowledge import color_cells as cc

VECTORS = json.loads((Path(__file__).parent / "vectors" / "color_cells_vectors.json").read_text())


def test_vectors_match_helpers():
    assert VECTORS["size"] == cc.SPACE_SIZE and VECTORS["n_chunks"] == cc.N_CHUNKS
    assert VECTORS["chunk_bytes"] == cc.CHUNK_BYTES and VECTORS["chunk_cells"] == cc.CHUNK_CELLS
    for v in VECTORS["cells"]:
        r, g, b = v["rgb"]
        i = cc.rgb_to_id(r, g, b)
        assert i == v["id"] and cc.id_to_rgb(i) == (r, g, b) and cc.id_to_hex(i) == v["hex"]
        assert cc.chunk_of(i) == v["chunk"] == (r >> 3)
        assert i >> 3 == v["byte"] and (1 << (i & 7)) == v["mask"]
        assert (i >> 3) % cc.CHUNK_BYTES == v["chunk_byte"]
        assert list(cc.l1_key(i)) == v["l1"] and list(cc.l0_key(i)) == v["l0"]


def test_id_range_checks():
    with pytest.raises(ValueError):
        cc.rgb_to_id(256, 0, 0)
    with pytest.raises(ValueError):
        cc.id_to_rgb(cc.SPACE_SIZE)
    rgb = np.array([[1, 2, 3], [255, 254, 253]], dtype=np.uint8)
    ids = cc.rgb_array_to_ids(rgb)
    assert ids.tolist() == [0x010203, 0xFFFEFD]
    assert np.array_equal(cc.ids_to_rgb_array(ids), rgb)


def test_feistel_is_a_bijection_on_the_whole_space():
    perm = cc.FeistelPermutation(seed=12345)
    out = perm.permute_array(np.arange(cc.SPACE_SIZE, dtype=np.uint32))
    seen = np.zeros(cc.SPACE_SIZE, dtype=bool)
    seen[out] = True
    assert seen.all()
    sample = np.random.default_rng(1).integers(0, cc.SPACE_SIZE, 50_000).astype(np.uint32)
    assert np.array_equal(perm.invert_array(perm.permute_array(sample)), sample)
    assert perm.invert(perm.permute(777)) == 777


def test_feistel_is_seeded_and_scrambles():
    a = cc.FeistelPermutation(1).permute_array(np.arange(1000, dtype=np.uint32))
    b = cc.FeistelPermutation(1).permute_array(np.arange(1000, dtype=np.uint32))
    c = cc.FeistelPermutation(2).permute_array(np.arange(1000, dtype=np.uint32))
    assert np.array_equal(a, b) and not np.array_equal(a, c)
    # consecutive positions land all over the cube, not along one axis
    first = cc.FeistelPermutation(1).permute_array(np.arange(20_000, dtype=np.uint32))
    for shift in (16, 8, 0):
        assert len(np.unique((first >> shift) & 255)) > 240


def test_bitset_set_test_popcount():
    plane = np.zeros(cc.PLANE_BYTES, dtype=np.uint8)
    ids = np.array([0, 1, 7, 8, 1000, cc.SPACE_SIZE - 1, 1000])
    cc.bits_set(plane, ids)
    assert cc.popcount(plane) == 6
    probe = np.array([0, 1, 2, 7, 8, 9, 1000, cc.SPACE_SIZE - 1])
    assert cc.bits_test(plane, probe).tolist() == [True, True, False, True, True, False, True, True]


def test_store_roundtrip_and_tiers(tmp_path):
    s = cc.ColorCellStore(tmp_path)
    s.mark("observed", [10, 11])
    s.mark("verified", [11, 12])
    s.mark("declared", [13])
    assert s.save()
    t = cc.ColorCellStore(tmp_path)
    assert [t.tier_of(i) for i in (10, 11, 12, 13, 14)] == ["observed", "verified", "verified", "declared", "none"]
    c = t.counts()
    assert (c["observed"], c["verified"], c["declared"], c["covered"], c["declared_only"]) == (2, 2, 1, 3, 1)
    for p in cc.PLANES:
        assert (tmp_path / f"{p}.bits").stat().st_size == cc.PLANE_BYTES == 2 * 1024 * 1024
    assert not list(tmp_path.glob("*.tmp"))


def test_two_stores_merge_instead_of_overwrite(tmp_path):
    a, b = cc.ColorCellStore(tmp_path), cc.ColorCellStore(tmp_path)
    a.mark("observed", [1, 2, 3])
    b.mark("observed", [3, 4, 5_000_000])
    a.save()
    b.save()  # must OR with a's file, not replace it
    c = cc.ColorCellStore(tmp_path)
    assert all(c.tier_of(i) == "observed" for i in (1, 2, 3, 4, 5_000_000))
    a.refresh()
    assert a.tier_of(4) == "observed"


def test_concurrent_saves_lose_nothing(tmp_path):
    stores = [cc.ColorCellStore(tmp_path) for _ in range(6)]

    def work(k: int):
        s = stores[k]
        s.record_outcome(verified=[k * 1000 + j for j in range(50)], failed=[900_000 + k])

    ts = [threading.Thread(target=work, args=(k,)) for k in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    final = cc.ColorCellStore(tmp_path)
    assert final.counts()["verified"] == 300
    assert final.counts()["declared_only"] == 6


def test_merge_chunks(tmp_path):
    s = cc.ColorCellStore(tmp_path)
    raw = bytearray(cc.CHUNK_BYTES)
    raw[0] = 0b101
    s.merge_chunks("observed", {3: bytes(raw)})
    base = 3 * cc.CHUNK_CELLS
    assert s.tier_of(base) == "observed" and s.tier_of(base + 1) == "none" and s.tier_of(base + 2) == "observed"
    with pytest.raises(ValueError):
        s.merge_chunks("observed", {3: b"short"})
    assert cc.chunk_bytes(s.planes["observed"], 3)[0] == 0b101
    assert len(cc.chunk_pack(bytes(raw))) < 200


def test_strides_are_disjoint_and_deterministic(tmp_path):
    s = cc.ColorCellStore(tmp_path)
    qs = [cc.ColorWorkQueue(s, i, 4) for i in range(4)]
    picks = [q.next_cells(3000, consume=False) for q in qs]
    allc = np.concatenate(picks)
    assert len(allc) == 12_000 and len(np.unique(allc)) == 12_000
    again = cc.ColorWorkQueue(cc.ColorCellStore(tmp_path), 2, 4).next_cells(3000, consume=False)
    assert np.array_equal(again, picks[2])
    # positions themselves are disjoint across the whole space
    pos = [q.positions(0, 50_000) for q in qs]
    assert len(np.unique(np.concatenate(pos))) == sum(len(p) for p in pos)


def test_queue_skips_covered_and_advances(tmp_path):
    s = cc.ColorCellStore(tmp_path)
    q = cc.ColorWorkQueue(s, 0, 2)
    first = q.next_cells(8, consume=False)
    s.mark("observed", first[:3])
    s.mark("verified", first[3:5])
    nxt = q.next_cells(8)
    assert not set(nxt.tolist()) & set(first[:5].tolist())
    assert set(first[5:].tolist()) <= set(nxt.tolist())
    q2 = cc.ColorWorkQueue(s, 0, 2)  # cursor persisted
    assert q2.cursor == q.cursor > 0
    assert not set(q2.next_cells(8).tolist()) & set(nxt.tolist())


def test_failed_cells_are_quarantined(tmp_path):
    s = cc.ColorCellStore(tmp_path)
    q = cc.ColorWorkQueue(s, 0, 1)
    bad = int(q.next_cells(1, consume=False)[0])
    for _ in range(cc.MAX_ATTEMPTS):
        s.record_outcome(failed=[bad])
    assert s.counts()["quarantined"] == 1
    assert bad not in set(cc.ColorWorkQueue(s, 0, 1).next_cells(50, consume=False).tolist())
    s.record_outcome(observed=[bad])
    assert s.counts()["quarantined"] == 0


def test_worker_identity_env_and_hostname(monkeypatch):
    monkeypatch.setenv("CONTAINER_INDEX", "3")
    monkeypatch.setenv("CONTAINER_COUNT", "5")
    assert cc.worker_identity() == (3, 5)
    monkeypatch.delenv("CONTAINER_INDEX")
    monkeypatch.delenv("CONTAINER_COUNT")
    monkeypatch.setenv("COLOR_WORKER_COUNT", "6")
    i, n = cc.worker_identity()
    assert n == 6 and 0 <= i < 6 and cc.worker_identity() == (i, n)


def test_seed_is_shared_through_meta(tmp_path, monkeypatch):
    monkeypatch.setenv("COLOR_QUEUE_SEED", "4242")
    a = cc.ColorCellStore(tmp_path)
    monkeypatch.setenv("COLOR_QUEUE_SEED", "9999")
    b = cc.ColorCellStore(tmp_path)
    assert a.seed == b.seed == 4242