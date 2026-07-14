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


def _log(msg: str, *, err: bool = False) -> None:
    stream = sys.stderr if err else sys.stdout
    print(msg, file=stream, flush=True)


def _run(cmd: list[str], capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=CLOUDFLARE_DIR,
        shell=sys.platform == "win32",
        capture_output=capture,
        text=True,
    )


def _execute(target: str, sql: str) -> tuple[bool, str, dict | None]:
    result = _run(
        ["npx", "wrangler", "d1", "execute", DB_NAME, target, "--command", sql, "--json"],
        capture=True,
    )
    out = (result.stdout or "") + (result.stderr or "")
    meta = None
    try:
        data = json.loads(result.stdout or "")
        if isinstance(data, list) and data:
            meta = data[0].get("meta") if isinstance(data[0], dict) else None
        elif isinstance(data, dict):
            meta = data.get("meta")
    except (json.JSONDecodeError, TypeError, AttributeError):
        pass
    return result.returncode == 0, out.strip(), meta if isinstance(meta, dict) else None


def _count(target: str, table: str) -> int | None:
    ok, out, _meta = _execute(target, f"SELECT count(*) AS n FROM {table}")
    if not ok:
        return None
    try:
        data = json.loads(out.split("\n")[0] if out.startswith("{") else out)
        # wrangler may prepend non-json; prefer stdout-only parse via re-execute path
        if not isinstance(data, (list, dict)):
            data = json.loads(out[out.find("[") :])
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
    """DELETE in batches using meta.changes (avoids expensive COUNT on huge tables)."""
    deleted = 0
    empty_streak = 0
    while True:
        _log(f"  {table}: deleting up to {batch}...")
        sql = f"DELETE FROM {table} WHERE rowid IN (SELECT rowid FROM {table} LIMIT {batch})"
        ok, out, meta = _execute(target, sql)
        if not ok:
            if "no such table" in out.lower():
                _log(f"  skip {table} (missing)")
                return deleted
            _log(f"  WARN {table}: {out[:200]}", err=True)
            ok2, out2, meta2 = _execute(target, f"DELETE FROM {table}")
            if ok2:
                ch = int((meta2 or {}).get("changes") or 0)
                _log(f"  wiped {table} (full DELETE, changes={ch})")
                deleted += ch
            else:
                _log(f"  FAIL {table}: {out2[:300]}", err=True)
            return deleted

        changes = int((meta or {}).get("changes") or 0)
        deleted += changes
        _log(f"  {table}: deleted {changes} (total~={deleted})")
        if changes <= 0:
            empty_streak += 1
            if empty_streak >= 1:
                break
        else:
            empty_streak = 0
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
    parser.add_argument(
        "--only",
        nargs="+",
        default=None,
        help="Optional subset of table names to wipe",
    )
    args = parser.parse_args()

    flag = "--remote" if args.remote else "--local"
    tables = REGISTRY_TABLES
    if args.only:
        unknown = [t for t in args.only if t not in REGISTRY_TABLES]
        if unknown:
            _log(f"Unknown tables: {unknown}", err=True)
            return 1
        tables = list(args.only)

    _log(f"Target: D1 {DB_NAME} ({flag})")
    _log("Tables: " + ", ".join(tables))

    if args.dry_run or not args.yes:
        for table in tables:
            n = _count(flag, table)
            _log(f"  {table}: {n if n is not None else '?'}")
        if not args.yes:
            _log("\nDry-run / counts only. Re-run with --yes to wipe.")
            return 0

    _log("\nWiping registry tables...")
    for table in tables:
        _delete_all(flag, table, batch=max(100, args.batch), delay=max(0.5, args.delay))
    _log("Done. Next: python scripts/seed_registries_d1.py --api-base https://motion.productions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
