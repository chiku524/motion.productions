#!/usr/bin/env python3
"""
Accelerate static color coverage by registering a grid of (r,g,b[,opacity]) cells
without the full prompt→render pipeline. Optionally POSTs novel discoveries to the API.

Usage:
  python scripts/color_sweep.py --api-base https://motion.productions
  python scripts/color_sweep.py --steps 11 --opacity-steps 5 --limit 400 --api-base https://motion.productions
  python scripts/color_sweep.py --steps 6 --dry-run
"""
from __future__ import annotations

import argparse
import sys
import time

from src.config import load_config
from src.knowledge.growth_per_instance import ensure_static_color_in_registry, ensure_static_primitives_seeded
from src.knowledge.remote_sync import DISCOVERIES_MAX_ITEMS, post_static_discoveries


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Register a grid of RGB(+opacity) colors in the static registry."
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
        help="Steps per RGB channel (6 → 216 opaque cells; 11 matches quantized cell space). Default 6.",
    )
    parser.add_argument(
        "--opacity-steps",
        type=int,
        default=1,
        help="Opacity tiers from 0..1 inclusive (1 = opaque only; 5 → 0,0.25,0.5,0.75,1). Default 1.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max number of cells to process (default: all in grid)",
    )
    parser.add_argument(
        "--post-chunk-pause",
        type=float,
        default=1.0,
        help="Seconds between discovery POST chunks (default 1.0).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print grid size and first few cells; do not register or POST",
    )
    args = parser.parse_args()

    step = max(1, min(256, args.steps))
    if step == 1:
        values = [0, 255]
    else:
        values = sorted(set(min(255, int(round(i * 255 / (step - 1)))) for i in range(step)))

    op_steps = max(1, min(21, args.opacity_steps))
    if op_steps == 1:
        opacities = [1.0]
    else:
        opacities = [round(i / (op_steps - 1), 4) for i in range(op_steps)]

    grid = [(r, g, b, op) for op in opacities for r in values for g in values for b in values]
    if args.limit is not None:
        grid = grid[: args.limit]
    total = len(grid)

    if args.dry_run:
        print(f"Would process {total} cells (steps={step}, opacity_steps={op_steps})")
        print(f"  rgb values={values[:8]}{'...' if len(values) > 8 else ''}")
        print(f"  opacities={opacities}")
        for cell in grid[:5]:
            print(f"  {cell}")
        return 0

    config = load_config()
    ensure_static_primitives_seeded(config)
    novel: list[dict] = []
    added = 0
    for i, (r, g, b, opacity) in enumerate(grid):
        color = {"r": r, "g": g, "b": b, "opacity": opacity}
        if ensure_static_color_in_registry(color, config=config, out_novel=novel):
            added += 1
        if (i + 1) % 100 == 0:
            print(f"  ... {i + 1}/{total} (added so far: {added})")

    print(f"Color sweep: {added} new cells added to local registry (total processed: {total}).")
    if novel and args.api_base:
        api_base = args.api_base.rstrip("/")
        posted = 0
        chunk = max(1, DISCOVERIES_MAX_ITEMS)
        pause = max(0.0, float(args.post_chunk_pause))
        for i in range(0, len(novel), chunk):
            batch = novel[i : i + chunk]
            try:
                post_static_discoveries(api_base, batch, [], job_id=None)
                posted += len(batch)
                print(f"  posted {posted}/{len(novel)}")
            except Exception as e:
                print(f"Warning: POST discoveries failed at {posted}: {e}", file=sys.stderr)
                time.sleep(max(pause, 3.0))
                try:
                    post_static_discoveries(api_base, batch, [], job_id=None)
                    posted += len(batch)
                    print(f"  posted {posted}/{len(novel)} (retry ok)")
                except Exception as e2:
                    print(f"Warning: retry failed: {e2}", file=sys.stderr)
                    break
            if pause and i + chunk < len(novel):
                time.sleep(pause)
        print(f"Posted {posted} novel static colors to {api_base}")
    elif novel and not args.api_base:
        print(f"Run with --api-base to POST {len(novel)} novel discoveries to the API.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
