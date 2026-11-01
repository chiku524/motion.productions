"""Repro for the 2026-10-31 restart stall: containers ahead of their pace line slept without ever persisting the
new day pins, so the ledger kept legacy 70k-era allowances (sum 56000, no day_budget) until a first post."""
from src.knowledge import write_budget as wb

T0 = 1793491200.0 + 9000  # 2026-11-01 02:30 UTC (10:30 PM ET), ~10% into the UTC day


def test_pacing_sleep_persists_day_pins_from_legacy_ledger(tmp_path):
    b = wb.WriteBudget(name="explorer", directory=tmp_path, daily_budget=50000, clock=lambda: T0)
    assert b.reserve(2898)  # front-loaded morning: already past the ~10% pace line of a 17.5k allowance
    data = b.snapshot()
    data.pop("day_budget")
    data["allowances"] = {"sound": 7000, "interpret": 10500, "explorer": 24500, "balanced": 14000}
    b._write(data)

    pacer = wb.WritePacer(budget=b, slack=0.03, chunk_s=1, enabled=True)
    slept = pacer.wait_for_pace(should_stop=lambda: pacer.total_waited_s > 0 or False, sleep=lambda s: setattr(pacer, "total_waited_s", 1.0))
    assert slept > 0  # ahead of pace: sleeping is the intended behaviour, not a crash/deadlock
    snap = b.snapshot()
    assert snap["day_budget"] == 50000
    assert snap["allowances"]["explorer"] == 17500 and sum(snap["allowances"].values()) <= 50000
