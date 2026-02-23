#!/usr/bin/env python3
"""
Seed the five linguistic domains identified by Manus AI as missing or sparse:
composition_balance, composition_symmetry, shot, transition, audio_mood.
Also seeds theme for future narrative/theme resolution.

Run once after deploy to improve prompt interpretation. Uses POST /api/linguistic-registry/batch.
"""
from __future__ import annotations

import argparse
import sys

# High-value synonym mappings from Manus AI enhancement report (§4 Priority 4)
SEED_ITEMS: list[dict[str, str]] = [
    # composition_balance
    {"span": "balanced", "canonical": "balanced", "domain": "composition_balance", "variant_type": "synonym"},
    {"span": "centered", "canonical": "balanced", "domain": "composition_balance", "variant_type": "synonym"},
    {"span": "even", "canonical": "balanced", "domain": "composition_balance", "variant_type": "synonym"},
    {"span": "off-center", "canonical": "left_heavy", "domain": "composition_balance", "variant_type": "synonym"},
    {"span": "rule of thirds", "canonical": "balanced", "domain": "composition_balance", "variant_type": "synonym"},
    {"span": "asymmetric", "canonical": "left_heavy", "domain": "composition_balance", "variant_type": "synonym"},
    # composition_symmetry
    {"span": "symmetric", "canonical": "symmetric", "domain": "composition_symmetry", "variant_type": "synonym"},
    {"span": "mirror", "canonical": "symmetric", "domain": "composition_symmetry", "variant_type": "synonym"},
    # shot
    {"span": "close", "canonical": "close", "domain": "shot", "variant_type": "synonym"},
    {"span": "closeup", "canonical": "close", "domain": "shot", "variant_type": "synonym"},
    {"span": "detail", "canonical": "close", "domain": "shot", "variant_type": "synonym"},
    {"span": "wide", "canonical": "wide", "domain": "shot", "variant_type": "synonym"},
    {"span": "establishing", "canonical": "wide", "domain": "shot", "variant_type": "synonym"},
    {"span": "landscape", "canonical": "wide", "domain": "shot", "variant_type": "synonym"},
    {"span": "medium", "canonical": "medium", "domain": "shot", "variant_type": "synonym"},
    {"span": "mid-shot", "canonical": "medium", "domain": "shot", "variant_type": "synonym"},
    {"span": "waist", "canonical": "medium", "domain": "shot", "variant_type": "synonym"},
    # transition
    {"span": "fade", "canonical": "fade", "domain": "transition", "variant_type": "synonym"},
    {"span": "fade in", "canonical": "fade", "domain": "transition", "variant_type": "synonym"},
    {"span": "fade out", "canonical": "fade", "domain": "transition", "variant_type": "synonym"},
    {"span": "cut", "canonical": "cut", "domain": "transition", "variant_type": "synonym"},
    {"span": "hard cut", "canonical": "cut", "domain": "transition", "variant_type": "synonym"},
    {"span": "jump cut", "canonical": "cut", "domain": "transition", "variant_type": "synonym"},
    {"span": "dissolve", "canonical": "dissolve", "domain": "transition", "variant_type": "synonym"},
    {"span": "cross dissolve", "canonical": "dissolve", "domain": "transition", "variant_type": "synonym"},
    # audio_mood (mood)
    {"span": "calm", "canonical": "calm", "domain": "audio_mood", "variant_type": "synonym"},
    {"span": "peaceful", "canonical": "calm", "domain": "audio_mood", "variant_type": "synonym"},
    {"span": "serene", "canonical": "calm", "domain": "audio_mood", "variant_type": "synonym"},
    {"span": "gentle", "canonical": "calm", "domain": "audio_mood", "variant_type": "synonym"},
    {"span": "dark", "canonical": "dark", "domain": "audio_mood", "variant_type": "synonym"},
    {"span": "moody", "canonical": "dark", "domain": "audio_mood", "variant_type": "synonym"},
    {"span": "brooding", "canonical": "dark", "domain": "audio_mood", "variant_type": "synonym"},
    {"span": "energetic", "canonical": "energetic", "domain": "audio_mood", "variant_type": "synonym"},
    {"span": "intense", "canonical": "energetic", "domain": "audio_mood", "variant_type": "synonym"},
    {"span": "powerful", "canonical": "energetic", "domain": "audio_mood", "variant_type": "synonym"},
    # theme (for future narrative/theme resolution)
    {"span": "nature", "canonical": "nature", "domain": "theme", "variant_type": "synonym"},
    {"span": "natural", "canonical": "nature", "domain": "theme", "variant_type": "synonym"},
    {"span": "organic", "canonical": "nature", "domain": "theme", "variant_type": "synonym"},
    {"span": "urban", "canonical": "urban", "domain": "theme", "variant_type": "synonym"},
    {"span": "city", "canonical": "urban", "domain": "theme", "variant_type": "synonym"},
    {"span": "metropolitan", "canonical": "urban", "domain": "theme", "variant_type": "synonym"},
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed linguistic registry with Manus AI suggested domains.")
    parser.add_argument("--api-base", default=None, help="API base URL (e.g. https://motion.productions); required unless --dry-run")
    parser.add_argument("--dry-run", action="store_true", help="Print items that would be sent, do not POST")
    args = parser.parse_args()
    if not args.dry_run and not args.api_base:
        parser.error("--api-base is required unless --dry-run")
    api_base = args.api_base.rstrip("/") if args.api_base else ""

    if args.dry_run:
        domains = set(i["domain"] for i in SEED_ITEMS)
        print(f"Would POST {len(SEED_ITEMS)} items across domains: {sorted(domains)}")
        for i in SEED_ITEMS:
            print(f"  {i['domain']}: {i['span']!r} -> {i['canonical']!r}")
        return 0

    try:
        from src.interpretation.linguistic_client import post_linguistic_growth
    except ImportError:
        sys.path.insert(0, ".")
        from src.interpretation.linguistic_client import post_linguistic_growth

    result = post_linguistic_growth(api_base, SEED_ITEMS)
    print(f"Linguistic seed: inserted={result.get('inserted', 0)}, updated={result.get('updated', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
