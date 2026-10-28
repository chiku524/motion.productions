"""Interpret-queue poller: idle back-off >= 120 s with jitter, Retry-After / poll_after_sec, rowid cursor, retries."""
import importlib.util
import sys
from pathlib import Path

import pytest

from src import api_client
from src.interpret_queue_poller import InterpretQueuePoller
from src.poll_backoff import PollBackoff

ROOT = Path(__file__).resolve().parent.parent


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make(answers, **kw):
    clock = Clock()
    paths: list[str] = []

    def fetch(path):
        paths.append(path)
        a = answers[min(len(paths) - 1, len(answers) - 1)]
        if isinstance(a, Exception):
            raise a
        return a

    p = InterpretQueuePoller(
        fetch, limit=20, backoff=PollBackoff(min_seconds=120, max_seconds=600, rng=lambda: 0.0),
        clock=clock, error_types=(api_client.APIError,), **kw,
    )
    return p, clock, paths


def item(rid):
    return {"id": f"i{rid}", "prompt": "p", "source": "web", "rid": rid}


def test_empty_queue_waits_at_least_120s_and_doubles_to_600():
    p, clock, paths = make([{"items": [], "poll_after_sec": 120}])
    waits = []
    for _ in range(6):
        clock.t = max(clock.t, p.next_at)
        assert p.poll() == []
        waits.append(round(p.next_at - clock.t))
    assert waits == [120, 240, 480, 600, 600, 600]


def test_poll_is_gated_between_due_times_and_default_floor_is_enforced():
    clock = Clock()
    paths: list[str] = []
    q = InterpretQueuePoller(
        lambda path: paths.append(path) or {"items": []},
        backoff=PollBackoff(min_seconds=10, max_seconds=20, rng=lambda: 0.0),  # a too-small config is raised to 120 s
        clock=clock,
    )
    assert q.backoff.min_seconds >= 120
    q.poll()
    n = len(paths)
    for _ in range(50):
        clock.t += 2.0  # 100 s of 2 s cycles: no further calls
        assert q.poll() == []
    assert len(paths) == n
    assert q.seconds_until_due() > 0
    clock.t += 25  # 125 s since the first poll
    q.poll()
    assert len(paths) == n + 1


def test_server_hint_is_a_floor_even_above_the_schedule():
    p, clock, _ = make([{"items": [], "poll_after_sec": 300}])
    p.poll()
    assert p.next_at - clock.t == pytest.approx(300.0)


def test_jitter_never_shortens_and_spreads_pollers():
    import random

    waits = set()
    for i in range(20):
        clock = Clock()
        p = InterpretQueuePoller(lambda path: {"items": []}, backoff=PollBackoff(min_seconds=120, rng=random.Random(i).random), clock=clock)
        p.poll()
        waits.add(round(p.next_at - clock.t, 3))
    assert len(waits) > 10 and all(120 <= w <= 150 for w in waits)


def test_new_work_resets_backoff_polls_next_cycle_and_advances_the_cursor():
    p, clock, paths = make([
        {"items": []},
        {"items": [item(5), item(6)], "next_cursor": 6, "poll_after_sec": 0},
        {"items": [], "next_cursor": 6, "poll_after_sec": 120},
    ])
    assert p.poll() == []
    clock.t = p.next_at
    got = p.poll()
    assert [i["rid"] for i in got] == [5, 6]
    assert p.cursor == 6 and p.due()  # immediately due again
    p.poll()
    assert paths[0].endswith("limit=20") and "after" not in paths[0]
    assert paths[2].endswith("limit=20&after=6")
    # empty after a cursor: wrap to 0, idle wait restarts at the minimum
    assert p.cursor == 0 and round(p.next_at - clock.t) == 120


def test_retries_of_already_attempted_rows_are_processed_but_count_as_idle():
    # a prompt that failed to interpret stays pending: after the wrap it is served again, but must not reset the back-off
    p, clock, paths = make([
        {"items": [item(5)], "next_cursor": 5},
        {"items": [], "next_cursor": 5},
        {"items": [item(5)], "next_cursor": 5},
        {"items": [item(5)], "next_cursor": 5},
    ])
    assert len(p.poll()) == 1
    p.poll()  # empty -> wrap, wait 120
    assert p.cursor == 0
    clock.t = p.next_at
    retry = p.poll()
    assert [i["rid"] for i in retry] == [5]
    assert p.next_at - clock.t == pytest.approx(240.0)  # escalated, not reset to ~0


def test_errors_use_retry_after_then_back_off():
    err = api_client.APIError("429", status_code=429, retry_after=500.0)
    p, clock, _ = make([err, RuntimeError("never raised as APIError")])
    assert p.poll() == []
    assert round(p.next_at - clock.t) == 500
    clock.t = p.next_at
    with pytest.raises(RuntimeError):
        p.poll()  # non-API errors are not swallowed


def test_shared_free_tier_cooldown_is_a_floor_for_errors():
    p, clock, _ = make([api_client.APIError("503", status_code=503)], cooldown_remaining=lambda: 700.0)
    p.poll()
    assert p.next_at - clock.t >= 700


def test_old_worker_without_rid_or_cursor_still_works():
    p, clock, paths = make([{"items": [{"id": "a", "prompt": "x"}]}, {"items": [{"id": "a", "prompt": "x"}]}])
    assert len(p.poll()) == 1
    assert p.due()
    assert p.cursor == 0 and "after" not in p.path()


def test_interpret_loop_wires_the_poller_and_defaults_match_compose():
    src = (ROOT / "scripts" / "interpret_loop.py").read_text(encoding="utf-8")
    assert "queue_poller.poll()" in src and "/api/interpret/queue?limit=" not in src
    assert "DEFAULT_DELAY_SECONDS = 90" in src and "CACHE_TTL_SECONDS = 600" in src
    assert 'INTERPRET_DELAY_SECONDS: "90"' in (ROOT / "docker-compose.local.yml").read_text(encoding="utf-8")
    assert 'INTERPRET_DELAY_SECONDS: "90"' in (ROOT / "config" / "workflows.yaml").read_text(encoding="utf-8")