"""Write pacing: loops sleep while their container is ahead of allowance x (fraction of the UTC day + slack)."""
import calendar
import importlib.util
import json
from pathlib import Path

import pytest

from src.knowledge import write_budget as wb

REPO = Path(__file__).resolve().parent.parent
DAY = 86400.0


def utc(y, mo, d, h=0, mi=0, s=0) -> float:
    return float(calendar.timegm((y, mo, d, h, mi, s)))


class Clock:
    def __init__(self, t: float):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.t += s


# Pacing maths is independent of the split; pin the even 30/30 split these numbers were written against.
EVEN = {"explorer": 30, "balanced": 30, "interpret": 15, "sound": 10, "other": 5}


def setup(tmp_path, name="explorer", budget=50000, at=utc(2026, 10, 27, 12), **kw):
    kw.setdefault("weights", EVEN)
    clock = Clock(at)
    b = wb.WriteBudget(name=name, directory=tmp_path / "ledger", daily_budget=budget, clock=clock, **kw)
    pacer = wb.WritePacer(budget=b, slack=0.03, chunk_s=30.0, enabled=True)
    return clock, b, pacer


# --- pure maths ----------------------------------------------------------------------------------------------
def test_pace_wait_seconds_under_and_over_pace():
    allowance = 15000.0
    # noon: pace line = 15000 * (0.5 + 0.03) = 7950
    assert wb.pace_wait_seconds(allowance, 7950, 43200, 0.03) == 0.0
    assert wb.pace_wait_seconds(allowance, 0, 43200, 0.03) == 0.0
    w = wb.pace_wait_seconds(allowance, 9000, 43200, 0.03)
    assert w == pytest.approx((9000 / allowance - 0.03) * DAY - 43200)
    # waiting exactly that long lands on the line
    assert wb.pace_wait_seconds(allowance, 9000, 43200 + w, 0.03) == pytest.approx(0.0, abs=1e-6)


def test_pace_wait_seconds_zero_or_spent_allowance_waits_for_reset():
    assert wb.pace_wait_seconds(0, 0, 3600, 0.03) == DAY - 3600
    assert wb.pace_wait_seconds(15000, 15000, 3600, 0.03) == DAY - 3600
    assert wb.pace_wait_seconds(15000, 100, 3600, 0.03, total_used=50000, daily_budget=50000) == DAY - 3600


def test_pace_wait_never_exceeds_the_reset():
    assert wb.pace_wait_seconds(1000, 999, 80000, 0.0) <= DAY - 80000


def test_restart_anchor_blocks_catch_up_burst():
    # process starts at 20:00 UTC with 0 rows used: the plain clock line would allow 83% of the allowance at once
    assert wb.pace_wait_seconds(15000, 5000, 72000, 0.03) == 0.0
    w = wb.pace_wait_seconds(15000, 5000, 72000, 0.03, anchor_sod=72000, anchor_used=0)
    assert w == DAY - 72000  # capped at the UTC reset
    w = wb.pace_wait_seconds(15000, 1500, 72000, 0.03, anchor_sod=72000, anchor_used=0)
    assert w == pytest.approx((1500 / 15000 - 0.03) * DAY)


def test_env_knobs(monkeypatch):
    monkeypatch.delenv("WRITE_PACING", raising=False)
    assert wb.pacing_enabled() is True
    for off in ("0", "off", "false", "No"):
        monkeypatch.setenv("WRITE_PACING", off)
        assert wb.pacing_enabled() is False
    monkeypatch.setenv("WRITE_PACING", "1")
    assert wb.pacing_enabled() is True
    monkeypatch.setenv("WRITE_PACING_SLACK", "0.1")
    assert wb.pacing_slack_from_env() == 0.1
    monkeypatch.setenv("WRITE_PACING_SLACK", "nonsense")
    assert wb.pacing_slack_from_env() == wb.DEFAULT_PACING_SLACK


# --- the pacer against a real ledger file --------------------------------------------------------------------
def test_on_pace_does_not_sleep(tmp_path):
    clock, b, pacer = setup(tmp_path)
    assert b.allowance() == 15000
    assert b.reserve(7000, "high")
    assert pacer.wait_for_pace(sleep=clock.sleep) == 0.0
    assert clock.t == utc(2026, 10, 27, 12)


def test_over_pace_sleeps_in_chunks_until_the_clock_catches_up(tmp_path):
    clock, b, pacer = setup(tmp_path)
    assert b.reserve(9000, "high")
    sleeps = []
    slept = pacer.wait_for_pace(sleep=lambda s: (sleeps.append(s), clock.sleep(s)))
    expected = (9000 / 15000 - 0.03) * DAY - 12 * 3600
    assert expected <= slept < expected + 30.0
    assert max(sleeps) <= 30.0 and len(sleeps) > 100  # short, interruptible chunks
    assert pacer.status()["wait_seconds"] == 0.0
    assert b.snapshot()["containers"]["explorer"]["paced_s"] == pytest.approx(slept)  # visible to loop_metrics


def test_wait_is_interruptible_by_shutdown(tmp_path):
    clock, b, pacer = setup(tmp_path)
    assert b.reserve(9000, "high")
    calls = {"n": 0}

    def stop():
        calls["n"] += 1
        return calls["n"] > 3

    slept = pacer.wait_for_pace(should_stop=stop, sleep=clock.sleep)
    assert slept == 90.0  # three chunks, then the stop request ends the wait
    assert pacer.wait_for_pace(should_stop=lambda: True, sleep=clock.sleep) == 0.0


def test_other_containers_progress_is_not_counted_against_this_one(tmp_path):
    clock, b, pacer = setup(tmp_path)
    other = wb.WriteBudget(name="balanced", directory=tmp_path / "ledger", daily_budget=50000, clock=clock, weights=EVEN)
    assert other.reserve(14000, "high")
    assert pacer.wait_for_pace(sleep=clock.sleep) == 0.0  # explorer has used nothing


def test_utc_midnight_rollover_resets_the_wait(tmp_path):
    clock, b, pacer = setup(tmp_path, at=utc(2026, 10, 27, 23, 59, 0))
    assert b.reserve(15000, "high")  # whole allowance spent late in the day
    slept = pacer.wait_for_pace(sleep=clock.sleep)
    assert 60.0 <= slept < 120.0  # woke at 00:00 UTC, when the ledger reset, not at the pace line
    assert clock.t >= utc(2026, 10, 28)
    assert pacer.status()["used"] == 0 and pacer.status()["wait_seconds"] == 0.0


def test_hard_allowance_still_blocks_posts_without_pacing(tmp_path):
    clock, b, pacer = setup(tmp_path)
    assert b.reserve(14990, "high")
    assert not b.reserve(100, "high")  # pacing is on top of the allowance, never instead of it
    pacer.enabled = False
    assert pacer.wait_for_pace(sleep=clock.sleep) == 0.0
    assert not b.reserve(100, "high")


def test_zero_allowance_waits_for_reset_but_can_be_interrupted(tmp_path):
    clock, b, pacer = setup(tmp_path, weights={"explorer": 0, "other": 5})
    assert b.allowance() == 0
    assert pacer.status()["wait_seconds"] == pytest.approx(DAY - 12 * 3600)
    n = {"i": 0}

    def stop():
        n["i"] += 1
        return n["i"] > 2

    assert pacer.wait_for_pace(should_stop=stop, sleep=clock.sleep) == 60.0
    assert not b.reserve(1, "high")  # nothing may be posted either


def test_global_budget_spent_waits_for_reset(tmp_path):
    clock, b, pacer = setup(tmp_path, budget=1000)
    assert b.reserve(300, "high")
    # another container used the rest of the global budget
    other = wb.WriteBudget(name="sound", directory=tmp_path / "ledger", daily_budget=1000, clock=clock)
    other._mutate(lambda data, now: other._entry(data).__setitem__("used", 700))
    assert pacer.status()["wait_seconds"] == pytest.approx(DAY - 12 * 3600)


def test_no_ledger_file_means_no_wait(tmp_path):
    clock, b, pacer = setup(tmp_path, at=utc(2026, 10, 27, 0, 0, 5))
    assert not b.path.exists()
    assert pacer.wait_for_pace(sleep=clock.sleep) == 0.0
    assert clock.t == utc(2026, 10, 27, 0, 0, 5)


def test_unreadable_ledger_does_not_pace_but_posts_still_fail_closed(tmp_path, monkeypatch):
    clock, b, pacer = setup(tmp_path)
    monkeypatch.setattr(b, "_read", lambda now: (_ for _ in ()).throw(OSError("disk")))
    assert pacer.wait_for_pace(sleep=clock.sleep) == 0.0
    assert b.reserve(10, "high") is False  # reserve cannot read the ledger: hold the write


def test_gate_disabled_or_pacing_off_never_sleeps(tmp_path):
    clock, b, pacer = setup(tmp_path, budget=0)
    assert pacer.wait_for_pace(sleep=clock.sleep) == 0.0
    clock, b, pacer = setup(tmp_path / "x")
    assert b.reserve(9000, "high")
    pacer.enabled = False
    assert pacer.wait_for_pace(sleep=clock.sleep) == 0.0


def test_restarted_process_does_not_burst_into_the_clock_time_it_missed(tmp_path):
    clock, b, pacer = setup(tmp_path, at=utc(2026, 10, 27, 20))  # restart at 20:00 UTC, nothing used yet today
    assert pacer.wait_for_pace(sleep=clock.sleep) == 0.0  # anchors here
    assert b.reserve(450, "high")  # the burst slack (3% of 15000)
    assert pacer.wait_for_pace(sleep=clock.sleep) == 0.0
    assert b.reserve(2000, "high")
    slept = pacer.wait_for_pace(sleep=clock.sleep)
    assert slept >= (2450 / 15000 - 0.03) * DAY - 1  # rate-limited from the restart, not allowed up to the 83% clock line


def test_module_hook_never_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("D1_DAILY_WRITE_BUDGET", "50000")
    wb.reset_budget()
    wb.reset_pacer()
    monkeypatch.setenv("WRITE_PACING", "0")
    wb.reset_pacer()
    assert wb.wait_for_pace() == 0.0
    wb.reset_pacer()


# --- metrics --------------------------------------------------------------------------------------------------
def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, REPO / path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_loop_metrics_reports_pace_status(tmp_path):
    mod = _load("scripts/loop_metrics.py", "loop_metrics_pace")
    now = utc(2026, 10, 27, 12)
    ledger = tmp_path / "ledger"
    ahead = wb.WriteBudget(name="explorer", directory=ledger, daily_budget=50000, clock=lambda: now)
    ok = wb.WriteBudget(name="sound", directory=ledger, daily_budget=50000, clock=lambda: now)
    assert ahead.reserve(10000, "high") and ok.reserve(1000, "high")  # explorer allowance 17,500 (35%)
    rep = mod.budget_report(ledger, now=now)
    assert rep["containers"]["explorer"]["pace_state"] == "ahead"
    assert rep["containers"]["explorer"]["pace_limit"] == pytest.approx(17500 * 0.53)
    assert rep["containers"]["sound"]["pace_state"] == "on pace"
    text = mod.render_budget(rep)
    assert "pace line" in text and "ahead" in text and "Pacing ON" in text
    json.dumps(rep)  # --json output stays serialisable