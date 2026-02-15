#!/usr/bin/env python3
"""
Backfill registry names: replace gibberish/inauthentic names with semantic ones.
Calls POST /api/registries/backfill-names on the API.
Cascades old→new name to prompts (learning_runs, interpretations, jobs) and sources_json.
For colors: uses RGB-driven semantic vocabulary (slate, ember, coral, etc.).
For other domains: uses semantic word invention.

Usage:
  py scripts/backfill_registry_names.py --api-base https://motion.productions
  py scripts/backfill_registry_names.py --dry-run  # preview only
  py scripts/backfill_registry_names.py --table learned_blends  # one table only (faster)

To recalculate depth percentages: python scripts/backfill_registry_depths.py
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.api_client import api_request_with_retry

TABLES = [
    "static_colors", "learned_colors", "learned_motion", "learned_blends",
    "learned_gradient", "learned_camera", "learned_lighting", "learned_composition",
    "learned_graphics", "learned_temporal", "learned_technical", "learned_audio_semantic",
    "learned_time", "learned_transition", "learned_depth", "static_sound", "narrative_entries",
]


def main() -> None:
    p = argparse.ArgumentParser(description="Backfill gibberish registry names with semantic ones")
    p.add_argument("--api-base", default=os.environ.get("API_BASE", "https://motion.productions"))
    p.add_argument("--dry-run", action="store_true", help="Preview only; no updates")
    p.add_argument("--limit", type=int, default=20, help="Max rows per request (default 20)")
    p.add_argument("--table", help="Process only this table (faster; use for large registries)")
    args = p.parse_args()
    base = args.api_base.rstrip("/")
    tables = [args.table] if args.table else TABLES
    if args.table and args.table not in TABLES:
        print(f"Unknown table: {args.table}. Valid: {', '.join(TABLES)}")
        sys.exit(1)
    try:
        grand_total = 0
        for tbl in tables:
            total = 0
            while True:
                qs = [f"limit={min(args.limit, 200)}", f"table={tbl}"]
                if args.dry_run:
                    qs.append("dry_run=1")
                path = "/api/registries/backfill-names?" + "&".join(qs)
                r = api_request_with_retry(base, "POST", path, data={}, timeout=60)
                updated = r.get("updated", 0)
                total += updated
                grand_total += updated
                if updated > 0:
                    print(f"  {tbl}: {updated} updated")
                if updated == 0 or args.dry_run:
                    break
            if total > 0 and not args.dry_run:
                print(f"  {tbl}: {total} total")
        print(f"Total: {grand_total} names {'would be ' if args.dry_run else ''}updated")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
