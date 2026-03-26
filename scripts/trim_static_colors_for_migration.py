#!/usr/bin/env python3
"""
Trim static_colors so D1 migrations (e.g. ADD COLUMN) can run under the CPU limit.
Deletes oldest rows in batches. Run from repo root.

Usage:
  python scripts/trim_static_colors_for_migration.py --remote --dry-run   # show row count only
  python scripts/trim_static_colors_for_migration.py --remote --keep 50000 # keep newest 50k rows
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CLOUDFLARE_DIR = REPO_ROOT / "cloudflare"
DB_NAME = "motion-productions-db"


def _run(cmd: list[str], capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=CLOUDFLARE_DIR,
        shell=sys.platform == "win32",
        capture_output=capture,
        text=capture,
    )


def _get_count(target: str) -> int | None:
    result = _run(
        [
            "npx", "wrangler", "d1", "execute", DB_NAME, target,
            "--command", "SELECT count(*) AS n FROM static_colors",
            "--json",
        ],
        capture=True,
    )
    out = (result.stdout or result.stderr or "").strip()
    if result.returncode != 0:
        # D1 often returns error as JSON in stdout
        try:
            err = json.loads(out)
            if isinstance(err, dict) and err.get("error", {}).get("code") == 7429:
                print(
                    "D1 CPU limit (7429): even COUNT(*) on static_colors exceeded the limit.",
                    file=sys.stderr,
                )
                print(
                    "The table is very large. Trim from Cloudflare Dashboard → D1 → your DB → Console:",
                    file=sys.stderr,
                )
                print(
                    "  DELETE FROM static_colors WHERE id IN (SELECT id FROM static_colors ORDER BY created_at ASC LIMIT 5000);",
                    file=sys.stderr,
                )
                print("Run that repeatedly until the table is smaller, then re-run this script or migrations.", file=sys.stderr)
            else:
                print(out, file=sys.stderr)
        except json.JSONDecodeError:
            print(out or "Command failed.", file=sys.stderr)
        return None
    if not out:
        return None
    # Wrangler --json returns array of { results: [ { n: 123 } ], success, meta } or single object
    for blob in (out, *out.splitlines()):
        blob = blob.strip()
        if not blob or blob[0] not in "[{":
            continue
        try:
            data = json.loads(blob)
            if isinstance(data, list) and data:
                data = data[0]
            results = (data or {}).get("results") if isinstance(data, dict) else None
            if isinstance(results, list) and results:
                row = results[0]
                # Column may be "n" (AS n) or "count(*)" depending on driver
                n = row.get("n") if isinstance(row, dict) else None
                if n is None and isinstance(row, dict):
                    n = row.get("count(*)")
                if n is not None:
                    return int(n)
        except (json.JSONDecodeError, TypeError, KeyError, ValueError):
            continue
    return None


def _delete_batch(target: str, batch_size: int) -> bool:
    # Delete oldest rows by created_at so we keep the newest.
    sql = (
        "DELETE FROM static_colors WHERE id IN ("
        "SELECT id FROM static_colors ORDER BY created_at ASC LIMIT " + str(batch_size) + ")"
    )
    result = _run(
        [
            "npx", "wrangler", "d1", "execute", DB_NAME, target,
            "--command", sql,
        ],
    )
    return result.returncode == 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Trim static_colors so D1 ALTER TABLE can run under CPU limit."
    )
    parser.add_argument("--local", action="store_true", help="Use local D1.")
    parser.add_argument("--remote", action="store_true", help="Use remote D1 (default).")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print current row count and exit.",
    )
    parser.add_argument(
        "--keep",
        type=int,
        metavar="N",
        default=0,
        help="Keep the newest N rows; delete older rows in batches.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=5000,
        help="Rows to delete per batch (default 5000).",
    )
    args = parser.parse_args()

    if not (CLOUDFLARE_DIR / "wrangler.jsonc").exists():
        print("Error: cloudflare/wrangler.jsonc not found. Run from repo root.", file=sys.stderr)
        sys.exit(1)

    target = "--local" if args.local else "--remote"

    count = _get_count(target)
    if count is None:
        print("Failed to get row count from static_colors.", file=sys.stderr)
        sys.exit(1)
    print(f"static_colors row count: {count}")

    if args.dry_run:
        if count > 100_000:
            print("Table is large. Run with --keep N (e.g. --keep 50000) to trim before migrating.")
        return

    if args.keep <= 0:
        print("Use --keep N to trim (e.g. --keep 50000).", file=sys.stderr)
        sys.exit(1)

    if count <= args.keep:
        print("Already at or below --keep; nothing to delete.")
        return

    batch_size = max(1, min(args.batch_size, 10000))
    total_deleted = 0
    while True:
        current = _get_count(target)
        if current is None:
            print("Failed to get count.", file=sys.stderr)
            sys.exit(1)
        if current <= args.keep:
            break
        to_delete = min(batch_size, current - args.keep)
        if not _delete_batch(target, to_delete):
            print("Delete failed.", file=sys.stderr)
            sys.exit(1)
        total_deleted += to_delete
        print(f"Deleted {to_delete} rows (total deleted this run: {total_deleted})")
        time.sleep(2)

    print(f"Done. Total rows deleted: {total_deleted}. Re-run migrations when ready.")


if __name__ == "__main__":
    main()
