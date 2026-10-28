"""Shared pytest setup: keep the D1 write-budget ledger and local write buffers out of the real knowledge/ volume."""
import pytest


@pytest.fixture(autouse=True)
def _isolated_write_budget(tmp_path, monkeypatch):
    monkeypatch.setenv("WRITE_BUDGET_DIR", str(tmp_path / "write_budget"))
    monkeypatch.setenv("WRITE_BUFFER_DIR", str(tmp_path / "write_buffer"))
    for var in ("D1_DAILY_WRITE_BUDGET", "D1_BUDGET_NAME", "D1_BUDGET_WEIGHTS", "D1_BUDGET_LOW_FRACTION", "LOOP_METRICS_NAME"):
        monkeypatch.delenv(var, raising=False)
    try:
        from src.knowledge import write_budget
        write_budget.reset_budget()
    except Exception:
        pass
    yield
    try:
        from src.knowledge import write_budget
        write_budget.reset_budget()
    except Exception:
        pass
