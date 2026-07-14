#!/usr/bin/env python3
"""
Unified primitive reseed: local JSON + D1.

Seeds Pure (colors/sounds), Blended (dynamic origins), Semantic (narrative),
and Interpretation linguistics — then POSTs discovery payloads so D1 matches.

Safe to re-run (idempotent). Prefer after wipe_registry_tables.py.
See docs/REGISTRY_RESET.md.

Usage:
  python scripts/seed_registries_d1.py --local-only
  python scripts/seed_registries_d1.py --api-base https://motion.productions
  python scripts/seed_registries_d1.py --reset-local --api-base https://motion.productions
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _reset_local_knowledge(config: dict) -> None:
    from src.knowledge.registry import get_registry_dir
    root = get_registry_dir(config)
    if root.exists():
        print(f"Clearing local registry cache: {root}")
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "static").mkdir(exist_ok=True)
    (root / "dynamic").mkdir(exist_ok=True)
    (root / "narrative").mkdir(exist_ok=True)


def _seed_linguistic(api_base: str) -> None:
    from src.interpretation.linguistic_client import post_linguistic_growth
    path = REPO_ROOT / "scripts" / "seed_linguistic_domains.py"
    spec = importlib.util.spec_from_file_location("seed_linguistic_domains", path)
    if not spec or not spec.loader:
        raise RuntimeError("Cannot load seed_linguistic_domains.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    items = getattr(mod, "SEED_ITEMS", [])
    if not items:
        print("  no SEED_ITEMS found")
        return
    post_linguistic_growth(api_base, items)
    print(f"  linguistic mappings posted: {len(items)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed all registry primitives locally and to D1.")
    parser.add_argument("--api-base", default=None, help="API base URL")
    parser.add_argument("--local-only", action="store_true", help="Seed local JSON only")
    parser.add_argument("--reset-local", action="store_true", help="Clear local knowledge/ before seed")
    parser.add_argument("--skip-linguistic", action="store_true")
    parser.add_argument("--skip-static", action="store_true")
    parser.add_argument("--skip-dynamic", action="store_true")
    parser.add_argument("--skip-narrative", action="store_true")
    args = parser.parse_args()

    api_base = (args.api_base or os.environ.get("API_BASE") or "").rstrip("/")
    if not args.local_only and not api_base:
        print("Provide --api-base or --local-only", file=sys.stderr)
        return 2

    from src.config import load_config
    from src.knowledge.growth_per_instance import (
        ensure_dynamic_primitives_seeded,
        ensure_static_primitives_seeded,
    )
    from src.knowledge.narrative_registry import ensure_narrative_primitives_seeded
    from src.knowledge.remote_sync import post_all_discoveries

    config = load_config()
    if args.reset_local:
        _reset_local_knowledge(config)

    static_colors: list = []
    static_sound: list = []
    dynamic_novel: dict[str, list] = {}
    narrative_novel: dict[str, list] = {}
    force = True

    if not args.skip_static:
        print("Seeding static primitives (colors + sounds)...")
        ensure_static_primitives_seeded(
            config, out_colors=static_colors, out_sounds=static_sound, force_novel=force
        )
        print(f"  static_colors payloads: {len(static_colors)}")
        print(f"  static_sound payloads: {len(static_sound)}")

    if not args.skip_dynamic:
        print("Seeding dynamic primitives (full origin grids)...")
        counts = ensure_dynamic_primitives_seeded(
            config, novel_for_sync=dynamic_novel, force_novel=force
        )
        for k, v in sorted(dynamic_novel.items()):
            print(f"  {k}: {len(v)} payloads (new local: {counts.get(k, 0)})")

    if not args.skip_narrative:
        print("Seeding narrative primitives...")
        added = ensure_narrative_primitives_seeded(
            config, out_novel=narrative_novel, force_novel=force
        )
        total_n = sum(len(v) for v in narrative_novel.values())
        print(f"  narrative payloads: {total_n} (new local: {added})")

    if args.local_only:
        print("Local seed complete (--local-only).")
        return 0

    print(f"Posting primitives to {api_base} ...")
    try:
        resp = post_all_discoveries(
            api_base,
            static_colors,
            static_sound,
            dynamic_novel,
            narrative_novel,
            job_id=None,
        )
        print("D1 results:", resp.get("results") or {})
    except Exception as e:
        print(f"POST discoveries failed: {e}", file=sys.stderr)
        return 1

    if not args.skip_linguistic:
        print("Seeding linguistic domains...")
        try:
            _seed_linguistic(api_base)
        except Exception as e:
            print(f"  linguistic seed failed: {e}", file=sys.stderr)

    print("Primitive reseed complete. See docs/REGISTRY_RESET.md for verify + Docker restart.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
