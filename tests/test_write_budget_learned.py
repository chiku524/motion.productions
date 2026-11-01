"""Learned reservation: reserve worst x learned real/worst ratio, keep the hard cap on the worst case, book real rows."""
from src.knowledge import write_budget as wb


def _b(tmp_path, budget=100000, name="sound"):
    return wb.WriteBudget(name=name, directory=tmp_path, daily_budget=budget)


def test_route_key_collapses_ids():
    assert wb.route_key("post", "/api/jobs/ab-12/complete?x=1") == "POST /api/jobs/*/complete"
    assert wb.route_key("POST", "/api/knowledge/discoveries") == "POST /api/knowledge/discoveries"


def test_worst_case_until_enough_samples_then_learned_ratio(tmp_path):
    b, r = _b(tmp_path), "POST /api/knowledge/discoveries"
    assert b.scaled_reservation(100, r) == 100
    for _ in range(wb.RATIO_MIN_SAMPLES):
        assert b.reserve(100, worst=100)
        b.record_response(100, 27, route=r, worst=100)  # real ~ 0.27 of worst (the measured 3.7x)
    got = b.scaled_reservation(100, r)
    assert got == 34  # 0.27 x 1.25 margin, rounded up
    t = b.trust()
    assert t["route_ratios"][r]["n"] == wb.RATIO_MIN_SAMPLES and t["worst_over_actual"] == round(100 / 27, 3)


def test_ratio_floor_and_ceiling(tmp_path):
    b, r = _b(tmp_path), "POST /api/x"
    for _ in range(wb.RATIO_MIN_SAMPLES):
        b.reserve(10, worst=10)
        b.record_response(10, 0, route=r, worst=10)
    assert b.scaled_reservation(100, r) == 25  # floor
    for _ in range(200):
        b.reserve(10, worst=10)
        b.record_response(10, 30, route=r, worst=10)  # model under-estimates: never reserve above worst
    assert b.scaled_reservation(100, r) == 100


def test_hard_cap_uses_worst_case_and_real_rows(tmp_path):
    b = wb.WriteBudget(name="explorer", directory=tmp_path, daily_budget=10000, weights={"explorer": 100})
    assert b.reserve(30, worst=100)
    b.record_response(30, 95, route="POST /a", worst=100)
    assert b.used() == 95  # real rows booked, not the reservation
    # 9,905 left globally: a learned 30-row reservation whose worst case (9,906) would not fit is refused
    assert not b.reserve(30, worst=9906)
    assert b.reserve(30, worst=9905)


def test_unreported_books_worst_plus_surcharge(tmp_path):
    b = _b(tmp_path)
    assert b.reserve(25, worst=100)
    b.record_response(25, None, route="POST /a", worst=100)
    assert b.used() == 100 + 25  # worst + 25% surcharge, not the learned reservation


def test_ratios_survive_utc_reset(tmp_path):
    now = [1_800_000_000.0]
    b = wb.WriteBudget(name="sound", directory=tmp_path, daily_budget=100000, clock=lambda: now[0])
    for _ in range(wb.RATIO_MIN_SAMPLES):
        b.reserve(100, worst=100)
        b.record_response(100, 20, route="POST /a", worst=100)
    now[0] += 86400
    assert b.used() == 0 and b.scaled_reservation(100, "POST /a") < 100
