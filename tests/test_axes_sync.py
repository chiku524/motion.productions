import pytest

from src.knowledge import axes_sync
from src.knowledge.write_budget import estimate_rows


@pytest.fixture(autouse=True)
def _on(monkeypatch):
    monkeypatch.setenv("LOOP_AXES_SYNC", "1")


def test_collect_keys_match_allowlist():
    c = axes_sync.collect({"size": 524288, "covered": 9, "per_alpha_level": [1] * 16},
                          {"pairs": {"genrexlighting_preset": {"seen": 3, "universe": 10}}})
    assert c["opacity.total"] == (9, 524288)
    assert c["opacity.level.15"] == (1, 32768)
    assert c["pair.genrexlighting_preset"] == (3, 10)
    assert len(c) == 18


def test_disabled_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("LOOP_AXES_SYNC")
    assert axes_sync.maybe_sync("http://x", directory=tmp_path)["status"] == "disabled"


def test_changed_only_and_interval(tmp_path):
    calls = []

    def post(base, path, body, timeout=0):
        calls.append(body)
        return {"recorded": True, "rows_written": len(body["items"])}

    counts = {"opacity.total": (5, 100), "pair.axb": (1, 4)}
    r = axes_sync.maybe_sync("http://x", now=1e6, post=post, counts=counts, directory=tmp_path)
    assert r["status"] == "synced" and r["items"] == 2
    assert axes_sync.maybe_sync("http://x", now=1e6 + 60, post=post, counts=counts, directory=tmp_path)["status"] == "not_due"
    counts["opacity.total"] = (6, 100)
    r = axes_sync.maybe_sync("http://x", now=1e6 + 7 * 3600, post=post, counts=counts, directory=tmp_path)
    assert r["items"] == 1 and calls[-1]["items"][0]["key"] == "opacity.total"


def test_table_missing_backs_off(tmp_path):
    def post(*a, **k):
        return {"available": False, "reason": "table_missing"}

    r = axes_sync.maybe_sync("http://x", now=1e6, post=post, counts={"opacity.total": (1, 2)}, directory=tmp_path)
    assert r["status"] == "table_missing"
    r = axes_sync.maybe_sync("http://x", now=1e6 + 7 * 3600, post=post, counts={"opacity.total": (1, 2)}, directory=tmp_path)
    assert r["status"] == "backoff"


def test_post_error_never_raises(tmp_path):
    def post(*a, **k):
        raise RuntimeError("boom")

    r = axes_sync.maybe_sync("http://x", now=1e6, post=post, counts={"opacity.total": (1, 2)}, directory=tmp_path)
    assert r["status"] == "error"


def test_estimate_rows_axes():
    n, _ = estimate_rows("POST", "/api/coverage/axes", {"items": [{}] * 5})
    assert n == 5
