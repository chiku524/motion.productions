#!/usr/bin/env python3
"""
Bootstrap registries with all primitives and optional color sweep.

Run after clone or before deploy so local (and optionally remote) registries
have the full primitive set. Safe to run repeatedly (idempotent seeding).

Usage:
  python scripts/registry_bootstrap.py
  python scripts/registry_bootstrap.py --color-sweep
  python scripts/registry_bootstrap.py --api-base https://motion.productions --color-sweep
"""
from __future__ import annotations

import argparse
import sys

from src.config import load_config
from src.knowledge.growth_per_instance import (
    ensure_dynamic_primitives_seeded,
    ensure_static_color_in_registry,
    ensure_static_primitives_seeded,
)
from src.knowledge.remote_sync import post_static_discoveries


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Seed static + dynamic primitives and optionally run color sweep."
    )
    parser.add_argument(
        "--api-base",
        default=None,
        help="API base URL (e.g. https://motion.productions). If set with --color-sweep, novel colors are POSTed.",
    )
    parser.add_argument(
        "--color-sweep",
        action="store_true",
        help="Run color_sweep after seeding (grid of RGB cells to raise static color coverage).",
    )
    parser.add_argument(
        "--sweep-steps",
        type=int,
        default=6,
        help="Color sweep steps per channel (default 6 → 216 cells).",
    )
    parser.add_argument(
        "--sweep-limit",
        type=int,
        default=None,
        help="Max color sweep cells to process (default: all).",
    )
    args = parser.parse_args()

    config = load_config()
    print("Seeding static primitives (color + sound)...")
    ensure_static_primitives_seeded(config)
    print("Seeding dynamic primitives (gradient, camera, motion, lighting, composition, time, temporal, technical, depth, transition, audio_semantic)...")
    ensure_dynamic_primitives_seeded(config)
    print("Registry bootstrap: all primitives seeded.")

    if args.color_sweep:
        print("Running color sweep...")
        step = max(1, min(256, args.sweep_steps))
        if step == 1:
            values = [0, 255]
        else:
            values = sorted(set(min(255, int(round(i * 255 / (step - 1)))) for i in range(step)))
        grid = [(r, g, b) for r in values for g in values for b in values]
        if args.sweep_limit is not None:
            grid = grid[: args.sweep_limit]
        total = len(grid)
        novel: list[dict] = []
        added = 0
        for i, (r, g, b) in enumerate(grid):
            color = {"r": r, "g": g, "b": b, "opacity": 1.0}
            if ensure_static_color_in_registry(color, config=config, out_novel=novel):
                added += 1
            if (i + 1) % 100 == 0:
                print(f"  ... {i + 1}/{total} (added: {added})")
        print(f"Color sweep: {added} new cells (total processed: {total}).")
        if novel and args.api_base:
            api_base = args.api_base.rstrip("/")
            try:
                post_static_discoveries(api_base, novel, [], job_id=None)
                print(f"Posted {len(novel)} novel static colors to {api_base}")
            except Exception as e:
                print(f"Warning: POST discoveries failed: {e}", file=sys.stderr)
        elif novel and not args.api_base:
            print("Run with --api-base to POST novel discoveries to the API.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
