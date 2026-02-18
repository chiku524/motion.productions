#!/usr/bin/env python3
"""
Backfill registry depths: recalculate depth_breakdown using Python blend_depth logic.
Fetches raw rows from API, recomputes depths (towards primitives), POSTs updates.
Use after depth calculation logic changes to refresh stored values.

Usage:
  python scripts/backfill_registry_depths.py --api-base https://motion.productions
  python scripts/backfill_registry_depths.py --table learned_colors --limit 30
  python scripts/backfill_registry_depths.py --table learned_motion --limit 30
  python scripts/backfill_registry_depths.py --dry-run

If you get 400 Bad Request for table=learned_colors, deploy the Cloudflare Worker
first (push to main or run deploy workflow) so the API includes learned_colors support.
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.api_client import api_request_with_retry
from src.knowledge.blend_depth import (
    compute_color_depth,
    compute_motion_depth,
    compute_lighting_depth,
)

TABLES = ["static_colors", "learned_colors", "learned_motion", "learned_lighting"]


def main() -> None:
    p = argparse.ArgumentParser(description="Backfill depth_breakdown using Python blend_depth")
    p.add_argument("--api-base", default=os.environ.get("API_BASE", "https://motion.productions"))
    p.add_argument("--dry-run", action="store_true", help="Preview only; no updates")
    p.add_argument("--limit", type=int, default=50, help="Max rows per table (default 50)")
    p.add_argument("--table", help="Process only this table")
    args = p.parse_args()
    base = args.api_base.rstrip("/")
    tables = [args.table] if args.table else TABLES
    if args.table and args.table not in TABLES:
        print(f"Unknown table: {args.table}. Valid: {', '.join(TABLES)}")
        sys.exit(1)

    def to_pct(d: dict[str, float]) -> dict[str, float]:
        """Convert 0-1 weights to 0-100 for storage (matches UI expectation)."""
        return {k: round(v * 100) if v <= 1 else round(v) for k, v in d.items()}

    grand_total = 0
    for tbl in tables:
        try:
            r = api_request_with_retry(
                base, "GET", f"/api/registries/backfill-rows?table={tbl}&limit={args.limit}", timeout=30
            )
            rows = r.get("rows") or []
        except Exception as e:
            print(f"  {tbl}: fetch failed — {e}")
            if "400" in str(e) and tbl == "learned_colors":
                print("  Hint: deploy the Cloudflare Worker (push to main or Actions → Deploy) so backfill-rows accepts learned_colors.")
            continue
        updates = []
        for row in rows:
            rid = row.get("id")
            if not rid:
                continue
            depth: dict[str, float] = {}
            if tbl == "static_colors":
                depth = compute_color_depth(
                    float(row.get("r", 0)), float(row.get("g", 0)), float(row.get("b", 0))
                )
            elif tbl == "learned_colors":
                depth = compute_color_depth(
                    float(row.get("r", 0)), float(row.get("g", 0)), float(row.get("b", 0))
                )
            elif tbl == "learned_motion":
                depth = compute_motion_depth(
                    float(row.get("motion_level", 0)), str(row.get("motion_trend", "steady"))
                )
            elif tbl == "learned_lighting":
                depth = compute_lighting_depth(
                    float(row.get("brightness", 128)),
                    float(row.get("contrast", 50)),
                    float(row.get("saturation", 1.0)),
                )
            if depth:
                updates.append({"table": tbl, "id": rid, "depth_breakdown": to_pct(depth)})
        if not updates:
            continue
        try:
            qs = "dry_run=1" if args.dry_run else ""
            path = "/api/registries/backfill-depths" + ("?" + qs if qs else "")
            resp = api_request_with_retry(base, "POST", path, data={"updates": updates}, timeout=60)
            count = resp.get("updated", 0)
            grand_total += count
            print(f"  {tbl}: {count} depth_breakdown updated")
        except Exception as e:
            print(f"  {tbl}: POST failed — {e}")
    print(f"Total: {grand_total} depth_breakdown {'would be ' if args.dry_run else ''}updated")


if __name__ == "__main__":
    main()
