#!/usr/bin/env python3
"""
Backfill registry names: replace gibberish names with semantic ones.
Calls POST /api/registries/backfill-names on the API.

Usage:
  py scripts/backfill_registry_names.py --api-base https://motion.productions
  py scripts/backfill_registry_names.py --dry-run  # preview only
"""
import argparse
import os
import sys

ROOT = __file__.resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.api_client import api_request_with_retry


def main() -> None:
    p = argparse.ArgumentParser(description="Backfill gibberish registry names with semantic ones")
    p.add_argument("--api-base", default=os.environ.get("API_BASE", "https://motion.productions"))
    p.add_argument("--dry-run", action="store_true", help="Preview only; no updates")
    args = p.parse_args()
    base = args.api_base.rstrip("/")
    path = "/api/registries/backfill-names" + ("?dry_run=1" if args.dry_run else "")
    try:
        r = api_request_with_retry(base, "POST", path, data={}, timeout=120)
        updated = r.get("updated", 0)
        print(f"Backfill complete: {updated} names {'would be ' if args.dry_run else ''}updated")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
