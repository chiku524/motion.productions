"""Colour sync: budget, change detection, backoff, multi-container safety. All against a fake Worker."""
from __future__ import annotations

import base64
import zlib

import numpy as np
import pytest

from src.knowledge import color_sync as cs
from src.knowledge.color_cells import CHUNK_BYTES, ColorCellStore, rgb_to_id


class FakeWorker:
    """Mirrors the Worker contract: OR-merge per chunk, report changed rows."""

    def __init__(self):
        self.rows: dict[int, dict[str, bytes]] = {}
        self.requests: list[dict] = []
        self.mode = "ok"

    def __call__(self, api_base, path, data=None, **kw):
        assert path == cs.PUSH_PATH
        self.requests.append(data)
        if self.mode == "table_missing":
            return {"available": False, "reason": "table_missing", "recorded": False}
        if self.mode == "degraded":
            return {"degraded": True, "recorded": False, "error": "d1_db_full"}
        if self.mode == "409":
            raise _Err(409, '{"error":"version_mismatch"}')
        if self.mode == "boom":
            raise _Err(503, "")
        assert data["space"] == "color.L2.a20" and data["version"] == 1 and len(data["chunks"]) <= 8
        written = 0
        for c in data["chunks"]:
            row = self.rows.setdefault(c["idx"], {p: bytes(CHUNK_BYTES) for p in cs.PLANES})
            before = dict(row)
            for p in cs.PLANES:
                if p in c:
                    inc = zlib.decompress(base64.b64decode(c[p]))
                    assert len(inc) == CHUNK_BYTES
                    row[p] = (np.frombuffer(row[p], np.uint8) | np.frombuffer(inc, np.uint8)).tobytes()
            written += row != before
        return {"recorded": True, "rows_written": written, "new_bits": {"observed": 1, "verified": 0, "declared": 0}}


class _Err(Exception):
    def __init__(self, code, body):
        super().__init__(f"http {code}")
        self.status_code, self.body = code, body


@pytest.fixture
def store(tmp_path):
    return ColorCellStore(tmp_path)


def fill(store, rs, plane="verified"):
    store.mark(plane, [rgb_to_id(r, 1, 2) for r in rs])
    store.save()


def test_first_sync_sends_only_non_empty_chunks_and_planes(store, monkeypatch):
    monkeypatch.delenv("COLOR_SYNC", raising=False)
    fill(store, [0, 9, 8])  # chunks 0 and 1
    w = FakeWorker()
    out = cs.maybe_sync(store, "http://x", clips_done=5, force=True, now=1000.0, post=w)
    assert out["status"] == "synced" and out["chunks_sent"] == 2 and out["requests"] == 1
    sent = w.requests[0]["chunks"]
    assert [c["idx"] for c in sent] == [0, 1]
    assert set(sent[0]) == {"idx", "verified"}  # empty planes are not transmitted
    assert len(w.rows) == 2


def test_unchanged_store_makes_no_request(store):
    fill(store, [3])
    w = FakeWorker()
    assert cs.maybe_sync(store, "http://x", force=True, now=10.0, post=w)["status"] == "synced"
    before = len(w.requests)
    out = cs.maybe_sync(store, "http://x", clips_done=1, now=10.0 + 4000, post=w)  # due by time, but nothing changed
    assert out["status"] == "nothing_changed" and out["chunks_sent"] == 0 and len(w.requests) == before
    # a forced run resends everything once (full resend heals lost updates), then it is quiet again
    assert cs.maybe_sync(store, "http://x", force=True, now=20.0 + 90_000, post=w)["status"] == "synced"
    assert cs.maybe_sync(store, "http://x", now=20.0 + 90_000 + 4000, post=w)["status"] == "nothing_changed"

def test_only_changed_chunks_are_resent(store):
    fill(store, [0, 9])
    w = FakeWorker()
    cs.maybe_sync(store, "http://x", force=True, now=10.0, post=w)
    w.requests.clear()
    fill(store, [200], plane="observed")  # chunk 25
    out = cs.maybe_sync(store, "http://x", now=10.0 + 4000, post=w)
    assert out["chunks_sent"] == 1 and [c["idx"] for c in w.requests[0]["chunks"]] == [25]


def test_cadence_time_and_clip_triggers(store, monkeypatch):
    monkeypatch.setenv("COLOR_SYNC_EVERY_CLIPS", "50")
    fill(store, [1])
    w = FakeWorker()
    assert cs.maybe_sync(store, "http://x", clips_done=1, now=10_000.0, post=w)["status"] == "synced"  # first: long overdue
    fill(store, [2])
    assert cs.maybe_sync(store, "http://x", clips_done=10, now=10_100.0, post=w)["status"] == "not_due"  # < min gap
    assert cs.maybe_sync(store, "http://x", clips_done=10, now=11_000.0, post=w)["status"] == "not_due"  # 1000 s, 20 clips
    assert cs.maybe_sync(store, "http://x", clips_done=40, now=11_100.0, post=w)["status"] == "synced"  # 70 clips >= 50
    fill(store, [3])
    assert cs.maybe_sync(store, "http://x", clips_done=1, now=11_100.0 + 3601, post=w)["status"] == "synced"  # hourly


def test_budget_never_exceeds_32_rows_and_4_requests(store):
    for r in range(0, 256, 4):  # touches all 32 chunks
        store.mark("observed", [rgb_to_id(r, 0, 0)])
    store.save()
    w = FakeWorker()
    out = cs.maybe_sync(store, "http://x", force=True, now=1.0, post=w)
    assert out["chunks_sent"] == 32 and out["requests"] == 4 and out["rows_written"] == 32
    assert all(len(r["chunks"]) <= 8 for r in w.requests)


def test_max_chunks_cap_defers_the_rest(store, monkeypatch):
    monkeypatch.setenv("COLOR_SYNC_MAX_CHUNKS", "3")
    for r in range(0, 256, 8):
        store.mark("observed", [rgb_to_id(r, 0, 0)])
    store.save()
    w = FakeWorker()
    out = cs.maybe_sync(store, "http://x", force=True, now=1.0, post=w)
    assert out["chunks_sent"] == 3 and out["deferred_chunks"] == 29


def test_table_missing_backs_off_for_hours(store):
    fill(store, [1])
    w = FakeWorker()
    w.mode = "table_missing"
    assert cs.maybe_sync(store, "http://x", force=True, now=100.0, post=w)["status"] == "table_missing"
    w.mode = "ok"
    out = cs.maybe_sync(store, "http://x", now=100.0 + 3600 * 2, post=w)
    assert out["status"] == "backoff" and out["reason"] == "table_missing"
    assert cs.maybe_sync(store, "http://x", now=100.0 + 3600 * 7, post=w)["status"] == "synced"


def test_version_mismatch_and_errors_never_raise_and_retry_later(store):
    fill(store, [1])
    w = FakeWorker()
    w.mode = "409"
    assert cs.maybe_sync(store, "http://x", force=True, now=1.0, post=w)["status"] == "version_mismatch"
    st = cs.load_state(store)
    assert st["backoff_reason"] == "version_mismatch"
    w.mode = "boom"
    st["backoff_until"] = 0
    cs._save_state(store, st)
    assert cs.maybe_sync(store, "http://x", force=True, now=5.0, post=w)["status"] == "error"
    w.mode = "degraded"
    assert cs.maybe_sync(store, "http://x", force=True, now=6.0, post=w)["status"] == "not_recorded"
    w.mode = "ok"
    assert cs.maybe_sync(store, "http://x", force=True, now=7.0, post=w)["status"] == "synced"  # digests were not advanced by failures


def test_disabled_busy_and_no_api(store, monkeypatch):
    w = FakeWorker()
    assert cs.maybe_sync(store, "", post=w)["status"] == "no_api"
    monkeypatch.setenv("COLOR_SYNC", "0")
    assert cs.maybe_sync(store, "http://x", force=True, post=w)["status"] == "disabled"
    monkeypatch.delenv("COLOR_SYNC")
    with cs._FileLock(store.dir / "sync.lock"):
        assert cs.maybe_sync(store, "http://x", force=True, post=w)["status"] == "busy"
    assert not w.requests


def test_sync_state_is_shared_between_containers(tmp_path):
    a, b = ColorCellStore(tmp_path), ColorCellStore(tmp_path)
    a.mark("verified", [rgb_to_id(0, 0, 1)])
    a.save()
    b.mark("observed", [rgb_to_id(100, 0, 1)])
    b.save()
    w = FakeWorker()
    cs.maybe_sync(a, "http://x", force=True, now=1.0, post=w)
    n = len(w.requests)
    out = cs.maybe_sync(b, "http://x", now=2.0, post=w)  # the other container just synced: not due again
    assert out["status"] == "not_due" and len(w.requests) == n
    assert {c["idx"] for r in w.requests for c in r["chunks"]} == {0, 12}  # b's bits travelled with a's sync


def test_fetch_remote_report_swallows_errors():
    assert cs.fetch_remote_report("http://x", get=lambda *a, **k: {"covered": 3}) == {"covered": 3}

    def boom(*a, **k):
        raise RuntimeError("down")

    assert cs.fetch_remote_report("http://x", get=boom) is None