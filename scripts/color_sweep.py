#!/usr/bin/env python3
"""
Manus AI Priority 5: accelerate static color coverage by registering a grid of (r,g,b) cells
without running the full prompt→interpret→render pipeline. Fills the static color registry
and optionally POSTs novel discoveries to the API.

Usage:
  python scripts/color_sweep.py --api-base https://motion.productions
  python scripts/color_sweep.py --steps 6 --dry-run   # preview cell count
"""
from __future__ import annotations

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Register a grid of RGB colors in the static registry (Manus AI color coverage)."
    )
    parser.add_argument(
        "--api-base",
        default=None,
        help="If set, POST novel discoveries to /api/knowledge/discoveries",
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=6,
        help="Number of steps per channel (e.g. 6 → 0,51,102,153,204,255 → 216 cells). Default 6.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max number of cells to process (default: all in grid)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print grid size and first few (r,g,b); do not register or POST",
    )
    args = parser.parse_args()

    step = max(1, min(256, args.steps))
    if step == 1:
        values = [0, 255]
    else:
        values = [int(round(i * 255 / (step - 1))) for i in range(step)]
        values = sorted(set(min(255, v) for v in values))
    grid = [(r, g, b) for r in values for g in values for b in values]
    if args.limit is not None:
        grid = grid[: args.limit]
    total = len(grid)

    if args.dry_run:
        print(f"Would process {total} cells (steps={step}, values={values[:5]}...)")
        for (r, g, b) in grid[:5]:
            print(f"  ({r}, {g}, {b})")
        return 0

    try:
        from src.config import load_config
        from src.knowledge.growth_per_instance import ensure_static_primitives_seeded, ensure_static_color_in_registry
        from src.knowledge.remote_sync import post_static_discoveries
    except ImportError:
        sys.path.insert(0, ".")
        from src.config import load_config
        from src.knowledge.growth_per_instance import ensure_static_primitives_seeded, ensure_static_color_in_registry
        from src.knowledge.remote_sync import post_static_discoveries

    config = load_config()
    ensure_static_primitives_seeded(config)
    novel: list[dict] = []
    added = 0
    for i, (r, g, b) in enumerate(grid):
        color = {"r": r, "g": g, "b": b, "opacity": 1.0}
        if ensure_static_color_in_registry(color, config=config, out_novel=novel):
            added += 1
        if (i + 1) % 100 == 0:
            print(f"  ... {i + 1}/{total} (added so far: {added})")

    print(f"Color sweep: {added} new cells added to local registry (total processed: {total}).")
    if novel and args.api_base:
        api_base = args.api_base.rstrip("/")
        try:
            from src.api_client import api_request_with_retry
            post_static_discoveries(api_base, novel, [], job_id=None)
            print(f"Posted {len(novel)} novel static colors to {api_base}")
        except Exception as e:
            print(f"Warning: POST discoveries failed: {e}", file=sys.stderr)
    elif novel and not args.api_base:
        print(f"Run with --api-base to POST {len(novel)} novel discoveries to the API.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
