#!/usr/bin/env python3
"""
Reconcile local 11×11×11×21 color grid against D1 by posting only missing keys.

Fetches color_key pages via wrangler (LIMIT/OFFSET), diffs against the local
grid, then POSTs novel cells through /api/knowledge/discoveries.

Usage:
  python scripts/reconcile_static_colors.py --api-base https://motion.productions
  python scripts/reconcile_static_colors.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.color_sweep import _build_grid
from src.knowledge.blend_depth import compute_color_depth
from src.knowledge.blend_names import generate_sensible_name
from src.knowledge.growth_per_instance import _static_color_key
from src.knowledge.remote_sync import DISCOVERIES_MAX_ITEMS, post_static_discoveries


def _wrangler_keys(*, after: str | None, limit: int) -> list[str]:
    if after is None:
        sql = f"SELECT color_key FROM static_colors ORDER BY color_key LIMIT {limit};"
    else:
        safe = after.replace("'", "''")
        sql = (
            f"SELECT color_key FROM static_colors WHERE color_key > '{safe}' "
            f"ORDER BY color_key LIMIT {limit};"
        )
    npx = shutil.which("npx") or shutil.which("npx.cmd") or "npx"
    # Windows: npx is a .cmd shim; shell=True is required for CreateProcess to find it.
    use_shell = os.name == "nt"
    cmd = [npx, "wrangler", "d1", "execute", "motion-productions-db", "--remote", "--json", "--command", sql]
    proc = subprocess.run(
        cmd if not use_shell else subprocess.list2cmdline(cmd),
        cwd=str(ROOT / "cloudflare"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=use_shell,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"wrangler failed (after={after!r}): {proc.stderr[-500:] or proc.stdout[-500:]}")
    data = json.loads(proc.stdout)
    rows = data[0].get("results") or []
    return [str(r["color_key"]) for r in rows if r.get("color_key")]


def fetch_all_d1_keys(*, page: int = 1500, pause: float = 1.5) -> set[str]:
    keys: set[str] = set()
    after: str | None = None
    while True:
        batch = _wrangler_keys(after=after, limit=page)
        if not batch:
            break
        keys.update(batch)
        after = batch[-1]
        print(f"  D1 keys fetched: {len(keys)} (after={after!r})", flush=True)
        if len(batch) < page:
            break
        time.sleep(pause)
    return keys


def main() -> int:
    parser = argparse.ArgumentParser(description="Post only static color cells missing from D1.")
    parser.add_argument("--api-base", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--page", type=int, default=2000)
    parser.add_argument("--post-chunk-pause", type=float, default=3.5)
    parser.add_argument("--limit", type=int, default=None, help="Max missing cells to POST")
    args = parser.parse_args()

    print("Building local grid keys...")
    grid = _build_grid(11, 21, None)
    local: dict[str, tuple[int, int, int, float]] = {}
    for r, g, b, op in grid:
        key = _static_color_key({"r": r, "g": g, "b": b, "opacity": op})
        local[key] = (r, g, b, op)
    print(f"  local grid: {len(local)}")

    print("Fetching D1 color_keys...")
    d1_keys = fetch_all_d1_keys(page=max(100, args.page))
    print(f"  D1 keys: {len(d1_keys)}")

    missing_keys = [k for k in local if k not in d1_keys]
    print(f"  missing on D1: {len(missing_keys)}")
    if args.limit is not None:
        missing_keys = missing_keys[: args.limit]
        print(f"  posting up to limit: {len(missing_keys)}")

    if args.dry_run:
        for k in missing_keys[:10]:
            print(f"  would post {k} -> {local[k]}")
        return 0

    if not args.api_base:
        print("--api-base required unless --dry-run", file=sys.stderr)
        return 2

    names: set[str] = set()
    novel: list[dict] = []
    for key in missing_keys:
        r, g, b, opacity = local[key]
        r_val, g_val, b_val = float(r), float(g), float(b)
        name = generate_sensible_name("color", key, existing_names=names, rgb_hint=(r_val, g_val, b_val))
        names.add(name)
        origin_colors = compute_color_depth(r_val, g_val, b_val)
        depth_breakdown = {
            **{k: round(v * 100) for k, v in origin_colors.items()},
            "opacity": round(float(opacity) * 100),
        }
        novel.append({
            "key": key,
            "r": round(r_val, 1),
            "g": round(g_val, 1),
            "b": round(b_val, 1),
            "opacity": round(float(opacity), 2),
            "depth_breakdown": depth_breakdown,
            "source_prompt": "color_reconcile",
            "name": name,
        })

    posted = 0
    chunk = max(1, DISCOVERIES_MAX_ITEMS)
    pause = max(0.0, float(args.post_chunk_pause))
    api_base = args.api_base.rstrip("/")
    for i in range(0, len(novel), chunk):
        batch = novel[i : i + chunk]
        try:
            post_static_discoveries(api_base, batch, [], job_id=None)
            posted += len(batch)
            print(f"  posted {posted}/{len(novel)}", flush=True)
        except Exception as e:
            print(f"Warning: POST failed at {posted}: {e}", file=sys.stderr)
            time.sleep(max(pause, 5.0))
            try:
                post_static_discoveries(api_base, batch, [], job_id=None)
                posted += len(batch)
                print(f"  posted {posted}/{len(novel)} (retry ok)", flush=True)
            except Exception as e2:
                print(f"Warning: retry failed: {e2}", file=sys.stderr)
                break
        if pause and i + chunk < len(novel):
            time.sleep(pause)
    print(f"Reconcile done: posted {posted}/{len(novel)} missing cells to {api_base}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
