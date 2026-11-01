from src.knowledge import write_budget as wb

T0 = 1793491200.0 + 3600  # 2026-11-01 01:00 UTC


def mk(tmp_path, name, budget, clock=lambda: T0):
    return wb.WriteBudget(name=name, directory=tmp_path, daily_budget=budget, clock=clock)


def test_all_buckets_pinned_together_and_sum_within_budget(tmp_path):
    b = mk(tmp_path, "explorer", 50000)
    assert b.reserve(10)
    snap = b.snapshot()
    pins = snap["allowances"]
    assert snap["day_budget"] == 50000
    assert set(pins) == set(b.weights)
    assert sum(pins.values()) <= 50000
    assert pins["explorer"] == 17500 and pins["balanced"] == 10000


def test_every_container_sees_same_pins(tmp_path):
    a = mk(tmp_path, "explorer", 50000)
    assert a.reserve(5)
    c = mk(tmp_path, "sound", 50000)
    assert c.reserve(5)
    assert a.snapshot()["allowances"] == c.snapshot()["allowances"]


def test_higher_env_never_raises_pinned_day(tmp_path):
    assert mk(tmp_path, "explorer", 50000).reserve(5)
    hi = mk(tmp_path, "balanced", 70000)
    assert hi.reserve(5)
    snap = hi.snapshot()
    assert snap["day_budget"] == 50000 and snap["allowances"]["balanced"] == 10000


def test_lower_env_repins_down_and_keeps_used(tmp_path):
    assert mk(tmp_path, "explorer", 70000).reserve(100)
    lo = mk(tmp_path, "balanced", 50000)
    assert lo.reserve(5)
    snap = lo.snapshot()
    assert snap["day_budget"] == 50000 and sum(snap["allowances"].values()) <= 50000
    assert snap["containers"]["explorer"]["used"] == 100


def test_legacy_per_bucket_pins_are_repinned(tmp_path):
    b = mk(tmp_path, "explorer", 50000)
    assert b.reserve(1)
    data = b.snapshot()
    data.pop("day_budget")
    data["allowances"] = {"sound": 7000, "interpret": 10500, "explorer": 24500, "balanced": 14000}
    b._write(data)
    assert b.reserve(1)
    snap = b.snapshot()
    assert snap["allowances"]["explorer"] == 17500 and sum(snap["allowances"].values()) <= 50000


def test_global_cap_uses_pinned_day_budget(tmp_path):
    assert mk(tmp_path, "explorer", 1000).reserve(1)
    hi = mk(tmp_path, "explorer", 100000)
    assert not hi.reserve(400)  # explorer pinned at 350 of a 1000 day
    assert hi.reserve(300)


def test_rollover_loan_moves_rows_not_creates_them(tmp_path, monkeypatch):
    monkeypatch.setenv("D1_ROLLOVER", "1")
    late = 1793491200.0 + 22 * 3600
    b = mk(tmp_path, "explorer", 50000, clock=lambda: late)
    assert b.reserve(1)
    data = b.snapshot()
    eff = {k: b.effective_allowance(data, k, late) for k in b.weights}
    assert eff["explorer"] > data["allowances"]["explorer"]
    assert sum(data["allowances"].values()) <= 50000
    assert data["loans"]["lent"] == eff["explorer"] - data["allowances"]["explorer"]
    big = mk(tmp_path, "explorer", 50000, clock=lambda: late)
    assert not big.reserve(50001)  # a loan never lifts the global cap
    assert data["loans"]["lent"] > 0
