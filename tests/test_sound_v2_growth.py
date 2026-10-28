"""Sound v2 store, recorder, sampler, growth wiring and POST budget."""
from __future__ import annotations

import random

import pytest

from src.audio import sound as S
from src.knowledge import growth_per_instance as G
from src.knowledge import keyspace as K
from src.knowledge import sound_v2 as V
from src.knowledge.remote_sync import _chunk_discoveries
from src.knowledge.static_registry import load_static_registry

REACHABLE = [43, 746, 1407, 2015, 2539, 3190, 3938, 4620, 5136, 5656]


@pytest.fixture()
def cfg(tmp_path):
    return {"output": {"dir": str(tmp_path / "output")}}


def _seg(ordinal: int) -> dict:
    c = K.sound_v2_cell_center(ordinal)
    key = K.sound_v2_ordinal_to_key(ordinal)
    return {"amplitude": c["amplitude"], "weight": c["amplitude"], "peak_hz": c["peak_hz"], "v2_key": key,
            "spectral_flatness": c["spectral_flatness"], "attack_ratio": c["attack_ratio"], "zcr": c["zcr"],
            "evidence_tier": "observed"}


def test_record_observed_then_verified_on_reobservation(cfg):
    r1 = V.record_clip_cells([_seg(100), _seg(100), _seg(200)], config=cfg, source_prompt="clip 1")
    assert r1["new"] == 2 and set(r1["cells"].values()) == {"observed"}
    assert len(r1["payloads"]) == 2
    r2 = V.record_clip_cells([_seg(100)], config=cfg, source_prompt="clip 2")
    assert r2["new"] == 0 and r2["cells"][K.sound_v2_ordinal_to_key(100)] == "verified"
    assert r2["payloads"] == []  # already synced: a repeat never costs another row
    st = V.coverage_stats(cfg)
    assert st["covered"] == 2 and st["by_tier"] == {"observed": 1, "verified": 1}


def test_frames_within_one_clip_do_not_self_verify(cfg):
    r = V.record_clip_cells([_seg(300)] * 24, config=cfg)
    assert set(r["cells"].values()) == {"observed"}
    assert V.coverage_stats(cfg)["by_tier"]["verified"] == 0


def test_aimed_cell_measured_in_its_target_is_verified_aiming_alone_is_not(cfg):
    V.note_attempts([10, 11], cfg)
    assert V.coverage_stats(cfg)["covered"] == 0  # aiming is not coverage
    r = V.record_clip_cells([_seg(10)], config=cfg, targets=[10, 11])
    assert r["cells"][K.sound_v2_ordinal_to_key(10)] == "verified"
    assert V.coverage_stats(cfg)["covered"] == 1
    assert V.coverage_stats(cfg)["attempted_unseen"] == 1  # cell 11 was aimed at but never measured


def test_segments_without_v2_measurement_record_nothing(cfg):
    r = V.record_clip_cells([{"amplitude": 0.3, "tone": "mid"}], config=cfg)
    assert r == {"cells": {}, "new": 0, "payloads": []}


def test_payload_cap_per_clip_and_backlog_drains(cfg, monkeypatch):
    monkeypatch.setenv("SOUND_V2_MAX_PER_CLIP", "3")
    r = V.record_clip_cells([_seg(o) for o in range(500, 510)], config=cfg)
    assert r["new"] == 10 and len(r["payloads"]) == 3  # all recorded locally, only 3 leave
    r2 = V.record_clip_cells([_seg(900)], config=cfg)
    assert len(r2["payloads"]) == 3  # backlog drains a few per clip, never in one burst
    assert V.max_per_clip() == 3


def test_payload_shape_is_a_plain_static_sound_row(cfg):
    p = V.record_clip_cells([_seg(2015)], config=cfg, source_prompt="sound v2 cell survey")["payloads"][0]
    assert p["key"] == K.sound_v2_ordinal_to_key(2015) and p["key"].startswith("s2.")
    assert p["name"] == "sound.L1#02015" and p["evidence_tier"] == "observed"
    assert p["depth_breakdown"]["ordinal"] == 2015 and p["depth_breakdown"]["tier"] == "observed"
    assert 0 < p["strength_pct"] <= 100 and p["tone"].startswith("band")


def test_bitmap_roundtrip():
    ords = {0, 1, 5, 4095, 6143}
    assert V.decode_bitmap(V.encode_bitmap(ords)) == ords
    assert V.decode_bitmap("") == set() and V.decode_bitmap("zz") == set()
    assert len(V.encode_bitmap([])) == K.SOUND_V2_SPACE_SIZE // 4


def test_sampler_returns_only_unseen_cells_and_honours_remote_bitmap(cfg):
    V.record_clip_cells([_seg(o) for o in (1, 2, 3)], config=cfg)
    mission = {"sound_v2": {"seen_bitmap": V.encode_bitmap(range(4, 6000))}}
    picks = V.pick_unseen_cells(200, config=cfg, mission=mission, rng=random.Random(0))
    assert len(picks) == len(set(picks)) and picks
    assert not set(picks) & ({1, 2, 3} | set(range(4, 6000)))
    assert set(picks) <= set(range(6000, 6144)) | {0}


def test_sampler_deprioritises_cells_the_synth_cannot_hit(cfg):
    mission = {"sound_v2": {"seen_bitmap": V.encode_bitmap(set(range(K.SOUND_V2_SPACE_SIZE)) - {7, 8})}}
    for _ in range(V.UNREACHABLE_AFTER):
        V.note_attempts([7], cfg)
    first = [V.pick_unseen_cells(1, config=cfg, mission=mission, rng=random.Random(i))[0] for i in range(200)]
    assert first.count(8) > 150 and first.count(7) < 50  # still reachable, rarely drawn
    assert V.pick_unseen_cells(5, config=cfg, mission=mission, rng=random.Random(1))  # never starves
    assert sorted(V.pick_unseen_cells(5, config=cfg, mission=mission)) == [7, 8]


def test_sampler_deterministic_with_seeded_rng_and_empty_when_full(cfg):
    a = V.pick_unseen_cells(8, config=cfg, rng=random.Random(5))
    b = V.pick_unseen_cells(8, config=cfg, rng=random.Random(5))
    assert a == b and len(a) == 8
    full = {"sound_v2": {"seen_bitmap": V.encode_bitmap(range(K.SOUND_V2_SPACE_SIZE))}}
    assert V.pick_unseen_cells(8, config=cfg, mission=full) == []


def test_mission_targets_picker_wraps_sampler(cfg):
    from src.knowledge.mission_targets import pick_target_sound_v2_cells

    assert len(pick_target_sound_v2_cells(4, config=cfg, rng=random.Random(2))) == 4


def test_growth_records_v1_and_v2_from_a_decoded_synth_clip(cfg, tmp_path):
    from src.knowledge.extractor_per_instance import read_audio_segments_only

    wav = tmp_path / "v2.wav"
    S.generate_audio_only(2.0, wav, target_v2_cells=REACHABLE[:4], seed=3)
    segs = read_audio_segments_only(wav, fps=24, duration_seconds=2.0)
    assert segs and all("v2_key" in s and s["evidence_tier"] == "observed" for s in segs)
    added, novel = G.grow_static_sound_from_audio_segments(
        segs, prompt="survey", config=cfg, collect_novel_for_sync=True, v2_targets=REACHABLE[:4]
    )
    assert added["sound_v2"] >= 1
    v2_rows = [r for r in novel if str(r.get("key", "")).startswith("s2.")]
    assert len(v2_rows) == min(added["sound_v2"], V.max_per_clip())
    assert all(r["evidence_tier"] in ("observed", "verified") for r in v2_rows)
    # v1 keys still recorded in the v1 registry, v2 cells live in their own additive store
    assert not any(e["key"].startswith("s2.") for e in load_static_registry("sound", cfg)["entries"])
    assert V.coverage_stats(cfg)["covered"] == added["sound_v2"]


def test_growth_without_sync_records_locally_but_emits_no_payload(cfg):
    added, novel = G.grow_static_sound_from_audio_segments([_seg(55)], prompt="x", config=cfg)
    assert added["sound_v2"] == 1 and novel == []
    assert V.coverage_stats(cfg)["covered"] == 1


# --- POST budget: v2 rows never add a request or displace other items ------------------------------------

def _v2_rows(n):
    return [{"key": K.sound_v2_ordinal_to_key(i), "name": f"c{i}"} for i in range(n)]


def test_v2_rows_ride_in_leftover_budget_only(monkeypatch):
    monkeypatch.setenv("DISCOVERIES_MAX_ITEMS", "36")
    monkeypatch.setenv("SOUND_V2_MAX_PER_CLIP", "6")
    d = {"static_sound": _v2_rows(6), "motion": [{"key": f"m{i}"} for i in range(30)]}
    chunks = _chunk_discoveries(dict(d))
    assert len(chunks) == 1 and len(chunks[0]["static_sound"]) == 6
    tight = {"static_sound": _v2_rows(6), "motion": [{"key": f"m{i}"} for i in range(34)]}
    chunks = _chunk_discoveries(tight)
    assert len(chunks) == 1  # same number of POSTs as without v2
    assert len(chunks[0]["static_sound"]) == 2 and len(chunks[0]["motion"]) == 34
    full = {"static_sound": _v2_rows(6), "motion": [{"key": f"m{i}"} for i in range(36)]}
    chunks = _chunk_discoveries(full)
    assert len(chunks) == 1 and "static_sound" not in chunks[0]


def test_v1_rows_are_never_dropped_by_the_v2_cap(monkeypatch):
    monkeypatch.setenv("DISCOVERIES_MAX_ITEMS", "36")
    v1 = [{"key": f"0.{i}_mid_hum"} for i in range(5)]
    chunks = _chunk_discoveries({"static_sound": v1 + _v2_rows(40)})
    keys = [r["key"] for c in chunks for r in c.get("static_sound", [])]
    assert all(r["key"] in keys for r in v1)
    assert sum(k.startswith("s2.") for k in keys) <= 6