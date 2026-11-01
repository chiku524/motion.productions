"""allowance-hard-cap: a container's REAL rows never pass its allowance (reproduces the 2026-10-31 overshoot)."""
import threading

from src.knowledge import write_budget as wb

R = "POST /api/knowledge/discoveries"


def _b(tmp_path, name="sound", budget=50000, weights=None, clock=None):
    kw = {"clock": clock} if clock else {}
    return wb.WriteBudget(name=name, directory=tmp_path, daily_budget=budget, weights=weights, **kw)


def _learn_low_ratio(b):
    # explorer-style posts teach the shared route ratio ~0.3 (mostly count bumps)
    for _ in range(wb.RATIO_MIN_SAMPLES):
        assert b.reserve(100, worst=100, route=R)
        b.record_response(100, 30, route=R, worst=100)


def test_learned_reservation_cannot_overshoot_allowance(tmp_path):
    ex = _b(tmp_path, "explorer")
    _learn_low_ratio(ex)
    snd = _b(tmp_path, "sound")  # allowance 5000
    assert snd.allowance() == 5000
    worst = 100
    while True:
        est = snd.scaled_reservation(worst, R)
        if not snd.reserve(est, worst=worst, route=R):
            break
        snd.record_response(est, worst, route=R, worst=worst)  # sound's items are all new: real == worst
    assert snd.used() <= 5000  # before the fix: used + est <= cap let the real 100 rows through -> 5,0xx


def test_peak_ratio_holds_more_when_model_undercounts(tmp_path):
    snd = _b(tmp_path, "sound")
    assert snd.reserve(50, worst=50, route=R)
    snd.record_response(50, 60, route=R, worst=50)  # Worker wrote more than the model's worst case
    while snd.reserve(50, worst=50, route=R):
        snd.record_response(50, 60, route=R, worst=50)
    assert snd.used() <= 5000


def test_concurrent_posts_share_holds(tmp_path):
    a, b = _b(tmp_path, "sound"), _b(tmp_path, "sound")  # two processes of one bucket
    assert a.reserve(2000, worst=2000, route=R)
    assert b.reserve(2000, worst=2000, route=R)
    assert not a.reserve(30, worst=1001, route=R)  # 4,000 held + 1,001 > 5,000
    a.record_response(2000, 2000, route=R, worst=2000)
    b.record_response(2000, 2000, route=R, worst=2000)
    assert a.used() == 4000 and a.remaining() == 1000


def test_hold_released_on_settle_and_refund(tmp_path):
    s = _b(tmp_path, "sound")
    assert s.reserve(10, worst=100, route=R)
    assert s.remaining() == 5000 - 100
    s.record_response(10, 5, route=R, worst=100)
    assert s.remaining() == 4995
    assert s.reserve(10, worst=100, route=R)
    s.refund(10)
    assert s.remaining() == 4995


def test_stale_hold_expires(tmp_path):
    now = [1_793_440_000.0]
    s = _b(tmp_path, "sound", clock=lambda: now[0])
    assert s.reserve(10, worst=4000, route=R)  # process dies before settling
    assert not s.reserve(10, worst=2000, route=R)
    now[0] += wb.HOLD_TTL_S + 1
    assert s.reserve(10, worst=2000, route=R)


def test_midday_weight_change_keeps_first_allowance(tmp_path):
    now = [1_793_440_000.0]
    old = _b(tmp_path, "balanced", weights={"balanced": 30, "other": 5}, clock=lambda: now[0])
    assert old.allowance() == 15000
    assert old.reserve(12000)
    new = _b(tmp_path, "balanced", weights={"balanced": 20, "other": 5}, clock=lambda: now[0])
    assert new.allowance() == 10000
    assert new.remaining() == 3000  # pinned 15,000 for the day: 12,000 is not an "overshoot" of 10,000
    assert not new.reserve(3001) and new.reserve(3000) and not new.reserve(1)
    now[0] += 86400  # next UTC day: the new weight applies
    assert new.remaining() == 10000


def test_unpinned_old_ledger_counts_overshoot_as_used(tmp_path):
    s = _b(tmp_path, "balanced")
    assert s.reserve(9000)
    import json
    d = json.loads(s.path.read_text())
    d["containers"]["balanced"]["used"] = 11700
    d.pop("allowances", None)
    s.path.write_text(json.dumps(d))
    assert s.remaining() == 0 and not s.reserve(1)


def test_threads_never_overshoot(tmp_path):
    s = _b(tmp_path, "sound")
    lock_errors = []

    def worker():
        try:
            while s.reserve(20, worst=100, route=R):
                s.record_response(20, 100, route=R, worst=100)
        except Exception as e:  # pragma: no cover
            lock_errors.append(e)

    ts = [threading.Thread(target=worker) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not lock_errors and s.used() <= 5000
