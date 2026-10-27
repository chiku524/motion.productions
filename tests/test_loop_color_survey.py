"""automate_loop integration of the exact-colour survey (opt-in LOOP_COLOR_SURVEY) and its compose wiring."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def loop():
    spec = importlib.util.spec_from_file_location("automate_loop_survey_test", ROOT / "scripts" / "automate_loop.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_disabled_by_default_does_nothing(loop, monkeypatch):
    monkeypatch.delenv("LOOP_COLOR_SURVEY", raising=False)
    called = []
    monkeypatch.setattr("src.knowledge.color_survey.run_survey_iteration", lambda *a, **k: called.append(1))
    assert loop.run_color_survey_step("http://x") is None
    assert not called


def test_enabled_runs_one_survey_burst(loop, monkeypatch):
    monkeypatch.setenv("LOOP_COLOR_SURVEY", "1")
    monkeypatch.setattr(
        "src.knowledge.color_survey.run_survey_iteration",
        lambda api_base, **k: {"clips": 2, "targets": 100, "verified": 100, "covered": 100, "pct_covered": 0.1},
    )
    out = loop.run_color_survey_step("http://x")
    assert out["clips"] == 2


def test_survey_failure_never_breaks_the_loop(loop, monkeypatch):
    monkeypatch.setenv("LOOP_COLOR_SURVEY", "1")

    def boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr("src.knowledge.color_survey.run_survey_iteration", boom)
    assert loop.run_color_survey_step("http://x") is None


def test_loop_calls_survey_step_before_creative_work():
    src = (ROOT / "scripts" / "automate_loop.py").read_text(encoding="utf-8", errors="replace")
    assert src.index("run_color_survey_step(args.api_base)") < src.index("pick_prompt(state, knowledge=knowledge")


def test_compose_enables_survey_for_explorer_and_balanced_only():
    yaml = pytest.importorskip("yaml")
    services = yaml.safe_load((ROOT / "docker-compose.local.yml").read_text(encoding="utf-8", errors="replace"))["services"]
    on = {n for n, s in services.items() if "LOOP_COLOR_SURVEY" in (s.get("environment") or {})}
    assert on == {"explorer", "balanced"}
    idx = {n: services[n]["environment"]["CONTAINER_INDEX"] for n in on}
    assert sorted(idx.values()) == ["0", "1"]  # disjoint strides
    assert all(services[n]["environment"]["COLOR_SYNC"].endswith(":-0}") for n in on)  # D1 sync off until 0101 applied