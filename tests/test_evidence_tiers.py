"""Evidence tiers: observed / verified / declared, and the extractor measurements behind them."""
from __future__ import annotations

import numpy as np
import pytest

from src.knowledge import evidence as E
from src.knowledge import growth_per_instance as G
from src.knowledge.extractor_per_instance import measure_depth_proxy, measure_transition_duration


@pytest.fixture()
def cfg(tmp_path):
    return {"output": {"dir": str(tmp_path / "output")}}


# --- pure tier rules -------------------------------------------------------------------------------------

def test_only_observed_and_verified_cover():
    assert E.covers("observed") and E.covers("verified")
    assert not E.covers("declared") and not E.covers(None) and not E.covers("nonsense")


def test_best_tier_order():
    assert E.best_tier("declared", "observed") == "observed"
    assert E.best_tier("observed", "verified") == "verified"
    assert E.best_tier("verified", "declared") == "verified"


def test_window_defaults_keep_guessed_categories_declared():
    t = E.window_tiers({})
    for cat in ("camera", "audio_semantic", "transition", "depth"):
        assert t[cat] == "declared"
    for cat in ("motion", "lighting", "graphics", "time"):
        assert t[cat] == "observed"


def test_window_evidence_upgrades_measured_categories_only():
    t = E.window_tiers({"evidence": {"transition": "observed", "depth": "observed", "camera": "observed"}})
    assert t["transition"] == "observed" and t["depth"] == "observed"
    assert t["camera"] == "observed"  # the extractor is trusted to say so; it never does for camera today


def test_legacy_entries_classified_by_rule():
    assert E.entry_tier("transition", {"duration_seconds": 0.0}) == "declared"
    assert E.entry_tier("transition", {"duration_seconds": 0.5}) == "observed"
    assert E.entry_tier("camera", {"sources": ["a clip"]}) == "declared"
    assert E.entry_tier("depth", {"sources": ["a clip"]}) == "declared"
    assert E.entry_tier("audio_semantic", {"sources": ["a clip"]}) == "declared"
    assert E.entry_tier("motion", {"sources": ["a clip"]}) == "observed"
    # a pre-seeded primitive is never coverage, even in a measured category
    assert E.entry_tier("motion", {"sources": ["primitive_seed"]}) == "declared"
    assert E.entry_tier("motion", {"sources": ["primitive_seed"], "evidence_tier": "verified"}) == "verified"


def test_coverage_by_tier_counts():
    out = E.coverage_by_tier({
        "motion": [{"sources": ["x"]}, {"sources": ["primitive_seed"]}, {"evidence_tier": "verified"}],
        "camera": [{"sources": ["x"]}],
    })
    assert out["motion"] == {"observed": 1, "verified": 1, "declared": 1, "covered": 2}
    assert out["camera"]["covered"] == 0 and out["camera"]["declared"] == 1


# --- extractor measurements ----------------------------------------------------------------------------

def _clip(kind: str, n: int = 48, seed: int = 0):
    rng = np.random.default_rng(seed)
    a = np.full((32, 32, 3), 40, np.uint8)
    b = np.full((32, 32, 3), 220, np.uint8)
    frames = []
    for i in range(n):
        if kind == "cut":
            f = a if i < n // 2 else b
        elif kind == "dissolve":
            lo, hi = n // 2 - 5, n // 2 + 5
            t = min(1.0, max(0.0, (i - lo) / (hi - lo)))
            f = (a * (1 - t) + b * t).astype(np.uint8)
        else:
            f = a
        noise = rng.integers(0, 2, f.shape, dtype=np.uint8)
        frames.append(np.clip(f.astype(int) + noise, 0, 255).astype(np.uint8))
    return frames


def test_transition_duration_cut_is_zero_and_dissolve_is_positive():
    cut = measure_transition_duration(_clip("cut"), 24, 24.0)
    dis = measure_transition_duration(_clip("dissolve"), 24, 24.0)
    assert cut == 0.0
    assert dis is not None and dis >= 0.2
    assert dis > cut


def test_transition_duration_none_when_unmeasurable():
    assert measure_transition_duration(_clip("static", n=3), 1, 24.0) is None
    assert measure_transition_duration(_clip("cut"), 0, 24.0) is None


def test_depth_proxy_flat_vs_parallax():
    flat = measure_depth_proxy([np.full((3, 3), 4.0) for _ in range(4)])
    assert flat is not None and flat["parallax_strength"] == 0.0 and flat["layer_count"] == 1
    g = np.array([[0.2, 0.2, 0.2], [1.0, 1.0, 1.0], [8.0, 8.0, 8.0]])
    deep = measure_depth_proxy([g for _ in range(4)])
    assert deep is not None and deep["parallax_strength"] > 0.5 and deep["layer_count"] >= 2
    assert measure_depth_proxy([]) is None


# --- registry growth stamps tiers ---------------------------------------------------------------------

def _entries(cfg, aspect):
    from src.knowledge.dynamic_registry import load_dynamic_registry

    return {e["key"]: e for e in load_dynamic_registry(aspect, cfg).get("entries", [])}


def test_unmeasured_window_records_declared_camera_depth_transition(cfg):
    window = {
        "camera": {"motion_type": "pan", "speed": "slow"},
        "transition": {"type": "cut", "duration_seconds": 0.0},
        "depth": {"parallax_strength": 0.0, "layer_count": 1},
        "motion": {"level": 3.0, "std": 1.0, "trend": "steady", "direction": "none", "rhythm": "steady"},
    }
    out: list = []
    G.ensure_dynamic_camera_in_registry(window, config=cfg, out_novel=out)
    G.ensure_dynamic_transition_in_registry(window, config=cfg, out_novel=out)
    G.ensure_dynamic_depth_in_registry(window, config=cfg, out_novel=out)
    assert out and all(p["evidence_tier"] == "declared" for p in out)
    for aspect in ("camera", "transition", "depth"):
        for e in _entries(cfg, aspect).values():
            assert e["evidence_tier"] == "declared"


def test_measured_window_records_observed(cfg):
    window = {
        "transition": {"type": "dissolve", "duration_seconds": 0.5, "measured": True},
        "depth": {"parallax_strength": 0.4, "layer_count": 3},
        "evidence": {"transition": "observed", "depth": "observed"},
    }
    out: list = []
    G.ensure_dynamic_transition_in_registry(window, config=cfg, out_novel=out)
    G.ensure_dynamic_depth_in_registry(window, config=cfg, out_novel=out)
    assert {p["evidence_tier"] for p in out} == {"observed"}


def test_declared_entry_upgrades_when_later_measured(cfg):
    declared = {"depth": {"parallax_strength": 0.4, "layer_count": 3}}
    G.ensure_dynamic_depth_in_registry(declared, config=cfg)
    assert next(iter(_entries(cfg, "depth").values()))["evidence_tier"] == "declared"
    G.ensure_dynamic_depth_in_registry({**declared, "evidence": {"depth": "observed"}}, config=cfg)
    assert next(iter(_entries(cfg, "depth").values()))["evidence_tier"] == "observed"
    G.ensure_dynamic_depth_in_registry(declared, config=cfg)  # a later guess never downgrades
    assert next(iter(_entries(cfg, "depth").values()))["evidence_tier"] == "observed"


def test_seeding_is_declared_everywhere(cfg):
    G.ensure_dynamic_primitives_seeded(cfg)
    from src.knowledge.dynamic_registry import load_dynamic_registry

    seen = 0
    for aspect in G.DYNAMIC_ASPECTS:
        for e in load_dynamic_registry(aspect, cfg).get("entries", []):
            seen += 1
            assert e["evidence_tier"] == "declared", (aspect, e["key"])
    assert seen > 50


def test_static_sound_tier_follows_the_source(cfg):
    spec_sound = {"amplitude": 0.31, "weight": 0.31, "tone": "mid", "timbre": "hum"}
    G.ensure_static_sound_in_registry(spec_sound, source_prompt="a prompt", config=cfg)
    measured = {**spec_sound, "amplitude": 0.52, "weight": 0.52, "evidence_tier": "observed"}
    G.ensure_static_sound_in_registry(measured, source_prompt="a clip", config=cfg)
    from src.knowledge.static_registry import load_static_registry

    tiers = {e["key"]: e["evidence_tier"] for e in load_static_registry("sound", cfg)["entries"]}
    assert tiers[G._static_sound_key(spec_sound)] == "declared"
    assert tiers[G._static_sound_key(measured)] == "observed"


def test_out_novel_payload_carries_tier(cfg):
    out: list = []
    G.ensure_static_sound_in_registry(
        {"amplitude": 0.44, "weight": 0.44, "tone": "low", "timbre": "rumble", "evidence_tier": "observed"},
        source_prompt="clip", config=cfg, out_novel=out,
    )
    assert out and out[0]["evidence_tier"] == "observed"