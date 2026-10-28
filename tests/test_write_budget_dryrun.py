"""The offline write-budget harness: budgeted loops write far fewer rows than baseline and stay inside the budget."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("write_budget_dryrun", Path(__file__).resolve().parent.parent / "scripts" / "write_budget_dryrun.py")
dry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dry)


def test_budgeted_run_is_under_allowances_and_below_baseline():
    seconds = 2 * 3600
    base = dry.simulate("baseline", dry.utc(0), seconds)
    bud = dry.simulate("budgeted", dry.utc(0), seconds)
    assert bud["total_rows"] < base["total_rows"] / 2
    for name, c in bud["containers"].items():
        assert c["rows"] <= c["allowance"], name
        assert c["rejected_by_worker"] == 0
    assert bud["total_rows"] <= 70000


def test_without_rows_written_reporting_budget_still_holds():
    bud = dry.simulate("budgeted", dry.utc(0), 3600, reports_rows=False)
    assert bud["total_rows"] <= 70000
    assert all(c["rejected_by_worker"] == 0 for c in bud["containers"].values())


def test_simulation_restores_clock_and_env():
    import os
    import time

    before = (time.time, time.sleep)
    dry.simulate("budgeted", dry.utc(12), 300)
    assert (time.time, time.sleep) == before
    assert "D1_BUDGET_NAME" not in os.environ
