#!/usr/bin/env python3
"""
Fill missing pure-sound origin brackets (mission / explorer findability).

Posts one canonical static_sound discovery per missing origin with
depth_breakdown.origin_noises dominated by that primitive (unique keys),
so GET /api/registries/browse?kind=static_sound facets update.

Usage:
  python scripts/sound_origin_sweep.py --api-base https://motion.productions
  python scripts/sound_origin_sweep.py --dry-run
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

logger = logging.getLogger(__name__)

# Distinct keys so D1 inserts novel rows (not count-bumps on silence-heavy blends)
_PRIMITIVE_PAYLOADS: dict[str, dict] = {
    "silence": {"amplitude": 0.0, "tone": "silent", "timbre": "silence"},
    "rumble": {"amplitude": 0.55, "tone": "low", "timbre": "rumble"},
    "hum": {"amplitude": 0.45, "tone": "low", "timbre": "hum"},
    "tone": {"amplitude": 0.5, "tone": "mid", "timbre": "tone"},
    "hiss": {"amplitude": 0.4, "tone": "high", "timbre": "hiss"},
    "rustle": {"amplitude": 0.35, "tone": "mid", "timbre": "rustle"},
    "thump": {"amplitude": 0.6, "tone": "low", "timbre": "thump"},
    "click": {"amplitude": 0.3, "tone": "high", "timbre": "click"},
    "whoosh": {"amplitude": 0.5, "tone": "mid", "timbre": "whoosh"},
    "drip": {"amplitude": 0.25, "tone": "mid", "timbre": "drip"},
}


def _payload_for(primitive: str, *, nonce: str = "") -> dict:
    base = dict(_PRIMITIVE_PAYLOADS.get(primitive) or {"amplitude": 0.4, "tone": "mid", "timbre": primitive})
    amp = float(base["amplitude"])
    # Unique key every run. Avoid underscore amp_tone_timbre shape — Worker sanitizePureSoundKey rewrites those.
    suffix = nonce or "v1"
    key = f"originfill:{primitive}:{suffix}"
    return {
        "key": key,
        "amplitude": amp,
        "weight": amp,
        "strength_pct": amp if amp <= 1 else amp / 100.0,
        "tone": base["tone"],
        "timbre": base["timbre"],
        "name": primitive[:1].upper() + primitive[1:] + " Origin",
        "source_prompt": f"sound_origin_sweep:{primitive}",
        "depth_breakdown": {
            "origin_noises": {primitive: 1.0},
            "amplitude": amp,
            "strength_pct": amp * 100 if amp <= 1 else amp,
        },
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description="Fill missing sound origin brackets in D1.")
    parser.add_argument("--api-base", default=os.environ.get("API_BASE", "https://motion.productions"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--include-silence", action="store_true")
    parser.add_argument("--all", action="store_true", help="Post all origins even if present")
    args = parser.parse_args()
    api_base = (args.api_base or "").rstrip("/")
    if not api_base:
        print("Provide --api-base", file=sys.stderr)
        return 2

    from src.knowledge.blend_depth import SOUND_ORIGIN_PRIMITIVES
    from src.knowledge.mission_targets import fetch_mission, missing_sound_origins
    from src.knowledge.remote_sync import post_static_discoveries

    mission = fetch_mission(api_base)
    if args.all:
        missing = list(SOUND_ORIGIN_PRIMITIVES)
    else:
        missing = missing_sound_origins(mission)
    if not args.include_silence and not args.all:
        missing = [m for m in missing if m != "silence"]
    if not missing:
        print("All sound origins present — nothing to sweep.")
        if mission:
            print("Present:", (mission.get("sound") or {}).get("origins_present"))
        return 0

    nonce = str(int(time.time()))
    payloads = [_payload_for(p, nonce=nonce) for p in missing]
    print(f"Posting {len(payloads)} origin fills: {', '.join(missing)}")
    if args.dry_run:
        for p in payloads:
            print(f"  dry-run {p['key']} -> {list((p['depth_breakdown'].get('origin_noises') or {}).keys())}")
        return 0

    resp = post_static_discoveries(api_base, [], payloads, job_id=None)
    print("D1 results:", resp.get("results") or resp)
    mission2 = fetch_mission(api_base)
    print("origins_present now:", (mission2 or {}).get("sound", {}).get("origins_present"))
    print("findability:", (mission2 or {}).get("findability_pct"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
