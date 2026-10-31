"""Per-container loop metrics log, its summariser, and the duplicate-skip helpers."""
from __future__ import annotations

import importlib.util
import json
import re
import time
from pathlib import Path

from src.knowledge.loop_metrics import LoopMetricsLog, metrics_name

ROOT = Path(__file__).resolve().parents[1]


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_log_appends_json_lines(tmp_path):
    log = LoopMetricsLog(tmp_path, name="explorer")
    assert log.log(outcome="accepted", rerolls=1, new_cells=3, post_items=36)
    assert log.log(outcome="rejected", rerolls=3)
    rows = [json.loads(x) for x in log.path.read_text(encoding="utf-8").splitlines()]
    assert [r["outcome"] for r in rows] == ["accepted", "rejected"]
    assert rows[0]["name"] == "explorer" and rows[0]["new_cells"] == 3 and rows[0]["t"] > 0


def test_log_rotates_and_stays_small(tmp_path):
    log = LoopMetricsLog(tmp_path, name="x", max_bytes=2048)
    for i in range(200):
        log.log(outcome="accepted", job_id=f"job-{i}", pad="p" * 40)
    files = sorted(p.name for p in tmp_path.iterdir())
    assert files == ["loop_metrics_x.jsonl", "loop_metrics_x.jsonl.1"]
    assert all(p.stat().st_size < 2048 + 400 for p in tmp_path.iterdir())


def test_log_never_raises(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("not a dir")
    assert LoopMetricsLog(blocker / "sub", name="x").log(outcome="error") is False


def test_metrics_name_prefers_env(monkeypatch):
    monkeypatch.delenv("LOOP_METRICS_NAME", raising=False)
    assert metrics_name("main", "window") == "main-window"
    monkeypatch.setenv("LOOP_METRICS_NAME", "balanced")
    assert metrics_name("main", "window") == "balanced"


def test_summary_and_projection(tmp_path):
    mod = _load("scripts/loop_metrics.py", "loop_metrics_script")
    now = int(time.time())
    log = LoopMetricsLog(tmp_path, name="explorer")
    rows = []
    # 8 clips over 2 hours: 6 accepted (36 items, 4 write requests, 5 new cells), 2 rejected duplicates
    for i in range(8):
        rejected = i in (3, 6)
        rows.append({
            "t": now - 7200 + i * (7200 // 7), "name": "explorer",
            "outcome": "rejected" if rejected else "accepted",
            "rerolls": 3 if rejected else 1,
            "new_cells": 0 if rejected else 5,
            "post_items": 0 if rejected else 36,
            "post_requests": 0 if rejected else 1,
            "write_requests": 1 if rejected else 4,
        })
    log.path.write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n", encoding="utf-8")
    recs = mod.load_records(tmp_path, now - 24 * 3600)
    assert len(recs) == 8
    s = mod.summarise(recs, rows_per_item=3.0, fixed_overhead=7300)
    c = s["containers"]["explorer"]
    assert c["clips"] == 8 and c["accepted"] == 6 and c["rejected"] == 2
    assert abs(c["accept_rate"] - 0.75) < 1e-9
    assert c["new_cells"] == 30
    assert abs(c["post_items_per_clip"] - 36.0) < 1e-9
    # rows/clip = 36*3 + mean write requests ((6*4 + 2*1) / 8 = 3.25)
    assert abs(c["est_d1_rows_per_clip"] - (108 + 3.25)) < 1e-6
    assert abs(c["clips_per_hour"] - 4.0) < 0.05
    expected = c["clips_per_hour"] * 24 * c["est_d1_rows_per_clip"] + 7300
    assert abs(s["total"]["projected_d1_rows_per_day"] - expected) < 1e-6
    out = mod.render(s, 24, tmp_path)
    assert "accept rate 75%" in out and "100,000" in out


def test_summary_script_handles_empty_dir(tmp_path, capsys):
    mod = _load("scripts/loop_metrics.py", "loop_metrics_script2")
    assert mod.main(["--dir", str(tmp_path / "missing")]) == 0
    assert "No loop metrics" in capsys.readouterr().out
    assert mod.main(["--dir", str(tmp_path), "--json"]) == 0


def test_iteration_outcome():
    loop = _load("scripts/automate_loop.py", "automate_loop_metrics_test")

    class G:
        fingerprint = object()

    assert loop.iteration_outcome(run_succeeded=False, rejected=True, gate=G()) == "rejected"
    assert loop.iteration_outcome(run_succeeded=True, rejected=False, gate=G()) == "accepted"
    assert loop.iteration_outcome(run_succeeded=True, rejected=False, gate=None) == "unchecked"
    assert loop.iteration_outcome(run_succeeded=False, rejected=False, gate=G()) == "error"
    err = loop.DuplicateClipSkipped(4, "combined 0.01 < 0.1", "abc")
    assert err.attempts == 4 and "4 attempt" in str(err)


def test_rejected_clip_is_never_published():
    """Static guard: the rejection check must come before finish_loop_job (publish) in the loop body."""
    src = (ROOT / "scripts" / "automate_loop.py").read_text(encoding="utf-8")
    assert src.index("raise DuplicateClipSkipped") < src.index("finish_loop_job(args.api_base, job_id, path")
    assert src.index("raise DuplicateClipSkipped") < src.index("extract_from_video(path)")


def test_compose_shares_novelty_store_across_loop_services():
    text = (ROOT / "docker-compose.local.yml").read_text(encoding="utf-8")
    for svc in ("explorer", "exploiter", "balanced"):
        block = re.search(rf"^  {svc}:\n(.*?)(?=^  \S|\Z)", text, re.S | re.M).group(1)
        assert "NOVELTY_STORE_DIR: /app/knowledge/novelty" in block, svc
        assert f"LOOP_METRICS_NAME: {svc}" in block, svc
    assert "- ./knowledge:/app/knowledge" in text

def test_budget_report_covers_every_container_and_projects_daily_total(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("D1_DAILY_WRITE_BUDGET", "70000")  # explicit: the shipped default is 50,000
    import calendar

    from src.knowledge import write_budget as wb

    mod = _load("scripts/loop_metrics.py", "loop_metrics_script_budget")
    now = float(calendar.timegm((2026, 10, 27, 6, 0, 0)))  # 06:00 UTC
    ledger = tmp_path / "ledger"
    for name, rows in (("interpret", 1000), ("sound", 300), ("explorer", 6000), ("balanced", 12000)):
        b = wb.WriteBudget(name=name, directory=ledger, daily_budget=70000, clock=lambda: now - 3600 * 5)
        assert b.reserve(rows)
        b.clock = lambda: now - 60  # last post a minute ago, so the container counts as still running
        b.reserve(0)
        b._mutate(lambda d, n: d["containers"][name].update(last_t=now - 60))
    rep = mod.budget_report(ledger, now=now)
    cs = rep["containers"]
    assert set(cs) == {"interpret", "sound", "explorer", "balanced"}
    assert cs["interpret"]["used"] == 1000 and cs["interpret"]["allowance"] == 10500
    # 6000 rows in ~5 h -> ~29k/day uncapped, capped at the 24.5k allowance (35%) because the gate stops posting there
    assert cs["explorer"]["projected_rows_per_day"] == 24500 and cs["explorer"]["projected_rows_per_day_uncapped"] > 24500
    assert cs["interpret"]["projected_rows_per_day"] < 10500
    assert rep["total_projected_rows_per_day"] <= 70000 and rep["total_used"] == 19300
    text = mod.render_budget(rep)
    assert "interpret" in text and "sound" in text and "ALL containers" in text


def test_budget_report_empty_ledger(tmp_path):
    mod = _load("scripts/loop_metrics.py", "loop_metrics_script_budget2")
    rep = mod.budget_report(tmp_path / "none")
    assert rep["containers"] == {} and "no rows charged" in mod.render_budget(rep)


def test_budget_report_shows_calibration_and_untrusted_ledger(tmp_path):
    from src.knowledge import write_budget as wb

    mod = _load("scripts/loop_metrics.py", "loop_metrics_script_budget3")
    ledger = tmp_path / "ledger"
    b = wb.WriteBudget(name="explorer", directory=ledger, daily_budget=50000)
    assert b.reserve(40)
    b.record_response(40, 20)
    text = mod.render_budget(mod.budget_report(ledger))
    assert "Ledger calibration: 1 posts booked at the Worker's real rows_written" in text and "2.00" in text
    assert "LEDGER UNTRUSTED" not in text
    for _ in range(wb.UNREPORTED_TRIP):
        b.reserve(10)
        b.record_response(10, None)
    rep = mod.budget_report(ledger)
    assert rep["calibration"]["trusted"] is False
    assert "LEDGER UNTRUSTED" in mod.render_budget(rep)
