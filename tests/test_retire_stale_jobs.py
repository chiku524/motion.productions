import json
from datetime import datetime, timezone

import pytest

import scripts.retire_stale_jobs as r

NOW = datetime(2026, 11, 1, 12, 30, tzinfo=timezone.utc)


class Fake:
    def __init__(self, changes=1500, bm="bm-1", fail=False):
        self.changes, self.bm, self.fail, self.calls = changes, bm, fail, []

    def bookmark(self):
        self.calls.append("bookmark")
        return self.bm

    def execute(self, sql):
        assert "UPDATE jobs" in sql and "LIMIT 1500" in sql
        self.calls.append("execute")
        if self.fail:
            raise RuntimeError("boom")
        return {"changes": self.changes, "rows_written": self.changes * 3, "rows_read": 10}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("KNOWLEDGE_DIR", str(tmp_path))
    ledger = tmp_path / "ledger.json"
    return tmp_path / "state.json", ledger


def _ledger(p, used):
    p.write_text(json.dumps({"day": "2026-11-01", "containers": {"explorer": {"used": used}}}))


def test_two_batches_then_daily_cap(env):
    sp, ledger = env
    _ledger(ledger, 10_000)
    f = Fake()
    assert r.run_once(f, now=NOW, ledger=ledger, sp=sp) == "batch"
    assert r.run_once(f, now=NOW, ledger=ledger, sp=sp) == "batch"
    assert r.run_once(f, now=NOW, ledger=ledger, sp=sp) == "skipped"
    assert f.calls == ["bookmark", "execute"] * 2  # bookmark before every batch
    st = json.loads(sp.read_text())
    assert st["batches"] == 2 and st["writes"] == 9000


def test_new_utc_day_resets(env):
    sp, ledger = env
    sp.write_text(json.dumps({"day": "2026-10-31", "batches": 2, "writes": 9000, "done": False, "total_rows": 3000}))
    assert r.run_once(Fake(), now=NOW, ledger=ledger, sp=sp) == "batch"


def test_headroom_guard(env):
    sp, ledger = env
    _ledger(ledger, 40_000)  # at 12:30 projects ~77k -> capped 50k; 50k+20k+4.5k = 74.5k ok
    assert r.run_once(Fake(), now=NOW, ledger=ledger, sp=sp) == "batch"
    sp.unlink()
    st_writes = {"day": "2026-11-01", "batches": 1, "writes": 22_000, "done": False}
    sp.write_text(json.dumps(st_writes))
    import os
    os.environ["RETIRE_DAILY_CAP"] = "100000"
    try:
        assert r.run_once(Fake(), now=NOW, ledger=ledger, sp=sp) == "skipped"  # 50k+20k+22k+4.5k > 95k
    finally:
        del os.environ["RETIRE_DAILY_CAP"]


def test_unreadable_ledger_fails_closed(env, monkeypatch):
    sp, ledger = env
    ledger.write_text("{not json")
    monkeypatch.setenv("D1_DAILY_WRITE_BUDGET", "80000")
    assert r.run_once(Fake(), now=NOW, ledger=ledger, sp=sp) == "skipped"


def test_no_bookmark_no_batch(env):
    sp, ledger = env
    f = Fake(bm="")
    assert r.run_once(f, now=NOW, ledger=ledger, sp=sp) == "error"
    assert "execute" not in f.calls


def test_zero_changes_marks_done(env):
    sp, ledger = env
    assert r.run_once(Fake(changes=0), now=NOW, ledger=ledger, sp=sp) == "done"
    f = Fake()
    assert r.run_once(f, now=NOW, ledger=ledger, sp=sp) == "skipped" and f.calls == []


def test_dry_run_writes_nothing(env):
    sp, ledger = env
    f = Fake()
    assert r.run_once(f, now=NOW, ledger=ledger, sp=sp, dry_run=True) == "dry_run" and f.calls == []


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("RETIRE_0103_ENABLED", raising=False)
    assert r.main([]) == 0


def test_next_run():
    assert r.next_run(NOW.replace(hour=12, minute=0), [(0, 30), (12, 30)]) == 1800
    assert r.next_run(NOW, [(0, 30), (12, 30)]) == 12 * 3600
