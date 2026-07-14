#!/usr/bin/env python3
"""
Wipe D1 registry tables only (keep jobs, R2 videos, learning_runs, events, feedback).

Deletes in batches to reduce D1 CPU 7429 errors. See docs/REGISTRY_RESET.md.

Usage:
  python scripts/wipe_registry_tables.py --remote --dry-run
  python scripts/wipe_registry_tables.py --remote --yes
  python scripts/wipe_registry_tables.py --local --yes
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CLOUDFLARE_DIR = REPO_ROOT / "cloudflare"
DB_NAME = "motion-productions-db"

# Registry / naming tables only — never jobs / R2 / operational UX tables
REGISTRY_TABLES = [
    "static_colors",
    "static_sound",
    "narrative_entries",
    "learned_blends",
    "learned_colors",
    "learned_motion",
    "learned_lighting",
    "learned_composition",
    "learned_graphics",
    "learned_temporal",
    "learned_technical",
    "learned_audio_semantic",
    "learned_time",
    "learned_gradient",
    "learned_camera",
    "learned_transition",
    "learned_depth",
    "learned_entities",
    "learned_dynamic_meta",
    "interpretations",
    "linguistic_registry",
    "name_reserve",
    "discovery_runs",
]


def _run(cmd: list[str], capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=CLOUDFLARE_DIR,
        shell=sys.platform == "win32",
        capture_output=capture,
        text=True,
    )


def _execute(target: str, sql: str) -> tuple[bool, str]:
    result = _run(
        ["npx", "wrangler", "d1", "execute", DB_NAME, target, "--command", sql, "--json"],
        capture=True,
    )
    out = (result.stdout or "") + (result.stderr or "")
    return result.returncode == 0, out.strip()


def _count(target: str, table: str) -> int | None:
    ok, out = _execute(target, f"SELECT count(*) AS n FROM {table}")
    if not ok:
        return None
    try:
        data = json.loads(out)
        # wrangler json shapes vary
        if isinstance(data, list) and data:
            results = data[0].get("results") or data[0].get("result") or []
            if results and isinstance(results[0], dict):
                return int(results[0].get("n") or results[0].get("COUNT(*)") or 0)
        if isinstance(data, dict):
            results = data.get("results") or []
            if results:
                return int(results[0].get("n") or 0)
    except (json.JSONDecodeError, TypeError, ValueError, KeyError, IndexError):
        pass
    return None


def _delete_all(target: str, table: str, batch: int, delay: float) -> int:
    """DELETE in batches. Returns approximate rows deleted."""
    deleted = 0
    while True:
        # SQLite/D1: delete a batch of rowids
        sql = f"DELETE FROM {table} WHERE rowid IN (SELECT rowid FROM {table} LIMIT {batch})"
        ok, out = _execute(target, sql)
        if not ok:
            if "no such table" in out.lower():
                print(f"  skip {table} (missing)")
                return deleted
            print(f"  WARN {table}: {out[:200]}", file=sys.stderr)
            # fallback: try wipe whole table once
            ok2, out2 = _execute(target, f"DELETE FROM {table}")
            if ok2:
                print(f"  wiped {table} (full DELETE)")
            else:
                print(f"  FAIL {table}: {out2[:300]}", file=sys.stderr)
            return deleted
        # Heuristic: if COUNT is 0, stop
        n = _count(target, table)
        deleted += batch
        print(f"  {table}: batch delete… remaining≈{n}")
        if n is None:
            # can't count — one more full delete then stop
            _execute(target, f"DELETE FROM {table}")
            break
        if n <= 0:
            break
        time.sleep(delay)
    return deleted


def main() -> int:
    parser = argparse.ArgumentParser(description="Wipe D1 registry tables (not jobs/videos).")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--remote", action="store_true", help="Production D1")
    target.add_argument("--local", action="store_true", help="Local wrangler D1")
    parser.add_argument("--dry-run", action="store_true", help="Print counts only")
    parser.add_argument("--yes", action="store_true", help="Confirm destructive wipe")
    parser.add_argument("--batch", type=int, default=2000, help="DELETE batch size")
    parser.add_argument("--delay", type=float, default=2.0, help="Seconds between batches")
    args = parser.parse_args()

    flag = "--remote" if args.remote else "--local"
    print(f"Target: D1 {DB_NAME} ({flag})")
    print("Tables:", ", ".join(REGISTRY_TABLES))

    if args.dry_run or not args.yes:
        for table in REGISTRY_TABLES:
            n = _count(flag, table)
            print(f"  {table}: {n if n is not None else '?'}")
        if not args.yes:
            print("\nDry-run / counts only. Re-run with --yes to wipe.")
            return 0

    print("\nWiping registry tables…")
    for table in REGISTRY_TABLES:
        _delete_all(flag, table, batch=max(100, args.batch), delay=max(0.5, args.delay))
    print("Done. Next: python scripts/seed_registries_d1.py --api-base https://motion.productions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
