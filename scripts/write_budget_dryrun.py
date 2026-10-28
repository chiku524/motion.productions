#!/usr/bin/env python3
"""
Offline dry run of the D1 write budget: simulated loop output for every container against a MOCK Worker.

    python scripts/write_budget_dryrun.py                    # 10 simulated minutes + a simulated 24 h, table
    python scripts/write_budget_dryrun.py --minutes 10 --no-day --json
    python scripts/write_budget_dryrun.py --no-reports-rows  # Worker not yet deployed: client keeps worst-case estimates

No network, no real Worker, no D1, no containers: HTTP is replaced by an in-process mock (``requests.request`` in
src.api_client), the clock is virtual (time.time / monotonic / sleep are patched while it runs), and state lives in a
temp directory. The loops' REAL client code runs: the gate (api_client), the shared ledger, the discovery spool, the
linguistic coalescer and the interpretation outbox. The per-iteration "work" is a calibrated MODEL of the loops, not a
measurement; tune SCENARIO below if the live numbers differ. Two modes are compared:

    baseline  WRITE_BUFFERS=0, D1_DAILY_WRITE_BUDGET=0   (what ran the first time: ~800 k rows/day)
    budgeted  docker-compose.local.yml defaults          (shared 70 k/day budget + local buffers)

The mock Worker prices rows like the real one (INSERT = 1 + indexes, count bump = 1, blend repeat = 0) and enforces
the 100 k/day free cap (503 + X-Degraded + Retry-After 900 once crossed).
"""
from __future__ import annotations

import argparse
import calendar
import contextlib
import io
import logging
import heapq
import json
import math
import os
import random
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

D1_FREE_LIMIT = 100_000
API = "http://mock.worker"

# Rows per NEW item (existing item = 1 row for a count bump, blends 0), mirroring write_budget.INSERT_ROWS.
NEW_ROWS = {"static_colors": 8, "colors": 5, "static_sound": 5, "blends": 6, "narrative": 5, "motion": 4}

# Calibrated model of one loop iteration. period = seconds between iterations (delay + render), universe/prefill = how
# much of the registry already exists in D1 (log-uniform draw: new fraction = ln(U/P)/ln(U)).
SCENARIO = {
    "explorer":          {"kind": "frame",    "period": 30.0, "offset": 0.0},
    "balanced":          {"kind": "window",   "period": 30.0, "offset": 15.0},
    "interpret":         {"kind": "interpret", "period": 95.0, "offset": 5.0},
    "sound":             {"kind": "sound",    "period": 77.5, "offset": 20.0},
    "webjobs":           {"kind": "webjobs",  "period": 900.0, "offset": 100.0},
    "procedural-render": {"kind": "render",   "period": 900.0, "offset": 400.0},
}

# What docker-compose.local.yml sets per service (budgeted mode).
BUDGETED_ENV = {
    "explorer": {"DISCOVERY_FLUSH_INTERVAL_S": "120", "DISCOVERY_FLUSH_MAX_ITEMS": "72", "LINGUISTIC_FLUSH_INTERVAL_S": "900", "DISCOVERIES_MAX_ITEMS": "36"},
    "balanced": {"DISCOVERY_FLUSH_INTERVAL_S": "120", "DISCOVERY_FLUSH_MAX_ITEMS": "72", "LINGUISTIC_FLUSH_INTERVAL_S": "900", "DISCOVERIES_MAX_ITEMS": "36"},
    "interpret": {"INTERPRET_FLUSH_INTERVAL_S": "600", "INTERPRET_FLUSH_MAX_ITEMS": "10", "LINGUISTIC_FLUSH_INTERVAL_S": "900",
                  "LINGUISTIC_FLUSH_MAX_ITEMS": "40", "WRITE_BUDGET_SLEEP_WHEN_EXHAUSTED_S": "900"},
    "sound": {"DISCOVERY_FLUSH_INTERVAL_S": "600", "DISCOVERY_FLUSH_MAX_ITEMS": "24", "DISCOVERIES_MAX_ITEMS": "12",
              "WRITE_BUDGET_SLEEP_WHEN_EXHAUSTED_S": "900"},
    "webjobs": {"DISCOVERIES_MAX_ITEMS": "36"},
    "procedural-render": {"DISCOVERIES_MAX_ITEMS": "36"},
}
ENV_KEYS = sorted({k for env in BUDGETED_ENV.values() for k in env} | {
    "D1_BUDGET_NAME", "D1_DAILY_WRITE_BUDGET", "WRITE_BUFFERS", "WRITE_BUDGET_DIR", "WRITE_BUFFER_DIR",
    "DISCOVERIES_CHUNK_PAUSE_SECONDS", "D1_BUDGET_WEIGHTS", "LOOP_METRICS_NAME", "WORKER_START_SCRIPT"})


def utc(h: int = 0, m: int = 0) -> float:
    return float(calendar.timegm((2026, 10, 27, h, m, 0)))


class Resp:
    def __init__(self, status: int, body: dict, headers: dict | None = None):
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self.text = json.dumps(body)
        self.content = self.text.encode()
        self.url = API

    def json(self) -> dict:
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import requests

            raise requests.exceptions.HTTPError(str(self.status_code), response=self)


class MockWorker:
    """Prices and counts D1 rows like the Worker; enforces the free daily cap when ``limit`` is set."""

    def __init__(self, clock, reports_rows: bool, limit: int | None, prefill: dict[str, set]):
        self.clock = clock
        self.reports_rows = reports_rows
        self.limit = limit
        self.tables: dict[str, set] = {k: set(v) for k, v in prefill.items()}
        self.day = None
        self.day_total = 0
        self.crossed_100k_at: float | None = None
        self.current = "?"
        self.rows = defaultdict(int)
        self.requests = defaultdict(int)
        self.rejected = defaultdict(int)
        self.seq = 0

    def _roll(self) -> None:
        d = int(self.clock() // 86400)
        if d != self.day:
            self.day, self.day_total = d, 0

    def request(self, method, url, data=None, headers=None, timeout=None):
        self._roll()
        path = url[len(API):] if url.startswith(API) else url
        body = json.loads(data) if data else {}
        if method.upper() != "GET" and self.limit is not None and self.day_total >= self.limit:
            self.rejected[self.current] += 1
            return Resp(503, {"error": "free_tier_limit", "degraded": True}, {"X-Degraded": "free_tier_limit", "Retry-After": "900"})
        rows, out = self._price(method.upper(), path, body)
        if rows:
            self.rows[self.current] += rows
            self.day_total += rows
            if self.crossed_100k_at is None and self.day_total >= D1_FREE_LIMIT:
                self.crossed_100k_at = self.clock()
        self.requests[self.current] += 1
        if self.reports_rows:
            out["rows_written"] = rows
        return Resp(200, out)

    def _price(self, method: str, path: str, body: dict) -> tuple[int, dict]:
        if method == "GET":
            return 0, {}
        if path == "/api/knowledge/discoveries":
            return self._discoveries(body)
        if path == "/api/linguistic-registry/batch":
            new = upd = 0
            seen = self.tables.setdefault("ling", set())
            for k in {(i.get("domain"), str(i.get("span")).strip().lower()) for i in body.get("items", [])}:
                if k in seen:
                    upd += 1
                else:
                    seen.add(k)
                    new += 1
            return new * 5 + upd, {"inserted": new, "updated": upd}
        if path == "/api/interpretations/batch":
            n = len(body.get("items", []))
            return 4 * n, {"inserted": n}
        if path == "/api/interpretations":
            return 4, {"id": "i"}
        if path.startswith("/api/interpretations/"):
            return 5, {"ok": True}
        if path == "/api/jobs":
            self.seq += 1
            return 5, {"id": f"job-{self.seq}", "job": {"id": f"job-{self.seq}"}}
        if path.startswith("/api/jobs/"):
            return 3, {"ok": True}
        if path == "/api/learning":
            return 4, {"ok": True}
        if path.startswith("/api/coverage/color"):
            return 4 * min(32, max(1, len(body.get("chunks") or []))), {"ok": True}
        if path == "/api/loop/state":
            return 0, {"ok": True}
        return 3, {"ok": True}

    def _discoveries(self, body: dict) -> tuple[int, dict]:
        rows = 0
        results: dict[str, int] = {}
        for cat, items in body.items():
            if cat == "job_id":
                rows += 3
                continue
            groups = [(cat, items)] if not isinstance(items, dict) else [("narrative", [i for a in items.values() for i in a])]
            for c, arr in groups:
                seen = self.tables.setdefault(c, set())
                uniq = {}
                for it in arr:
                    ident = it.get("key") or json.dumps(it.get("output"), sort_keys=True)
                    uniq[ident] = uniq.get(ident, 0) + int(it.get("count_delta") or 1)
                for ident in uniq:
                    if ident in seen:
                        rows += 0 if c == "blends" else 1
                    else:
                        seen.add(ident)
                        rows += NEW_ROWS.get(c, 4)
                results[c] = results.get(c, 0) + len(uniq)
        return rows, {"results": results}


def _draw(rng: random.Random, universe: int) -> int:
    return int(universe ** rng.random())  # log-uniform ~ 1/x: a few very common items, a long tail


def _prefill(universe: int, frac: float) -> set:
    return {f"k{r}" for r in range(0, int(universe * frac))}


def build_prefill(universe: int) -> dict[str, set]:
    return {"static_colors": _prefill(universe, 0.66), "blends": {json.dumps({"id": r}, sort_keys=True) for r in range(int(universe * 0.25))},
            "static_sound": _prefill(universe, 0.00002), "narrative": _prefill(2000, 0.9)}


class Sim:
    UNIVERSE = 1_000_000

    def __init__(self, mode: str, start: float, seconds: float, seed: int, reports_rows: bool, budget: int):
        self.mode, self.start, self.end = mode, start, start + seconds
        self.rng = random.Random(seed)
        self.now = start
        self.reports_rows = reports_rows
        self.budget = budget
        self.tmp = tempfile.TemporaryDirectory(prefix="wb_dryrun_")
        base = Path(self.tmp.name)
        self.ledger_dir, self.buffer_dir = base / "write_budget", base / "write_buffer"
        limit = D1_FREE_LIMIT if mode == "budgeted" else None  # baseline: measure demand, note when 100k is crossed
        self.worker = MockWorker(lambda: self.now, reports_rows, limit, build_prefill(self.UNIVERSE))
        self.iter = defaultdict(int)
        self.cooldown: dict[str, float] = {}
        self.budgets: dict[str, object] = {}
        self.idle_s = defaultdict(float)

    # -- environment of one container -------------------------------------------------------------------------
    def env_for(self, name: str) -> dict[str, str]:
        e = {"D1_BUDGET_NAME": name, "WRITE_BUDGET_DIR": str(self.ledger_dir), "WRITE_BUFFER_DIR": str(self.buffer_dir),
             "DISCOVERIES_CHUNK_PAUSE_SECONDS": "0", "DISCOVERIES_MAX_ITEMS": "36"}
        if self.mode == "baseline":
            e.update({"WRITE_BUFFERS": "0", "D1_DAILY_WRITE_BUDGET": "0"})
        else:
            e.update({"WRITE_BUFFERS": "1", "D1_DAILY_WRITE_BUDGET": str(self.budget)})
            e.update(BUDGETED_ENV[name])
        return e

    def enter(self, name: str) -> None:
        from src import api_client
        from src.knowledge import write_budget as wb

        for k in ENV_KEYS:
            os.environ.pop(k, None)
        os.environ.update(self.env_for(name))
        os.environ["MOTION_API_SECRET"] = ""
        if name not in self.budgets:
            self.budgets[name] = wb.WriteBudget(name=name)
        wb.reset_budget(self.budgets[name])
        api_client._limit_cooldown_until = self.cooldown.get(name, 0.0)
        self.worker.current = name

    def leave(self, name: str) -> None:
        from src import api_client

        self.cooldown[name] = api_client._limit_cooldown_until

    # -- one iteration of each loop kind (the posts a loop makes, in the order it makes them) -----------------
    def new_job(self) -> str:
        from src import api_client

        try:
            r = api_client.api_post(API, "/api/jobs", {"workflow_type": "loop"})
            return str((r or {}).get("id") or "job")
        except api_client.APIError:
            return "local-" + str(self.iter["jobs"])

    def finish_job(self, job_id: str) -> None:
        from src import api_client
        from src.knowledge.remote_sync import is_local_job_id

        if is_local_job_id(job_id):
            return
        for path in (f"/api/jobs/{job_id}/complete", "/api/learning"):
            try:
                api_client.api_post(API, path, {"job_id": job_id})
            except api_client.APIError:
                pass

    def colors(self, n: int) -> list[dict]:
        return [{"key": f"k{_draw(self.rng, self.UNIVERSE)}", "r": 1, "g": 2, "b": 3, "name": "c"} for _ in range(n)]

    def blends(self, n: int) -> list[dict]:
        return [{"domain": "color", "output": {"id": _draw(self.rng, self.UNIVERSE)}, "name": "b"} for _ in range(n)]

    def spans(self, n: int) -> list[dict]:
        return [{"span": f"w{_draw(self.rng, 600)}", "canonical": "x", "domain": self.rng.choice(["color", "light", "motion", "sound"])} for _ in range(n)]

    def step(self, name: str, kind: str) -> float:
        """Run one iteration; returns extra idle seconds the loop sleeps because its allowance is gone."""
        from src import api_client
        from src.interpretation.linguistic_client import post_linguistic_growth
        from src.knowledge import remote_sync, write_buffers as wbuf

        self.iter[name] += 1
        i = self.iter[name]
        buffered = self.mode == "budgeted"
        if buffered and kind != "webjobs" and kind != "render":
            wbuf.flush_all(API)
        extra = wbuf.idle_when_exhausted() if buffered else 0.0
        if kind in ("frame", "window"):
            job = self.new_job()
            if kind == "frame":
                disc = {"static_colors": self.colors(6), "blends": self.blends(2), "motion": [{"key": f"m{self.rng.randrange(40)}"}]}
            else:
                disc = {"static_colors": self.colors(4), "blends": self.blends(3),
                        "narrative": {"themes": [{"key": f"t{_draw(self.rng, 2000)}", "name": "t"} for _ in range(2)]}}
            remote_sync.post_discoveries(API, disc, job_id=job)
            self.finish_job(job)
            post_linguistic_growth(API, self.spans(3))
            if i % 10 == 0:  # colour survey sync (COLOR_SYNC=1): 8 coverage chunks
                try:
                    api_client.api_post(API, "/api/coverage/color", {"chunks": [{"c": n} for n in range(8)]})
                except api_client.APIError:
                    pass
        elif kind == "sound":
            cells = [{"key": f"k{_draw(self.rng, 100) if self.rng.random() < 0.2 else self.rng.randrange(10**9)}"} for _ in range(4)]
            remote_sync.post_discoveries(API, {"static_sound": cells})
        elif kind == "interpret":
            outbox = wbuf.get_interpretation_outbox() if buffered else None
            for src, n in (("generate", 8), ("backfill", 12)):
                for _ in range(n):
                    pid = _draw(self.rng, 100_000) if src == "generate" else self.rng.randrange(2000)
                    instr = {"duration": 6.0, "colors": [f"c{self.rng.randrange(400)}"]}
                    if buffered:
                        outbox.record(f"prompt {src} {pid}", instr, src)
                    else:
                        try:
                            if src == "generate":
                                api_client.api_post(API, "/api/interpretations", {"prompt": f"p{pid}", **instr})
                            api_client.api_request_with_retry(API, "PATCH", f"/api/interpretations/p{pid}", data=instr)
                        except api_client.APIError:
                            pass
            post_linguistic_growth(API, self.spans(20))
        elif kind == "webjobs":
            job = self.new_job()
            remote_sync.post_discoveries(API, {"static_colors": self.colors(3), "blends": self.blends(2)}, job_id=job)
            self.finish_job(job)
        elif kind == "render":
            remote_sync.post_discoveries(API, {"static_colors": self.colors(2)})
        return extra

    # -- driver -------------------------------------------------------------------------------------------------
    def run(self) -> dict:
        orig = (time.time, time.monotonic, time.sleep)
        time.time = lambda: self.now
        time.monotonic = lambda: self.now - self.start
        time.sleep = lambda s: None
        import requests

        orig_req = requests.request
        requests.request = self.worker.request
        from src import api_client
        from src.knowledge import write_buffers as wbuf, write_budget as wb

        wbuf.reset_buffers()
        wb.reset_budget()
        api_client.reset_free_tier_cooldown()
        heap = [(self.start + c["offset"], n) for n, c in SCENARIO.items()]
        heapq.heapify(heap)
        try:
            while heap and heap[0][0] < self.end:
                t, name = heapq.heappop(heap)
                self.now = t
                cfg = SCENARIO[name]
                self.enter(name)
                try:
                    extra = self.step(name, cfg["kind"])
                finally:
                    self.leave(name)
                self.idle_s[name] += extra
                heapq.heappush(heap, (t + cfg["period"] * (0.9 + 0.2 * self.rng.random()) + extra, name))
            self.now = self.end
            return self.report()
        finally:
            time.time, time.monotonic, time.sleep = orig
            requests.request = orig_req
            wbuf.reset_buffers()
            wb.reset_budget()
            for k in ENV_KEYS:
                os.environ.pop(k, None)
            self.tmp.cleanup()

    def report(self) -> dict:
        from src.knowledge import write_buffers as wbuf
        from src.knowledge.write_budget import WriteBudget

        hours = (self.end - self.start) / 3600.0
        out = {"mode": self.mode, "hours": hours, "containers": {}, "crossed_100k_at_utc": None}
        if self.worker.crossed_100k_at:
            out["crossed_100k_at_utc"] = time.strftime("%H:%M", time.gmtime(self.worker.crossed_100k_at))
        for name in SCENARIO:
            os.environ.update({"D1_BUDGET_NAME": name, "WRITE_BUFFER_DIR": str(self.buffer_dir), "WRITE_BUFFERS": "1"})
            wbuf.reset_buffers()
            deferred = 0
            if self.mode == "budgeted":
                deferred = len(wbuf.get_discovery_spool()) + len(wbuf.get_linguistic_coalescer()) + len(wbuf.get_interpretation_outbox())
            rows = self.worker.rows[name]
            allowance = WriteBudget(name=name, daily_budget=self.budget).allowance() if self.mode == "budgeted" else None
            projected = rows / hours * 24.0
            if allowance is not None:
                projected = min(projected, float(allowance))  # the ledger stops the container at its allowance
            out["containers"][name] = {
                "rows": rows, "rows_per_day": projected, "requests": self.worker.requests[name],
                "rejected_by_worker": self.worker.rejected[name], "buffered_items_left": deferred,
                "allowance": allowance,
                "idle_s": self.idle_s[name],
            }
        out["total_rows"] = sum(c["rows"] for c in out["containers"].values())
        out["total_rows_per_day"] = sum(c["rows_per_day"] for c in out["containers"].values())
        return out


def simulate(mode: str, start: float, seconds: float, seed: int = 7, reports_rows: bool = True, budget: int = 70000) -> dict:
    logging.disable(logging.CRITICAL)  # loops print/log per POST; thousands of lines over a simulated day
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            return Sim(mode, start, seconds, seed, reports_rows, budget).run()
    finally:
        logging.disable(logging.NOTSET)


def render(short: dict, day: dict | None, budget: int) -> str:
    b, g = short["baseline"], short["budgeted"]
    lines = [f"Dry run (mock Worker, virtual clock, no network). D1 free cap 100,000 rows/day; shared budget {budget:,}/day.", "",
             f"A) {b['hours'] * 60:.0f} simulated minutes from 12:00 UTC  (rows written; /day = x 24 h / duration, budgeted capped at its allowance)",
             f"{'container':<19}{'baseline rows':>14}{'baseline /day':>15}{'budgeted rows':>15}{'budgeted /day':>15}{'allowance':>11}"]
    for n in SCENARIO:
        cb, cg = b["containers"][n], g["containers"][n]
        lines.append(f"{n:<19}{cb['rows']:>14,}{cb['rows_per_day']:>15,.0f}{cg['rows']:>15,}{cg['rows_per_day']:>15,.0f}{cg['allowance']:>11,}")
    lines.append(f"{'TOTAL':<19}{b['total_rows']:>14,}{b['total_rows_per_day']:>15,.0f}{g['total_rows']:>15,}{g['total_rows_per_day']:>15,.0f}")
    lines.append("  (10 minutes is startup-dominated: flush intervals are 2-15 min, so budgeted rows lag; section B is authoritative)")
    if day:
        db, dg = day["baseline"], day["budgeted"]
        lines += ["", "B) one full simulated UTC day, 00:00-24:00 (actual rows the mock Worker wrote)",
                  f"{'container':<19}{'baseline demand':>16}{'budgeted':>10}{'allowance':>11}{'% of allow.':>12}{'buffered left':>15}{'idle h':>8}"]
        for n in SCENARIO:
            cb, cg = db["containers"][n], dg["containers"][n]
            lines.append(f"{n:<19}{cb['rows']:>16,}{cg['rows']:>10,}{cg['allowance']:>11,}{100 * cg['rows'] / max(1, cg['allowance']):>12.0f}"
                         f"{cg['buffered_items_left']:>15,}{cg['idle_s'] / 3600:>8.1f}")
        lines.append(f"{'TOTAL':<19}{db['total_rows']:>16,}{dg['total_rows']:>10,}")
        cross = db["crossed_100k_at_utc"]
        lines.append(f"Baseline would cross the 100k free cap at {cross} UTC and then fail every write until 00:00 UTC." if cross
                     else "Baseline stays under 100k in this model.")
        lines.append(f"Budgeted: {dg['total_rows']:,} rows/day = {100 * dg['total_rows'] / D1_FREE_LIMIT:.0f}% of the free cap "
                     f"({'UNDER' if dg['total_rows'] <= budget else 'OVER'} the {budget:,} budget); Worker rejections: "
                     f"{sum(c['rejected_by_worker'] for c in dg['containers'].values())}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--minutes", type=float, default=10.0, help="short run length in simulated minutes (default 10)")
    ap.add_argument("--no-day", action="store_true", help="skip the simulated 24 h run")
    ap.add_argument("--budget", type=int, default=int(os.environ.get("D1_DAILY_WRITE_BUDGET") or 70000))
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--no-reports-rows", action="store_true", help="mock Worker does not report rows_written (pre-deploy)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    rr = not a.no_reports_rows
    short = {m: simulate(m, utc(12), a.minutes * 60, a.seed, rr, a.budget) for m in ("baseline", "budgeted")}
    day = None if a.no_day else {m: simulate(m, utc(0), 86400, a.seed, rr, a.budget) for m in ("baseline", "budgeted")}
    if a.json:
        print(json.dumps({"short": short, "day": day}, indent=2))
    else:
        print(render(short, day, a.budget))
    final = (day or short)["budgeted"]
    return 0 if final["total_rows"] <= a.budget else 1


if __name__ == "__main__":
    raise SystemExit(main())
