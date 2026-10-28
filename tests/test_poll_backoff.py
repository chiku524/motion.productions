"""Idle-poll back-off for the webjobs bridge (docs/D1_FREE_TIER.md, "jobs claim")."""
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from src import api_client
from src.poll_backoff import PollBackoff, queue_hint

ROOT = Path(__file__).resolve().parent.parent


def _fixed(v):
    return lambda: v


def test_default_idle_poll_is_at_least_60s_and_jitter_never_shortens_it():
    b = PollBackoff(rng=_fixed(0.0))
    assert b.min_seconds >= 60
    assert b.next_delay() == pytest.approx(60.0)
    b2 = PollBackoff(rng=_fixed(0.999))
    assert 60.0 <= b2.next_delay() <= 60.0 * 1.25


def test_exponential_growth_is_capped_and_reset_by_work():
    b = PollBackoff(min_seconds=60, max_seconds=600, rng=_fixed(0.0))
    assert [round(b.next_delay()) for _ in range(6)] == [60, 120, 240, 480, 600, 600]
    b.reset()
    assert round(b.next_delay()) == 60


def test_jitter_spreads_delays_between_pollers():
    import random

    delays = {round(PollBackoff(min_seconds=60, rng=random.Random(i).random).next_delay(), 3) for i in range(20)}
    assert len(delays) > 10
    assert all(60 <= d <= 75 for d in delays)


def test_server_hint_is_a_floor_and_a_large_hint_is_honoured():
    b = PollBackoff(min_seconds=60, max_seconds=600, rng=_fixed(0.0))
    assert b.next_delay(hint=300) == 300  # degraded Worker asked for 5 min
    assert b.next_delay(hint=10) == pytest.approx(120)  # a small hint never shortens the schedule
    assert b.next_delay(hint=1800) == 1800  # above max_seconds: the server knows best


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("POLL_IDLE_MIN_SECONDS", "90")
    monkeypatch.setenv("POLL_IDLE_MAX_SECONDS", "200")
    b = PollBackoff(rng=_fixed(0.0))
    assert [round(b.next_delay()) for _ in range(3)] == [90, 180, 200]


def test_queue_hint_reads_body_and_retry_after_header():
    assert queue_hint({"jobs": [], "poll_after_sec": 60}) == 60
    assert queue_hint({"poll_after_sec": 0}) is None
    assert queue_hint({}, {"Retry-After": "120"}) == 120
    assert queue_hint({"poll_after_sec": 60}, {"retry-after": "300"}) == 300
    assert queue_hint(None) is None


def test_error_delay_honours_retry_after_and_shared_cooldown():
    b = PollBackoff(min_seconds=60, rng=_fixed(0.0))
    exc = SimpleNamespace(retry_after=240.0)
    assert b.error_delay(exc) == 240.0
    assert b.error_delay(None, cooldown_remaining=900.0) == 900.0
    assert b.error_delay(ValueError("boom")) >= 60  # no hint: still the escalating schedule


class _Resp:
    def __init__(self, status, headers=None, text="{}"):
        self.status_code = status
        self.headers = headers or {}
        self.text = text
        self.content = text.encode()

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"{self.status_code}", response=self)

    def json(self):
        import json as _json

        return _json.loads(self.text)


def test_api_error_carries_retry_after_from_a_429(monkeypatch):
    monkeypatch.setattr(api_client.requests, "request", lambda *a, **k: _Resp(429, {"Retry-After": "75"}, '{"error":"rate limited"}'))
    monkeypatch.setattr(api_client.time, "sleep", lambda s: None)
    with pytest.raises(api_client.APIError) as ei:
        api_client.api_request("http://x", "GET", "/api/jobs?status=pending", max_retries=0)
    assert ei.value.status_code == 429
    assert ei.value.retry_after == 75.0


def test_api_error_retry_after_is_none_without_a_hint(monkeypatch):
    monkeypatch.setattr(api_client.requests, "request", lambda *a, **k: _Resp(404, {}, '{"error":"nope"}'))
    with pytest.raises(api_client.APIError) as ei:
        api_client.api_request("http://x", "GET", "/api/jobs/zz", max_retries=0)
    assert ei.value.retry_after is None


def _load_bridge():
    spec = importlib.util.spec_from_file_location("generate_bridge_under_test", ROOT / "scripts" / "generate_bridge.py")
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(ROOT))
    spec.loader.exec_module(mod)
    return mod


def _run_bridge(monkeypatch, answers, max_polls, argv=None):
    """Drive generate_bridge.main() through `answers` (each a (jobs, hint) tuple or an Exception); return the sleeps."""
    gb = _load_bridge()
    import src.workflow_utils as wu

    polls = {"n": 0}
    sleeps: list[float] = []
    processed: list[str] = []

    def fake_fetch(api_base):
        i = polls["n"]
        polls["n"] += 1
        a = answers[min(i, len(answers) - 1)]
        if isinstance(a, Exception):
            raise a
        return a

    monkeypatch.setattr(gb, "fetch_pending_queue", fake_fetch)
    monkeypatch.setattr(gb, "process_job", lambda job, *a, **k: processed.append(job["id"]))
    monkeypatch.setattr(gb, "load_config", lambda p=None: {})
    monkeypatch.setattr(gb.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(wu, "setup_graceful_shutdown", lambda: None)
    monkeypatch.setattr(wu, "request_shutdown", lambda: polls["n"] >= max_polls)
    monkeypatch.setattr(gb, "PollBackoff", lambda **kw: PollBackoff(rng=_fixed(0.0), **kw))
    monkeypatch.setattr(sys, "argv", ["generate_bridge.py"] + (argv or []))
    gb.main()
    return sleeps, processed


def test_bridge_backs_off_exponentially_while_the_queue_is_empty(monkeypatch):
    monkeypatch.delenv("BRIDGE_INTERVAL_SECONDS", raising=False)
    sleeps, _ = _run_bridge(monkeypatch, [([], 60.0)], max_polls=5)
    assert [round(s) for s in sleeps] == [60, 120, 240, 480, 600]


def test_bridge_honours_the_workers_degraded_hint_then_resets_on_work(monkeypatch):
    monkeypatch.delenv("BRIDGE_INTERVAL_SECONDS", raising=False)
    answers = [([], 300.0), ([], 60.0), ([{"id": "abc1"}], None), ([], 60.0)]
    sleeps, processed = _run_bridge(monkeypatch, answers, max_polls=4)
    assert processed == ["abc1"]
    # 300 (degraded hint) | 120 (schedule beats the 60 s hint) | 1 (after a job) | 60 (reset to the minimum)
    assert [round(s) for s in sleeps] == [300, 120, 1, 60]


def test_bridge_errors_back_off_and_use_retry_after(monkeypatch):
    monkeypatch.delenv("BRIDGE_INTERVAL_SECONDS", raising=False)
    err = api_client.APIError("429", status_code=429, retry_after=500.0)
    sleeps, _ = _run_bridge(monkeypatch, [err, RuntimeError("boom")], max_polls=2)
    assert round(sleeps[0]) == 500
    assert round(sleeps[1]) == 120


def test_bridge_default_interval_is_60s_and_compose_matches():
    src = (ROOT / "scripts" / "generate_bridge.py").read_text(encoding="utf-8")
    assert 'get("BRIDGE_INTERVAL_SECONDS", "60")' in src
    compose = (ROOT / "docker-compose.local.yml").read_text(encoding="utf-8")
    assert 'BRIDGE_INTERVAL_SECONDS: "60"' in compose
