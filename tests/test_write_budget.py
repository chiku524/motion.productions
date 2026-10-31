"""Shared daily D1 write budget: accounting, UTC reset, concurrency on one ledger file, exhaustion, back-off."""
import calendar
import json
import subprocess
import sys
from pathlib import Path

import pytest
import requests

from src import api_client
from src.knowledge import write_budget as wb

REPO = Path(__file__).resolve().parent.parent


def utc(y, mo, d, h=0, mi=0, s=0) -> float:
    return float(calendar.timegm((y, mo, d, h, mi, s)))


class Clock:
    def __init__(self, t: float):
        self.t = t

    def __call__(self) -> float:
        return self.t


def make(tmp_path, name="explorer", budget=70000, clock=None, **kw):
    return wb.WriteBudget(name=name, directory=tmp_path / "ledger", daily_budget=budget, clock=clock or Clock(utc(2026, 10, 27, 12)), **kw)


def test_default_split_matches_weights(tmp_path):
    names = ("interpret", "sound", "explorer", "balanced", "survey", "webjobs")
    allowance = {n: make(tmp_path, n).allowance() for n in names}
    assert allowance == {"interpret": 10500, "sound": 7000, "explorer": 24500, "balanced": 14000, "survey": 3500, "webjobs": 3500}
    assert sum(make(tmp_path, n).allowance() for n in ("interpret", "sound", "explorer", "balanced", "survey", "other")) == 63000  # weights are percents; the 10% not allotted is reserve


def test_weights_over_100_are_normalised(tmp_path):
    b = make(tmp_path, "explorer", weights={"explorer": 150, "balanced": 150, "other": 0})
    assert b.allowance() == 35000


def test_env_budget_and_weights(monkeypatch):
    monkeypatch.setenv("D1_DAILY_WRITE_BUDGET", "1000")
    monkeypatch.setenv("D1_BUDGET_WEIGHTS", "sound=50,explorer=50,other=0")
    b = wb.WriteBudget(name="sound")
    assert b.daily_budget == 1000 and b.allowance() == 500
    monkeypatch.setenv("D1_DAILY_WRITE_BUDGET", "0")
    assert not wb.WriteBudget(name="sound").enabled


def test_reserve_counts_and_exhausts_at_allowance(tmp_path):
    b = make(tmp_path, "sound")  # 7000 rows
    assert b.reserve(6990)
    assert b.used() == 6990 and b.remaining() == 10
    assert not b.reserve(11)
    assert b.reserve(10)
    assert b.remaining() == 0
    snap = b.snapshot()["containers"]["sound"]
    assert snap["used"] == 7000 and snap["denied_posts"] == 1 and snap["denied_rows"] == 11


def test_one_container_cannot_spend_anothers_share(tmp_path):
    clock = Clock(utc(2026, 10, 27, 12))
    sound = make(tmp_path, "sound", clock=clock)
    explorer = make(tmp_path, "explorer", clock=clock)
    assert sound.reserve(7000)
    assert not sound.reserve(1)
    assert explorer.reserve(24500)  # untouched by sound exhausting itself


def test_other_containers_share_one_pool(tmp_path):
    clock = Clock(utc(2026, 10, 27, 12))
    web = make(tmp_path, "webjobs", clock=clock)
    proc = make(tmp_path, "procedural-render", clock=clock)
    assert web.reserve(3000)
    assert proc.reserve(500)
    assert not proc.reserve(1)  # 3,500 pool spent between them


def test_global_cap_never_exceeds_total_budget(tmp_path):
    clock = Clock(utc(2026, 10, 27, 12))
    names = ("explorer", "balanced", "interpret", "sound", "webjobs")
    for n in names:
        b = make(tmp_path, n, clock=clock)
        while b.reserve(500):
            pass
    total = sum(e["used"] for e in make(tmp_path).snapshot()["containers"].values())
    assert total <= 70000


def test_low_priority_is_capped_and_paced_so_discoveries_are_never_starved(tmp_path):
    clock = Clock(utc(2026, 10, 27, 23, 59, 0))  # end of day: pacing no longer limits
    b = make(tmp_path, "explorer", clock=clock)  # allowance 24500, low cap 50% = 12250
    spent = 0
    while b.reserve(100, wb.LOW):
        spent += 100
    assert 12100 <= spent <= 12250
    assert b.reserve(12000, wb.HIGH)  # discoveries still have the other half
    assert not b.reserve(1, wb.LOW)


def test_low_priority_is_paced_across_the_day(tmp_path):
    clock = Clock(utc(2026, 10, 27, 0, 0, 1))
    b = make(tmp_path, "explorer", clock=clock)
    early = 0
    while b.reserve(50, wb.LOW):
        early += 50
    assert early <= 24500 * 0.5 * 0.16  # burst only: ~15% of the low share at 00:00 UTC
    clock.t = utc(2026, 10, 27, 12)
    assert b.reserve(50, wb.LOW)  # more is released as the day goes on


def test_webjobs_posts_are_always_high_priority(tmp_path):
    b = make(tmp_path, "webjobs", clock=Clock(utc(2026, 10, 27, 0, 0, 1)))
    assert b.reserve(3000, wb.LOW)


def test_ledger_resets_at_utc_midnight(tmp_path):
    clock = Clock(utc(2026, 10, 27, 23, 59, 50))
    b = make(tmp_path, "sound", clock=clock)
    assert b.reserve(7000) and not b.reserve(1)
    assert b.seconds_until_reset() == pytest.approx(10, abs=1)
    clock.t = utc(2026, 10, 28, 0, 0, 5)
    assert b.used() == 0 and b.remaining() == 7000
    assert b.reserve(5)
    data = json.loads((tmp_path / "ledger" / "ledger.json").read_text())
    assert data["day"] == "2026-10-28" and data["containers"]["sound"]["used"] == 5


def test_reset_is_utc_not_local_time(tmp_path, monkeypatch):
    # 03:30 UTC on the 28th is still the evening of the 27th in New York; the ledger must already be on the 28th.
    clock = Clock(utc(2026, 10, 28, 3, 30))
    b = make(tmp_path, "sound", clock=clock)
    assert b.reserve(1)
    assert json.loads((tmp_path / "ledger" / "ledger.json").read_text())["day"] == "2026-10-28"


def test_settle_replaces_estimate_with_reported_rows(tmp_path):
    b = make(tmp_path, "sound")
    assert b.reserve(100)
    b.settle(100, 31)
    assert b.used() == 31
    b.settle(100, None)  # settle() without a figure is a no-op (record_response() is the path that handles "unreported")
    assert b.used() == 31
    b.refund(31)
    assert b.used() == 0


def test_backoff_is_shared_and_expires(tmp_path):
    clock = Clock(utc(2026, 10, 27, 12))
    a = make(tmp_path, "sound", clock=clock)
    c = make(tmp_path, "explorer", clock=clock)
    a.start_backoff(900, "x-degraded")
    assert c.backoff_remaining() == pytest.approx(900, abs=1)
    assert not c.can_afford(1)
    clock.t += 901
    assert c.backoff_remaining() == 0 and c.can_afford(1)


def test_backoff_survives_midnight_rollover(tmp_path):
    clock = Clock(utc(2026, 10, 27, 23, 59, 0))
    a = make(tmp_path, "sound", clock=clock)
    a.start_backoff(900)
    clock.t = utc(2026, 10, 28, 0, 1, 0)
    assert a.backoff_remaining() > 0


def test_disabled_budget_never_blocks(tmp_path):
    b = make(tmp_path, "sound", budget=0)
    assert b.reserve(10**9) and b.remaining() > 10**6


def test_ledger_failure_fails_closed(tmp_path):
    b = make(tmp_path, "sound")
    (tmp_path / "ledger").mkdir(parents=True, exist_ok=True)
    (tmp_path / "ledger" / "ledger.lock").write_text("x")  # held lock
    b._lock_path = tmp_path / "ledger" / "ledger.lock"
    orig = wb._FileLock.__init__

    def quick(self, path, timeout=0.1, stale=3600):
        orig(self, path, timeout=0.1, stale=3600)

    wb._FileLock.__init__ = quick
    try:
        assert b.reserve(1) is False
    finally:
        wb._FileLock.__init__ = orig


WORKER = """
import sys, json
sys.path.insert(0, {repo!r})
from src.knowledge import write_budget as wb
b = wb.WriteBudget(name={name!r}, directory={d!r}, daily_budget=70000)
ok = 0
for _ in range({n}):
    if b.reserve({rows}):
        ok += 1
print(json.dumps({{"ok": ok}}))
"""


def test_concurrent_containers_on_one_ledger_file(tmp_path):
    d = str(tmp_path / "shared")
    plan = [("explorer", 40, 200), ("balanced", 40, 200), ("sound", 80, 100), ("interpret", 40, 400)]
    procs = [
        subprocess.Popen([sys.executable, "-c", WORKER.format(repo=str(REPO), name=n, d=d, n=cnt, rows=rows)], stdout=subprocess.PIPE, text=True)
        for n, cnt, rows in plan
    ]
    oks = {}
    for (n, _, rows), p in zip(plan, procs):
        out, _ = p.communicate(timeout=120)
        assert p.returncode == 0
        oks[n] = json.loads(out.strip().splitlines()[-1])["ok"] * rows
    ledger = json.loads((Path(d) / "ledger.json").read_text())["containers"]
    for n, spent in oks.items():
        assert ledger[n]["used"] == spent, "no lost updates under concurrent read-modify-write"
    assert oks["sound"] <= 7000 and oks["interpret"] <= 10500 and oks["explorer"] <= 21000 and oks["balanced"] <= 21000
    assert sum(oks.values()) <= 70000


# ---- cost model ---------------------------------------------------------------------------------------------

def test_cost_model_known_endpoints():
    assert wb.estimate_rows("GET", "/api/jobs/abc") == (0, wb.HIGH)
    assert wb.estimate_rows("POST", "/api/jobs") == (5, wb.LOW)
    assert wb.estimate_rows("POST", "/api/jobs/ab-12/complete") == (2, wb.LOW)
    assert wb.estimate_rows("POST", "/api/learning") == (4, wb.LOW)
    assert wb.estimate_rows("POST", "/api/interpretations") == (4, wb.LOW)
    assert wb.estimate_rows("POST", "/api/loop/state") == (0, wb.LOW)
    assert wb.estimate_rows("POST", "/api/linguistic-registry/batch", {"items": [{}] * 10})[0] == 50


def test_cost_model_discoveries_dedupes_and_prices_by_table():
    body = {"static_colors": [{"key": "a"}, {"key": "a"}, {"key": "b"}], "static_sound": [{"key": "s"}], "motion": [{"key": "m1"}, {"key": "m2"}], "narrative": {"mood": [{"key": "x"}]}, "job_id": "j"}
    rows, prio = wb.estimate_rows("POST", "/api/knowledge/discoveries", body)
    assert prio == wb.HIGH
    ins = wb.INSERT_ROWS
    assert rows == ins['static_colors'] * 2 + ins['static_sound'] + ins['learned_profile'] * 2 + ins['narrative'] + ins['discovery_runs']


# ---- api_client gate ----------------------------------------------------------------------------------------

class FakeResp:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code = status
        self._body = body if body is not None else {}
        self.headers = headers or {}
        self.text = json.dumps(self._body)
        self.content = self.text.encode()
        self.url = "http://x"

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"{self.status_code}", response=self)


@pytest.fixture
def net(monkeypatch):
    calls = []
    state = {"resp": FakeResp(200, {"ok": True})}

    def fake_request(method, url, data=None, headers=None, timeout=None):
        calls.append((method, url))
        return state["resp"]

    monkeypatch.setattr(api_client.requests, "request", fake_request)
    monkeypatch.setattr(api_client.time, "sleep", lambda s: None)
    api_client.reset_free_tier_cooldown()
    yield calls, state
    api_client.reset_free_tier_cooldown()


def test_api_request_stops_posting_when_allowance_is_exhausted(net, monkeypatch):
    calls, state = net
    state["resp"] = FakeResp(200, {"ok": True, "rows_written": 15})  # a reporting Worker: booked at the real 15 rows
    monkeypatch.setenv("D1_BUDGET_NAME", "sound")
    monkeypatch.setenv("D1_DAILY_WRITE_BUDGET", "100")
    monkeypatch.setenv("D1_BUDGET_WEIGHTS", "sound=100")
    wb.reset_budget()
    body = {"static_sound": [{"key": f"k{i}"} for i in range(3)]}  # 15 rows each POST
    sent = 0
    with pytest.raises(api_client.WriteBudgetSkipped) as ei:
        for _ in range(20):
            api_client.api_post("http://api", "/api/knowledge/discoveries", body)
            sent += 1
    assert sent == 6 and len(calls) == 6  # 6 x 15 = 90 of 100, 7th does not fit
    assert "write_budget" in ei.value.body and isinstance(ei.value, api_client.APIError)
    assert api_client.api_get("http://api", "/api/jobs/x") ["ok"] is True  # reads are never gated
    assert len(calls) == 7


def test_api_request_settles_to_reported_rows_written(net, monkeypatch):
    calls, state = net
    monkeypatch.setenv("D1_BUDGET_NAME", "sound")
    monkeypatch.setenv("D1_DAILY_WRITE_BUDGET", "1000")
    wb.reset_budget()
    state["resp"] = FakeResp(201, {"status": "recorded", "rows_written": 2})
    api_client.api_post("http://api", "/api/knowledge/discoveries", {"static_sound": [{"key": "k"}]})
    assert wb.get_budget().used() == 2  # estimate was 5


def test_x_degraded_header_starts_the_shared_900s_backoff(net, monkeypatch):
    calls, state = net
    monkeypatch.setenv("D1_BUDGET_NAME", "explorer")
    wb.reset_budget()
    state["resp"] = FakeResp(503, {"degraded": True, "error": "free_tier_limit"}, {"X-Degraded": "free_tier_limit", "Retry-After": "900"})
    with pytest.raises(api_client.APIError):
        api_client.api_post("http://api", "/api/learning", {"prompt": "p"})
    assert wb.get_budget().backoff_remaining() == pytest.approx(900, abs=5)
    assert wb.get_budget().used() == 0  # degraded answer wrote nothing: refunded
    n = len(calls)
    # another container (fresh process state, same ledger) is held off without touching the network
    api_client._limit_cooldown_until = 0.0
    with pytest.raises(api_client.APIError) as ei:
        api_client.api_post("http://api", "/api/jobs", {"prompt": "p"})
    assert "cooldown" in str(ei.value) and len(calls) == n


def test_200_with_x_degraded_header_also_backs_off(net, monkeypatch):
    calls, state = net
    monkeypatch.setenv("D1_BUDGET_NAME", "explorer")
    wb.reset_budget()
    state["resp"] = FakeResp(200, {"recorded": False}, {"X-Degraded": "d1_db_full", "Retry-After": "900"})
    api_client.api_post("http://api", "/api/learning", {"prompt": "p"})
    assert api_client.free_tier_cooldown_remaining() > 800


def test_d1_quota_error_body_is_not_retried_and_backs_off(net, monkeypatch):
    calls, state = net
    monkeypatch.setenv("D1_BUDGET_NAME", "explorer")
    wb.reset_budget()
    state["resp"] = FakeResp(500, {"error": "D1_ERROR: daily rows written quota exceeded"})
    monkeypatch.setattr(api_client.time, "sleep", lambda s: None)
    with pytest.raises(api_client.APIError):
        api_client.api_request("http://api", "POST", "/api/learning", data={"prompt": "p"}, max_retries=3)
    assert len(calls) == 1
    assert api_client.free_tier_cooldown_remaining() > 800


def test_gate_off_when_budget_zero(net, monkeypatch):
    calls, _ = net
    monkeypatch.setenv("D1_DAILY_WRITE_BUDGET", "0")
    wb.reset_budget()
    for _ in range(50):
        api_client.api_post("http://api", "/api/jobs", {"prompt": "p"})
    assert len(calls) == 50





def test_colour_survey_posts_are_charged_to_the_survey_bucket(tmp_path):
    clock = Clock(utc(2026, 10, 27, 12))
    explorer = make(tmp_path, "explorer", clock=clock)
    survey = wb.budget_for_path("/api/coverage/color/chunks", explorer)
    assert survey.name == "survey" and survey.allowance() == 3500
    assert wb.budget_for_path("/api/knowledge/discoveries", explorer) is explorer
    assert survey.reserve(3500) and not survey.reserve(1)  # fail-closed on its own share
    assert explorer.reserve(100)  # explorer's discoveries unaffected
    snap = make(tmp_path).snapshot()["containers"]
    assert snap["survey"]["used"] == 3500 and snap["explorer"]["used"] == 100


def test_survey_bucket_absent_from_weights_falls_back_to_container(tmp_path):
    b = make(tmp_path, "explorer", weights={"explorer": 50, "other": 10})
    assert wb.budget_for_path("/api/coverage/color/chunks", b) is b


def test_default_weights_keep_the_same_total():
    assert sum(wb.DEFAULT_WEIGHTS.values()) == 90
    assert wb.DEFAULT_WEIGHTS["explorer"] > wb.DEFAULT_WEIGHTS["balanced"]
