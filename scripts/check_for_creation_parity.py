#!/usr/bin/env python3
"""
Assert for-creation static_colors are diversified across hue families
(rough parity with explorer browse / mission facets).

Usage:
  python scripts/check_for_creation_parity.py --api-base https://motion.productions
  python scripts/check_for_creation_parity.py --min-families 8 --max-share 0.35
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def main() -> int:
    parser = argparse.ArgumentParser(description="Check for-creation vs explorer family diversity.")
    parser.add_argument("--api-base", default=os.environ.get("API_BASE", "https://motion.productions"))
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--min-families", type=int, default=8, help="Min distinct families in for-creation sample")
    parser.add_argument("--max-share", type=float, default=0.40, help="Max fraction any single family may own")
    args = parser.parse_args()
    api_base = args.api_base.rstrip("/")

    from src.api_client import api_get

    fc = api_get(api_base, f"/api/knowledge/for-creation?limit={args.limit}")
    mission = api_get(api_base, "/api/registries/mission")
    colors = fc.get("static_colors") or {}
    if not colors:
        print("FAIL: for-creation returned no static_colors")
        return 1

    fams = Counter()
    for _k, v in colors.items():
        if not isinstance(v, dict):
            continue
        fam = v.get("family")
        if not fam:
            from src.knowledge.mission_targets import classify_color_family_rgb
            fam = classify_color_family_rgb(float(v.get("r", 0)), float(v.get("g", 0)), float(v.get("b", 0)))
        fams[str(fam)] += 1

    n = sum(fams.values())
    share = {k: v / n for k, v in fams.items()} if n else {}
    max_share = max(share.values()) if share else 1.0
    mission_filled = (mission.get("colors") or {}).get("families_filled") or 0

    print(f"for-creation colors: {n}")
    print(f"families present: {len(fams)} -> {dict(fams)}")
    print(f"max family share: {max_share:.2%}")
    print(f"mission families_filled: {mission_filled}")

    ok = True
    if len(fams) < args.min_families:
        print(f"FAIL: need >= {args.min_families} families, got {len(fams)}")
        ok = False
    if max_share > args.max_share:
        print(f"FAIL: max share {max_share:.2%} > {args.max_share:.0%}")
        ok = False
    if ok:
        print("OK: for-creation family diversity within bands")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
