"""Ledger calibration: the client's row-cost model must match what D1 really charges (index writes included),
a Worker that stops reporting ``rows_written`` must fail the ledger closed, and no write path may skip the ledger."""
import glob
import sqlite3
from pathlib import Path

import pytest

from src import api_client
from src.knowledge import write_budget as wb
from tests.test_write_budget import FakeResp

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def net(monkeypatch):
    calls, state = [], {"resp": FakeResp(200, {"ok": True})}

    def fake_request(method, url, data=None, headers=None, timeout=None):
        calls.append((method, url))
        return state["resp"]

    monkeypatch.setattr(api_client.requests, "request", fake_request)
    monkeypatch.setattr(api_client.time, "sleep", lambda s: None)
    api_client.reset_free_tier_cooldown()
    yield calls, state
    api_client.reset_free_tier_cooldown()


@pytest.fixture(scope="module")
def index_counts():
    db = sqlite3.connect(":memory:")
    for f in sorted(glob.glob(str(ROOT / "cloudflare" / "migrations" / "*.sql"))):
        db.executescript(Path(f).read_text(encoding="utf-8"))
    tables = [r[0] for r in db.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'")]
    return {t: len(db.execute(f"pragma index_list('{t}')").fetchall()) for t in tables}


def test_default_budget_is_50000_real_rows(monkeypatch):
    monkeypatch.delenv("D1_DAILY_WRITE_BUDGET", raising=False)
    assert wb.DEFAULT_DAILY_BUDGET == 50000
    assert wb.daily_budget_from_env() == 50000
    compose = (ROOT / "docker-compose.local.yml").read_text(encoding="utf-8", errors="replace")
    assert "D1_DAILY_WRITE_BUDGET: ${D1_DAILY_WRITE_BUDGET:-50000}" in compose
    assert "70000" not in compose


@pytest.mark.parametrize("key,table,extra_max", [
    ("jobs", "jobs", 0), ("learning_runs", "learning_runs", 0), ("interpretations", "interpretations", 0),
    ("linguistic_registry", "linguistic_registry", 0), ("static_sound", "static_sound", 0),
    ("learned_profile", "learned_motion", 0), ("narrative", "narrative_entries", 0), ("discovery_runs", "discovery_runs", 0),
    ("events", "events", 0),
    # these also reserve display names in name_reserve (2 rows each), so the estimate is an upper bound
    ("static_colors", "static_colors", 3), ("learned_colors", "learned_colors", 3), ("learned_blends", "learned_blends", 6),
])
def test_insert_costs_are_derived_from_the_migrations(index_counts, key, table, extra_max):
    real = 1 + index_counts[table]  # row + every index entry (PK / UNIQUE autoindexes included)
    est = wb.INSERT_ROWS[key]
    assert est >= real, f"{key}: estimate {est} under-counts D1's {real}"
    assert est <= real + extra_max, f"{key}: estimate {est} is more than {extra_max} above D1's {real}"


def test_coverage_chunk_estimate_covers_a_single_row_per_chunk(index_counts):
    assert wb.INSERT_ROWS["color_coverage"] >= 1 + index_counts["color_coverage_chunks"]


def test_measured_costs_from_the_worker_harness():
    # Measured with cloudflare/test/writeBudget.test.mjs's miniflare D1 (meta.rows_written). Never below real, within 20% over.
    measured = {
        ("POST", "/api/jobs", None): 5, ("POST", "/api/jobs/ab-12/complete", None): 2, ("POST", "/api/learning", None): 4,
        ("POST", "/api/events", None): 5, ("POST", "/api/interpret/queue", None): 4, ("PATCH", "/api/interpret/ab12-cd", None): 3,
        ("POST", "/api/interpretations", None): 4,
    }
    for (m, p, d), real in measured.items():
        est, _ = wb.estimate_rows(m, p, d)
        assert real <= est <= real * 1.2, (m, p, est, real)


def test_interpret_container_paths_are_priced_not_defaulted():
    assert wb.estimate_rows("PATCH", "/api/interpret/ab12-cd")[0] == wb.UPDATE_ROWS["interpretation_patch"]
    assert wb.estimate_rows("POST", "/api/interpret/queue")[0] == wb.INSERT_ROWS["interpret_queue"]
    assert wb.estimate_rows("POST", "/api/some/new/route")[0] == wb.UNKNOWN_WRITE_ROWS >= 5


def test_unreported_answer_costs_estimate_plus_surcharge_and_reported_one_costs_the_real_rows(tmp_path):
    b = wb.WriteBudget(name="sound", directory=tmp_path, daily_budget=10000)
    assert b.reserve(40)
    b.record_response(40, None)
    assert b.used() == 40 + 10  # +25%
    assert b.reserve(40)
    b.record_response(40, 12)
    assert b.used() == 50 + 12
    t = b.trust()
    assert (t["reported_posts"], t["unreported_posts"], t["surcharge_rows"]) == (1, 1, 10)
    assert t["estimate_over_actual"] == round(40 / 12, 3) and t["trusted"]


def test_ledger_fails_closed_when_the_worker_stops_reporting_rows(tmp_path):
    now = [1_800_000_000.0]
    b = wb.WriteBudget(name="explorer", directory=tmp_path, daily_budget=100000, clock=lambda: now[0])
    for _ in range(wb.UNREPORTED_TRIP):
        assert b.reserve(10)
        b.record_response(10, None)
    assert not b.trust()["trusted"]
    assert b.reserve(10)  # exactly one probe is let through ...
    assert not b.reserve(10)  # ... then everything is refused
    assert not b.reserve(10, wb.HIGH)
    now[0] += wb.PROBE_SECONDS + 1
    assert b.reserve(10)  # next probe window
    b.record_response(10, 7)  # the Worker reports again -> trusted again
    assert b.trust()["trusted"] and b.reserve(10) and b.reserve(10)


def test_untrusted_state_survives_the_utc_day_rollover(tmp_path):
    now = [1_800_000_000.0]
    b = wb.WriteBudget(name="explorer", directory=tmp_path, daily_budget=100000, clock=lambda: now[0])
    for _ in range(wb.UNREPORTED_TRIP):
        b.reserve(10)
        b.record_response(10, None)
    now[0] += 86400
    b.reserve(1)  # the probe
    assert not b.reserve(10)


def test_api_request_books_real_rows_and_counts_unreported_posts(net, monkeypatch):
    calls, state = net
    monkeypatch.setenv("D1_BUDGET_NAME", "interpret")
    monkeypatch.setenv("D1_DAILY_WRITE_BUDGET", "1000")
    wb.reset_budget()
    state["resp"] = FakeResp(200, {"id": "x", "status": "done", "rows_written": 3})
    api_client.api_request("http://api", "PATCH", "/api/interpret/ab12-cd", data={"instruction": {}})
    assert wb.get_budget().used() == 3
    state["resp"] = FakeResp(200, {"id": "x"})  # old Worker
    api_client.api_request("http://api", "PATCH", "/api/interpret/ab12-cd", data={"instruction": {}})
    assert wb.get_budget().used() == 3 + 3 + 1  # estimate 3 + ceil(25%)
    assert wb.get_budget().trust()["unreported_posts"] == 1


def test_api_request_stops_when_ten_answers_in_a_row_carry_no_rows_written(net, monkeypatch):
    calls, state = net
    monkeypatch.setenv("D1_BUDGET_NAME", "interpret")
    monkeypatch.setenv("D1_DAILY_WRITE_BUDGET", "100000")
    wb.reset_budget()
    state["resp"] = FakeResp(200, {"id": "x"})
    sent = 0
    with pytest.raises(api_client.WriteBudgetSkipped):
        for _ in range(50):
            api_client.api_request("http://api", "POST", "/api/learning", data={"prompt": "p"})
            sent += 1
    assert sent == wb.UNREPORTED_TRIP + 1  # trips after 10 unreported answers; one probe is let through, then refusal
    assert len(calls) == sent


def test_retry_after_a_5xx_is_charged_again(monkeypatch):
    monkeypatch.setenv("D1_BUDGET_NAME", "sound")
    monkeypatch.setenv("D1_DAILY_WRITE_BUDGET", "1000")
    wb.reset_budget()
    monkeypatch.setattr(api_client.time, "sleep", lambda s: None)
    answers = [FakeResp(500, {"error": "boom"}), FakeResp(201, {"rows_written": 4})]
    monkeypatch.setattr(api_client.requests, "request", lambda *a, **k: answers.pop(0))
    api_client.api_request("http://api", "POST", "/api/learning", data={"prompt": "p"}, max_retries=2)
    # attempt 1 may have written (estimate 4 stays charged) + attempt 2 settled to the real 4
    assert wb.get_budget().used() == 4 + 4


def test_retry_after_a_429_refusal_is_not_double_charged(monkeypatch):
    monkeypatch.setenv("D1_BUDGET_NAME", "sound")
    monkeypatch.setenv("D1_DAILY_WRITE_BUDGET", "1000")
    wb.reset_budget()
    monkeypatch.setattr(api_client.time, "sleep", lambda s: None)
    answers = [FakeResp(429, {"retry_after_ms": 10}), FakeResp(201, {"rows_written": 4})]
    monkeypatch.setattr(api_client.requests, "request", lambda *a, **k: answers.pop(0))
    api_client.api_request("http://api", "POST", "/api/learning", data={"prompt": "p"}, max_retries=2)
    assert wb.get_budget().used() == 4


def test_a_retry_that_no_longer_fits_the_budget_is_skipped(monkeypatch):
    monkeypatch.setenv("D1_BUDGET_NAME", "sound")
    monkeypatch.setenv("D1_DAILY_WRITE_BUDGET", "100")
    monkeypatch.setenv("D1_BUDGET_WEIGHTS", "sound=100")
    wb.reset_budget()
    assert wb.get_budget().reserve(88)
    monkeypatch.setattr(api_client.time, "sleep", lambda s: None)
    answers = [FakeResp(500, {"error": "boom"}), FakeResp(201, {"rows_written": 4})]
    calls = []
    monkeypatch.setattr(api_client.requests, "request", lambda *a, **k: calls.append(1) or answers.pop(0))
    with pytest.raises(api_client.WriteBudgetSkipped):
        api_client.api_request("http://api", "POST", "/api/knowledge/discoveries", data={"static_sound": [{"key": "k"}]}, max_retries=2)
    assert len(calls) == 1


def test_api_post_binary_settles_instead_of_keeping_the_worst_case(monkeypatch):
    monkeypatch.setenv("D1_BUDGET_NAME", "webjobs")
    monkeypatch.setenv("D1_DAILY_WRITE_BUDGET", "1000")
    wb.reset_budget()
    monkeypatch.setattr(api_client.requests, "post", lambda *a, **k: FakeResp(201, {"rows_written": 2}))
    api_client.api_post_binary("http://api", "/api/jobs/ab-12/upload", b"x")
    assert wb.get_budget().used() == 2  # estimate was 3
