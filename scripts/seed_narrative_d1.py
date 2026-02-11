#!/usr/bin/env python3
"""
Seed narrative D1 registry with all primitive values from NARRATIVE_ORIGINS.
Idempotent: existing entries get count incremented. Run once after deploy.

Usage:
  python scripts/seed_narrative_d1.py
  python scripts/seed_narrative_d1.py --api-base https://motion.productions
"""
import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed narrative D1 with origin primitives.")
    parser.add_argument(
        "--api-base",
        default=os.environ.get("API_BASE", "https://motion.productions"),
        help="API base URL",
    )
    args = parser.parse_args()
    api_base = args.api_base.rstrip("/")

    from src.knowledge.origins import NARRATIVE_ORIGINS

    # Map origin keys to narrative aspects (same as ensure_narrative_primitives_seeded)
    aspect_map = {
        "genre": "genre",
        "tone": "mood",
        "style": "style",
        "tension_curve": "plots",
        "settings": "settings",
        "themes": "themes",
        "scene_type": "scene_type",
    }
    narrative: dict[str, list[dict[str, str]]] = {}
    for origin_key, aspect in aspect_map.items():
        values = NARRATIVE_ORIGINS.get(origin_key, [])
        for v in values:
            if isinstance(v, str):
                narrative.setdefault(aspect, []).append({
                    "key": v.strip().lower(),
                    "value": v.strip(),
                    "source_prompt": "seed",
                })

    from src.api_client import api_request_with_retry

    payload = {"narrative": narrative}
    try:
        resp = api_request_with_retry(api_base, "POST", "/api/knowledge/discoveries", data=payload, timeout=60)
        total = sum(r for r in resp.get("results", {}).values() if isinstance(r, int))
        print(f"Seeded {total} narrative entries across {len(narrative)} aspects.")
    except Exception as e:
        print(f"Failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
