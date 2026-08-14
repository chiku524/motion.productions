#!/usr/bin/env python3
"""
Seed a specialized loop from a reference video.

Reads a local clip you have rights to (your own render, CC0, public domain),
extracts colors / sounds / motion windows into the registries, and writes a
loop-origin recipe (palette + hold/snap timing). The source MP4 is not copied
into the library and is not replayed.

Usage:
  python scripts/ingest_reference.py path/to/clip.mp4 --loop cartoon
  python scripts/ingest_reference.py path/to/clip.mp4 --loop cartoon --api-base https://motion.productions
  python scripts/ingest_reference.py path/to/clip.mp4 --loop cartoon --max-frames 72

Drop convention: references/cartoon.mp4
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ingest a reference video as a loop origin (measurements + registry growth)."
    )
    parser.add_argument("video", nargs="?", default="", help="Path to an MP4 you have rights to")
    parser.add_argument("--loop", default="cartoon", help="Loop name (default cartoon)")
    parser.add_argument("--api-base", default=None, help="POST discoveries to this API (D1)")
    parser.add_argument("--local-only", action="store_true", help="Grow local registries only; skip API")
    parser.add_argument("--max-frames", type=int, default=72, help="Sample this many frames across the clip")
    args = parser.parse_args()

    video = Path(args.video) if args.video else REPO_ROOT / "references" / f"{args.loop}.mp4"
    if not video.is_file():
        print(
            f"No reference clip at {video}. Pass a path, or place a clip at references/{args.loop}.mp4.\n"
            "Use a file you have rights to. This extracts specs (colors, timing); it does not copy the show.",
            file=sys.stderr,
        )
        return 2

    api_base = None if args.local_only else (args.api_base or os.environ.get("API_BASE") or "").rstrip("/")
    from src.config import load_config
    from src.knowledge.reference_origin import ingest_reference_video

    recipe = ingest_reference_video(
        video,
        loop=args.loop,
        api_base=api_base or None,
        config=load_config(),
        max_frames=max(8, int(args.max_frames)),
    )
    print(json.dumps({k: recipe[k] for k in recipe if k != "growth_added"}, indent=2))
    added = recipe.get("growth_added") or {}
    if added:
        print("growth:", added)
    print("saved:", recipe.get("saved_to"))
    if recipe.get("synced"):
        print("synced discoveries to", api_base)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
