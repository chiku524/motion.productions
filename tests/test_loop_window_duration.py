"""LOOP_WINDOW_LONG_SHARE: optional 3-6 s window runs (default off)."""
from __future__ import annotations

import importlib.util
from pathlib import Path


WINDOW = "a moving window blend across a motion window of rust and teal"
FRAME = "a still frame of rust and teal in a static frame"


def _loop():
    path = Path(__file__).resolve().parents[1] / "scripts" / "automate_loop.py"
    spec = importlib.util.spec_from_file_location("automate_loop_window_long_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_default_unchanged(monkeypatch):
    monkeypatch.delenv("LOOP_WINDOW_LONG_SHARE", raising=False)
    m = _loop()
    assert m.long_window_duration(WINDOW, 1.0, rng_value=0.0) == 1.0


def test_share_one_stretches_window_into_3_to_6(monkeypatch):
    monkeypatch.setenv("LOOP_WINDOW_LONG_SHARE", "1")
    m = _loop()
    assert m.long_window_duration(WINDOW, 1.0, rng_value=0.0, span_value=0.0) == 3.0
    assert m.long_window_duration(WINDOW, 1.0, rng_value=0.0, span_value=1.0) == 6.0
    for _ in range(30):
        assert 3.0 <= m.long_window_duration(WINDOW, 1.0) <= 6.0


def test_frame_runs_never_stretched(monkeypatch):
    monkeypatch.setenv("LOOP_WINDOW_LONG_SHARE", "1")
    m = _loop()
    assert m.long_window_duration(FRAME, 1.0, rng_value=0.0) == 1.0


def test_share_is_a_probability(monkeypatch):
    monkeypatch.setenv("LOOP_WINDOW_LONG_SHARE", "0.3")
    m = _loop()
    assert m.long_window_duration(WINDOW, 1.0, rng_value=0.29, span_value=0.5) == 4.5
    assert m.long_window_duration(WINDOW, 1.0, rng_value=0.31, span_value=0.5) == 1.0


def test_api_duration_wins(monkeypatch):
    monkeypatch.setenv("LOOP_WINDOW_LONG_SHARE", "1")
    m = _loop()
    assert m.long_window_duration(WINDOW, 2.0, api_duration=2.0, rng_value=0.0) == 2.0


def test_custom_bounds_and_bad_values(monkeypatch):
    monkeypatch.setenv("LOOP_WINDOW_LONG_SHARE", "1")
    monkeypatch.setenv("LOOP_WINDOW_LONG_MIN", "4")
    monkeypatch.setenv("LOOP_WINDOW_LONG_MAX", "5")
    m = _loop()
    assert m.long_window_duration(WINDOW, 1.0, rng_value=0.0, span_value=0.0) == 4.0
    monkeypatch.setenv("LOOP_WINDOW_LONG_SHARE", "junk")
    assert m.long_window_duration(WINDOW, 1.0, rng_value=0.0) == 1.0