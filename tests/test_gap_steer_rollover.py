"""Gap steering (LOOP_GAP_STEER) and idle-budget rollover (D1_ROLLOVER)."""
from __future__ import annotations

import itertools

import numpy as np
import pytest

from src.knowledge import gap_steer
from src.knowledge.color_cells import PLANE_BYTES, rgb_to_id
from src.knowledge.cross_axis import CrossAxisTracker
from src.knowledge.write_budget import WriteBudget


def _seq(*vals):
    it = itertools.cycle(vals)
    return lambda: next(it)


@pytest.fixture(autouse=True)
def _clear_cache():
    gap_steer._cache.update(t=0.0, weights=None)
    yield
    gap_steer._cache.update(t=0.0, weights=None)


def test_family_weights_skip_covered_cells():
    plane = np.full(PLANE_BYTES, 0xFF, dtype=np.uint8)  # everything covered
    assert gap_steer.family_gap_weights(plane) == {}
    empty = np.zeros(PLANE_BYTES, dtype=np.uint8)
    w = gap_steer.family_gap_weights(empty)
    assert abs(sum(w.values()) - 1.0) < 1e-9 and "blue" in w


def test_family_weights_favour_uncovered_family():
    # cover every sampled cell except the "red" ones: only red can be steered to
    from src.knowledge.mission_targets import classify_color_family_rgb
    from src.knowledge.color_cells import id_to_rgb, bits_set
    rng = np.random.default_rng(1729)
    ids = rng.integers(0, 1 << 24, size=gap_steer.SAMPLE_N, dtype=np.int64)
    plane = np.zeros(PLANE_BYTES, dtype=np.uint8)
    keep = np.array([i for i in ids.tolist() if classify_color_family_rgb(*id_to_rgb(i)) != "red"], dtype=np.int64)
    bits_set(plane, keep)
    w = gap_steer.family_gap_weights(plane)
    assert set(w) == {"red"}
    assert gap_steer.gap_family(_seq(0.3), plane_loader=lambda: plane) == "red"


def test_steer_disabled_or_unlucky(monkeypatch):
    monkeypatch.delenv("LOOP_GAP_STEER", raising=False)
    assert gap_steer.steer(_seq(0.0)) is None
    monkeypatch.setenv("LOOP_GAP_STEER", "1")
    monkeypatch.setenv("LOOP_GAP_STEER_P", "0.7")
    assert gap_steer.steer(_seq(0.9), plane_loader=lambda: np.zeros(PLANE_BYTES, np.uint8)) is None  # randomness kept


def test_steer_family_and_missing_pair(monkeypatch, tmp_path):
    monkeypatch.setenv("LOOP_GAP_STEER", "1")
    monkeypatch.setenv("LOOP_GAP_STEER_PAIR_P", "1")
    t = CrossAxisTracker(tmp_path)
    t.record({"palette_name": "ocean", "motion_type": "drift"})
    t.record({"palette_name": "ember", "motion_type": "pulse"})
    out = gap_steer.steer(_seq(0.1), plane_loader=lambda: np.zeros(PLANE_BYTES, np.uint8), tracker=t)
    assert out and out["family"]
    assert out["pair"] == "palette_namexmotion_type"
    assert set(out["phrases"]) in ({"ember", "drift"}, {"ocean", "pulse"})


def test_steer_queue_worker_keeps_stride_family(monkeypatch, tmp_path):
    monkeypatch.setenv("LOOP_GAP_STEER", "1")
    monkeypatch.setenv("LOOP_GAP_STEER_PAIR_P", "0")
    assert gap_steer.steer(_seq(0.1), use_queue=True, tracker=CrossAxisTracker(tmp_path)) is None


def test_prompt_uses_gap_family_and_phrases():
    from src.automation.prompt_gen import generate_mission_prompt
    p = generate_mission_prompt(kind="frame", focus="color", mission={}, family="pink", extra_phrases=["ember", "drift"])
    assert p and "drift" in p.lower()


def test_rgb_helper_sanity():
    assert rgb_to_id(0, 0, 0) == 0


# -- rollover --------------------------------------------------------------------------------------------------
DAY0 = 1793404800.0  # 2026-10-31T00:00Z


def _wb(tmp_path, name, t, budget=50000):
    return WriteBudget(name=name, directory=tmp_path, daily_budget=budget, clock=lambda: t)


def test_rollover_off_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("D1_ROLLOVER", raising=False)
    t = DAY0 + 23 * 3600
    ex = _wb(tmp_path, "explorer", t)
    assert ex.rollover_status()["active"] is False
    assert ex.remaining() == ex.allowance()


def test_rollover_lends_only_behind_pace_and_only_late(tmp_path, monkeypatch):
    monkeypatch.setenv("D1_ROLLOVER", "1")
    monkeypatch.setenv("D1_ROLLOVER_FRACTION", "0.5")
    early = DAY0 + 12 * 3600
    assert _wb(tmp_path, "explorer", early).rollover_status()["active"] is False
    t = DAY0 + 21 * 3600  # in the last 4 h
    snd = _wb(tmp_path, "sound", t)
    assert snd.reserve(100)  # sound far behind its pace line (5000 x 0.875 = 4375)
    bal = _wb(tmp_path, "balanced", t)
    assert bal.reserve(bal.allowance())  # balanced at its cap: lends nothing
    ex = _wb(tmp_path, "explorer", t)
    st = ex.rollover_status()
    assert st["active"] and "balanced" not in st["lenders"]
    assert st["lenders"]["sound"] == int((5000 * 0.875 - 100) * 0.5)
    assert ex.remaining() == ex.allowance() + st["lent"]
    # a non-borrower never gets more than its own allowance
    assert _wb(tmp_path, "interpret", t).remaining() == _wb(tmp_path, "interpret", t).allowance()


def test_rollover_never_exceeds_global_budget(tmp_path, monkeypatch):
    monkeypatch.setenv("D1_ROLLOVER", "1")
    monkeypatch.setenv("D1_ROLLOVER_FRACTION", "1")
    t = DAY0 + 23.5 * 3600
    ex = _wb(tmp_path, "explorer", t, budget=1000)
    # explorer allowance 350; lenders idle -> big loan, but the global 1000 cap holds
    assert ex.reserve(ex.allowance())
    assert ex.reserve(400)
    assert ex.snapshot()["containers"]["explorer"]["used"] <= 1000
    assert not ex.reserve(1000 - 750 + 1)


def test_rollover_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("D1_ROLLOVER", "1")
    t = DAY0 + 23 * 3600
    ex = _wb(tmp_path, "explorer", t)
    monkeypatch.setattr(ex, "_bucket_used", lambda *a: (_ for _ in ()).throw(RuntimeError("x")))
    assert ex.rollover_detail({"containers": {}}, t)["lent"] == 0


def test_loop_metrics_shows_rollover(tmp_path, monkeypatch):
    monkeypatch.setenv("D1_ROLLOVER", "1")
    import importlib, sys
    sys.path.insert(0, "scripts")
    lm = importlib.import_module("loop_metrics")
    t = DAY0 + 22 * 3600
    _wb(tmp_path, "sound", t).reserve(10)
    b = lm.budget_report(tmp_path, now=t)
    assert b["rollover"]["active"] is True
    assert "Rollover ACTIVE" in lm.render_budget(b)
