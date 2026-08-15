#!/usr/bin/env python3
"""
Measure a local clip you have rights to into the registries.

Extracts colors / sounds / motion windows. Does not become the loop's
starting picture and is not replayed as video frames.

Usage:
  python scripts/ingest_reference.py path/to/clip.mp4 --api-base https://motion.productions
  python scripts/ingest_reference.py path/to/clip.mp4 --max-frames 72
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
        description="Measure a reference video into the registries (not used as a render start)."
    )
    parser.add_argument("video", nargs="?", default="", help="Path to an MP4 you have rights to")
    parser.add_argument("--loop", default="main", help="Label for the measurement recipe file")
    parser.add_argument("--api-base", default=None, help="POST discoveries to this API (D1)")
    parser.add_argument("--local-only", action="store_true", help="Grow local registries only; skip API")
    parser.add_argument("--max-frames", type=int, default=72, help="Sample this many frames across the clip")
    parser.add_argument(
        "--recipe-only",
        action="store_true",
        help="Re-measure palette/field/timing only; skip registry growth and API",
    )
    parser.add_argument(
        "--objects-only",
        action="store_true",
        help="Import silhouette meshes from an existing loop origin field (no video re-read)",
    )
    args = parser.parse_args()

    if args.objects_only:
        from src.photoreal.origin_objects import extract_and_store_origin_objects
        objects = extract_and_store_origin_objects(args.loop)
        print(json.dumps({
            "loop": args.loop,
            "object_count": len(objects),
            "objects": [
                {k: v for k, v in obj.items() if k != "mesh_obj"}
                for obj in objects
            ],
        }, indent=2))
        return 0

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
        recipe_only=bool(args.recipe_only),
    )
    skip = {"growth_added", "field"}
    print(json.dumps({k: recipe[k] for k in recipe if k not in skip}, indent=2))
    field = recipe.get("field") or {}
    if field:
        print(
            "field:",
            field.get("width"),
            "x",
            field.get("height"),
            "x",
            len(field.get("frames") or []),
            "indexed samples",
        )
    added = recipe.get("growth_added") or {}
    if added:
        print("growth:", added)
    print("saved:", recipe.get("saved_to"))
    if recipe.get("synced"):
        print("synced discoveries to", api_base)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
