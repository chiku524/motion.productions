"""LOOP_JOB_LOG_EVERY: per-clip job/complete/learning log rows only for every Nth loop clip."""
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


def _fn():
    return importlib.import_module("automate_loop").should_log_loop_job


def test_default_logs_every_clip(monkeypatch):
    monkeypatch.delenv("LOOP_JOB_LOG_EVERY", raising=False)
    assert all(_fn()(i) for i in range(7))


def test_every_nth(monkeypatch):
    monkeypatch.setenv("LOOP_JOB_LOG_EVERY", "5")
    assert [i for i in range(12) if _fn()(i)] == [0, 5, 10]


def test_zero_disables_and_garbage_falls_back(monkeypatch):
    monkeypatch.setenv("LOOP_JOB_LOG_EVERY", "0")
    assert not _fn()(0)
    monkeypatch.setenv("LOOP_JOB_LOG_EVERY", "x")
    assert _fn()(3)
