#!/usr/bin/env python3
"""Batched retire of stale pending LOOP jobs (cloudflare/migrations_pending/0103_retire_stale_pending_jobs.sql).

Docker replacement for C:\\Users\\chiku\\d1-audit\\run-0103-batch.ps1 (Windows tasks motion-0103-retire /
motion-0103-retire-2). status -> 'abandoned'; nothing is deleted. Same guards, checked before EVERY batch:

  * at most RETIRE_MAX_BATCHES (2) batches and RETIRE_DAILY_CAP (10,000) writes per UTC day (state file);
  * loops' projected UTC-day writes (shared ledger, capped at D1_DAILY_WRITE_BUDGET 50k) + 20k reserve + today's
    0103 writes + one batch (4,500) must stay <= 95,000;
  * a D1 Time Travel bookmark is fetched and logged before each batch (no bookmark -> no batch: fail closed);
  * a batch that changes 0 rows marks the job done forever (state file), after which it is a no-op.

Talks to the Cloudflare D1 REST API (no wrangler in the image). Needs CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_API_TOKEN
(D1 edit scope) and D1_DATABASE_ID in the environment; missing -> exits without doing anything. Never prints secrets.

  python scripts/retire_stale_jobs.py            # one guarded batch (like one Windows task run)
  python scripts/retire_stale_jobs.py --loop     # service: one guarded batch at each RETIRE_RUN_HOURS_UTC (00:30, 12:30)
  python scripts/retire_stale_jobs.py --dry-run  # guards only
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
SQL_FILE = ROOT / "cloudflare" / "migrations_pending" / "0103_retire_stale_pending_jobs.sql"
BATCH_WRITES = 4500
GLOBAL_CEILING = 95_000
RESERVE = 20_000


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name) or default)
    except ValueError:
        return default


def knowledge_dir() -> Path:
    return Path(os.environ.get("KNOWLEDGE_DIR") or (ROOT / "knowledge"))


def state_path() -> Path:
    return knowledge_dir() / "write_budget" / "0103-state.json"


def log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} {msg}"
    print(line, flush=True)
    try:
        p = knowledge_dir() / "write_budget" / "0103-batches.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def load_state(p: Path) -> dict:
    try:
        d = json.loads(p.read_text(encoding="utf-8-sig"))
        if isinstance(d, dict):
            return d
    except (OSError, ValueError):
        pass
    return {"day": "", "batches": 0, "writes": 0, "done": False, "total_rows": 0}


def save_state(p: Path, st: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def loops_projected(now: datetime, ledger: Path, cap: int) -> tuple[int, int]:
    """(used today, projected for the whole UTC day capped at the loops' budget); unreadable ledger -> cap (fail closed)."""
    today = now.strftime("%Y-%m-%d")
    try:
        d = json.loads(ledger.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return 0, 0
    except (OSError, ValueError):
        return -1, cap
    used = 0
    if d.get("day") == today:
        for c in (d.get("containers") or {}).values():
            used += int((c or {}).get("used") or 0)
    hours = (now - now.replace(hour=0, minute=0, second=0, microsecond=0)).total_seconds() / 3600
    frac = max(hours / 24.0, 0.25)
    return used, min(int(used / frac), cap)


def guard(st: dict, now: datetime, ledger: Path) -> tuple[bool, str, dict]:
    today = now.strftime("%Y-%m-%d")
    if st.get("done"):
        return False, "done already (a batch changed 0 rows); nothing to do", st
    if st.get("day") != today:
        st.update(day=today, batches=0, writes=0)
    max_b, cap = _int_env("RETIRE_MAX_BATCHES", 2), _int_env("RETIRE_DAILY_CAP", 10_000)
    if st["batches"] >= max_b or st["writes"] + BATCH_WRITES > cap:
        return False, f"skip: daily 0103 allowance used ({st['batches']} batches, {st['writes']} writes)", st
    loops_cap = _int_env("D1_DAILY_WRITE_BUDGET", 50_000)
    used, projected = loops_projected(now, ledger, loops_cap)
    if projected + RESERVE + st["writes"] + BATCH_WRITES > GLOBAL_CEILING:
        return False, f"skip: loops projected {projected}/day leaves no headroom", st
    return True, f"ok (loops used={used} projected={projected})", st


class D1Rest:
    def __init__(self, account: str, token: str, db: str):
        self.base = f"https://api.cloudflare.com/client/v4/accounts/{account}/d1/database/{db}"
        self._token = token

    def _req(self, method: str, path: str, body: Any = None) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(self.base + path, data=data, method=method,
                                   headers={"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"})
        with urllib.request.urlopen(r, timeout=120) as resp:
            out = json.loads(resp.read().decode())
        if not out.get("success"):
            raise RuntimeError(f"D1 API error: {str(out.get('errors'))[:200]}")
        return out["result"]

    def bookmark(self) -> str:
        return str(self._req("GET", "/time_travel/bookmark").get("bookmark") or "")

    def execute(self, sql: str) -> dict:
        res = self._req("POST", "/query", {"sql": sql})
        return (res[0] if isinstance(res, list) else res).get("meta") or {}


def sql_statement() -> str:
    text = SQL_FILE.read_text(encoding="utf-8")
    return "\n".join(ln for ln in text.splitlines() if not ln.strip().startswith("--")).strip()


def run_once(client: Any, *, now: datetime | None = None, dry_run: bool = False,
             ledger: Path | None = None, sp: Path | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    sp = sp or state_path()
    ledger = ledger or knowledge_dir() / "write_budget" / "ledger.json"
    st = load_state(sp)
    ok, why, st = guard(st, now, ledger)
    if not ok or dry_run:
        log(why if not ok else f"dry-run: would run a batch; {why}")
        save_state(sp, st)
        return "skipped" if not ok else "dry_run"
    try:
        bm = client.bookmark()
        if not bm:
            raise RuntimeError("empty bookmark")
        log(f"bookmark before batch: {bm}")
        meta = client.execute(sql_statement())
    except Exception as e:
        log(f"error: {str(e)[:200]}")
        save_state(sp, st)
        return "error"
    changes, written = int(meta.get("changes") or 0), int(meta.get("rows_written") or 0)
    st["batches"] += 1
    st["writes"] += max(written, changes * 3)
    st["total_rows"] = int(st.get("total_rows") or 0) + changes
    log(f"batch ok: changes={changes} rows_written={written} rows_read={meta.get('rows_read')} {why} total_retired={st['total_rows']}")
    if changes == 0:
        st["done"] = True
        log("backlog cleared; job is done (service may be removed)")
    save_state(sp, st)
    return "done" if changes == 0 else "batch"


def client_from_env() -> D1Rest | None:
    a, t, d = (os.environ.get(k, "").strip() for k in ("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN", "D1_DATABASE_ID"))
    return D1Rest(a, t, d) if a and t and d else None


def next_run(now: datetime, hours: list[tuple[int, int]]) -> float:
    best = None
    for h, m in hours:
        cand = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if cand <= now:
            cand = cand.fromtimestamp(cand.timestamp() + 86400, timezone.utc)
        if best is None or cand < best:
            best = cand
    return (best - now).total_seconds()


def parse_hours(s: str) -> list[tuple[int, int]]:
    out = []
    for part in s.split(","):
        h, _, m = part.strip().partition(":")
        out.append((int(h), int(m or 0)))
    return out


def main(argv: list[str] | None = None, sleep: Callable[[float], None] = time.sleep) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    if os.environ.get("RETIRE_0103_ENABLED", "") not in ("1", "true", "yes"):
        log("RETIRE_0103_ENABLED is not set; exiting without doing anything")
        return 0
    client = client_from_env()
    if client is None and not args.dry_run:
        log("missing CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN / D1_DATABASE_ID; exiting")
        return 1
    if not args.loop:
        return 0 if run_once(client, dry_run=args.dry_run) != "error" else 1
    hours = parse_hours(os.environ.get("RETIRE_RUN_HOURS_UTC", "00:30,12:30"))
    while True:
        wait = next_run(datetime.now(timezone.utc), hours)
        log(f"next batch window in {int(wait)} s")
        sleep(wait)
        if run_once(client, dry_run=args.dry_run) == "done" or load_state(state_path()).get("done"):
            log("0103 complete; idling")
            while True:
                sleep(86400)


if __name__ == "__main__":
    sys.exit(main())
