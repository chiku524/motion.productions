#!/usr/bin/env python3
"""
Accelerate static color coverage by registering a grid of (r,g,b[,opacity]) cells
without the full prompt→render pipeline. Optionally POSTs novel discoveries to the API.

Optimized for large grids: loads the local color registry once, tracks keys in a set,
and writes the JSON at most once at the end (avoids O(n²) full-file rewrites).

Usage:
  python scripts/color_sweep.py --api-base https://motion.productions
  python scripts/color_sweep.py --steps 11 --opacity-steps 5 --limit 5000 --api-base https://motion.productions
  python scripts/color_sweep.py --steps 6 --dry-run
  python scripts/color_sweep.py --api-only --api-base https://motion.productions --limit 2000
"""
from __future__ import annotations

import argparse
import sys
import time

from src.config import load_config
from src.knowledge.blend_depth import compute_color_depth
from src.knowledge.blend_names import generate_sensible_name
from src.knowledge.growth_per_instance import _static_color_key, ensure_static_primitives_seeded
from src.knowledge.remote_sync import DISCOVERIES_MAX_ITEMS, post_static_discoveries
from src.knowledge.static_registry import load_static_registry, save_static_registry


def _build_grid(steps: int, opacity_steps: int, limit: int | None) -> list[tuple[int, int, int, float]]:
    step = max(1, min(256, steps))
    if step == 1:
        values = [0, 255]
    else:
        values = sorted(set(min(255, int(round(i * 255 / (step - 1)))) for i in range(step)))

    op_steps = max(1, min(21, opacity_steps))
    if op_steps == 1:
        opacities = [1.0]
    else:
        opacities = [round(i / (op_steps - 1), 4) for i in range(op_steps)]

    grid = [(r, g, b, op) for op in opacities for r in values for g in values for b in values]
    if limit is not None:
        grid = grid[:limit]
    return grid


def main() -> int:
    # Line-buffer stdout so long sweeps show progress under tee/pipes.
    try:
        sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    except Exception:
        pass

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
        "--offset",
        type=int,
        default=0,
        help="Skip the first N grid cells (resume denser passes without re-scanning early cells).",
    )
    parser.add_argument(
        "--post-chunk-pause",
        type=float,
        default=1.0,
        help="Seconds between discovery POST chunks (default 1.0).",
    )
    parser.add_argument(
        "--api-only",
        action="store_true",
        help="Do not update local JSON registry; only build payloads and POST to API.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print grid size and first few cells; do not register or POST",
    )
    args = parser.parse_args()

    grid = _build_grid(args.steps, args.opacity_steps, None)
    offset = max(0, int(args.offset or 0))
    if offset:
        grid = grid[offset:]
    if args.limit is not None:
        grid = grid[: args.limit]
    total = len(grid)

    if args.dry_run:
        print(f"Would process {total} cells (steps={args.steps}, opacity_steps={args.opacity_steps}, offset={offset})")
        for cell in grid[:5]:
            print(f"  {cell}")
        return 0

    config = load_config()
    if not args.api_only:
        print("Seeding static primitives (once)...")
        ensure_static_primitives_seeded(config)

    existing_keys: set[str] = set()
    data: dict = {"entries": [], "count": 0}
    names: set[str] = set()
    if not args.api_only:
        print("Loading local color registry once...")
        data = load_static_registry("color", config)
        entries = data.get("entries") or []
        existing_keys = {str(e.get("key") or "") for e in entries if e.get("key")}
        names = {str(e.get("name") or "") for e in entries if e.get("name")}
        print(f"  local keys: {len(existing_keys)}")

    novel: list[dict] = []
    added = 0
    t0 = time.time()
    for i, (r, g, b, opacity) in enumerate(grid):
        color = {"r": r, "g": g, "b": b, "opacity": opacity}
        key = _static_color_key(color)
        if not key or key in existing_keys:
            if (i + 1) % 500 == 0:
                elapsed = time.time() - t0
                print(f"  ... {i + 1}/{total} (added so far: {added}, {elapsed:.0f}s)")
            continue

        r_val = float(r)
        g_val = float(g)
        b_val = float(b)
        opacity_val = float(opacity)
        name = generate_sensible_name("color", key, existing_names=names, rgb_hint=(r_val, g_val, b_val))
        names.add(name)
        origin_colors = compute_color_depth(r_val, g_val, b_val)
        depth_breakdown = {
            **{k: round(v * 100) for k, v in origin_colors.items()},
            "opacity": round(opacity_val * 100),
        }
        entry = {
            "key": key,
            "r": round(r_val, 1),
            "g": round(g_val, 1),
            "b": round(b_val, 1),
            "opacity": round(opacity_val, 2),
            "name": name,
            "count": 1,
            "sources": ["color_sweep"],
            "depth_breakdown": depth_breakdown,
        }
        if not args.api_only:
            data.setdefault("entries", []).append(entry)
        existing_keys.add(key)
        novel.append({
            "key": key,
            "r": entry["r"],
            "g": entry["g"],
            "b": entry["b"],
            "opacity": entry["opacity"],
            "depth_breakdown": depth_breakdown,
            "source_prompt": "color_sweep",
            "name": name,
        })
        added += 1
        if (i + 1) % 500 == 0:
            elapsed = time.time() - t0
            print(f"  ... {i + 1}/{total} (added so far: {added}, {elapsed:.0f}s)")

    if not args.api_only and added:
        data["count"] = len(data.get("entries") or [])
        print(f"Saving local registry ({data['count']} entries)...")
        save_static_registry("color", data, config)

    print(f"Color sweep: {added} new cells (processed {total} in {time.time() - t0:.0f}s).")
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
