#!/usr/bin/env python3
"""
Seed the five linguistic domains identified by Manus AI as missing or sparse:
composition_balance, composition_symmetry, shot, transition, audio_mood.
Also seeds theme for future narrative/theme resolution.

Run once after deploy to improve prompt interpretation. Uses POST /api/linguistic-registry/batch.
"""
from __future__ import annotations

import argparse

from src.interpretation.linguistic_client import post_linguistic_growth

# High-value synonym mappings from Manus AI enhancement report (§4 Priority 4)
# Expanded for interpreter usefulness: camera, motion axes, full audio moods, palette slang.
SEED_ITEMS: list[dict[str, str]] = [
    # composition_balance
    {"span": "balanced", "canonical": "balanced", "domain": "composition_balance", "variant_type": "synonym"},
    {"span": "centered", "canonical": "balanced", "domain": "composition_balance", "variant_type": "synonym"},
    {"span": "even", "canonical": "balanced", "domain": "composition_balance", "variant_type": "synonym"},
    {"span": "off-center", "canonical": "left_heavy", "domain": "composition_balance", "variant_type": "synonym"},
    {"span": "rule of thirds", "canonical": "balanced", "domain": "composition_balance", "variant_type": "synonym"},
    {"span": "asymmetric", "canonical": "left_heavy", "domain": "composition_balance", "variant_type": "synonym"},
    {"span": "left heavy", "canonical": "left_heavy", "domain": "composition_balance", "variant_type": "synonym"},
    {"span": "right heavy", "canonical": "right_heavy", "domain": "composition_balance", "variant_type": "synonym"},
    # composition_symmetry
    {"span": "symmetric", "canonical": "symmetric", "domain": "composition_symmetry", "variant_type": "synonym"},
    {"span": "mirror", "canonical": "symmetric", "domain": "composition_symmetry", "variant_type": "synonym"},
    {"span": "bilateral", "canonical": "bilateral", "domain": "composition_symmetry", "variant_type": "synonym"},
    {"span": "slight symmetry", "canonical": "slight", "domain": "composition_symmetry", "variant_type": "synonym"},
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
    {"span": "extreme close", "canonical": "extreme_close", "domain": "shot", "variant_type": "synonym"},
    {"span": "pov", "canonical": "pov", "domain": "shot", "variant_type": "synonym"},
    # transition
    {"span": "fade", "canonical": "fade", "domain": "transition", "variant_type": "synonym"},
    {"span": "fade in", "canonical": "fade", "domain": "transition", "variant_type": "synonym"},
    {"span": "fade out", "canonical": "fade", "domain": "transition", "variant_type": "synonym"},
    {"span": "cut", "canonical": "cut", "domain": "transition", "variant_type": "synonym"},
    {"span": "hard cut", "canonical": "cut", "domain": "transition", "variant_type": "synonym"},
    {"span": "jump cut", "canonical": "cut", "domain": "transition", "variant_type": "synonym"},
    {"span": "dissolve", "canonical": "dissolve", "domain": "transition", "variant_type": "synonym"},
    {"span": "cross dissolve", "canonical": "dissolve", "domain": "transition", "variant_type": "synonym"},
    {"span": "wipe", "canonical": "wipe", "domain": "transition", "variant_type": "synonym"},
    # audio_mood (full AUDIO_ORIGINS mood set + slang)
    {"span": "calm", "canonical": "calm", "domain": "audio_mood", "variant_type": "synonym"},
    {"span": "peaceful", "canonical": "peaceful", "domain": "audio_mood", "variant_type": "synonym"},
    {"span": "serene", "canonical": "calm", "domain": "audio_mood", "variant_type": "synonym"},
    {"span": "gentle", "canonical": "soft", "domain": "audio_mood", "variant_type": "synonym"},
    {"span": "dark", "canonical": "dark", "domain": "audio_mood", "variant_type": "synonym"},
    {"span": "moody", "canonical": "moody", "domain": "audio_mood", "variant_type": "synonym"},
    {"span": "brooding", "canonical": "dark", "domain": "audio_mood", "variant_type": "synonym"},
    {"span": "energetic", "canonical": "energetic", "domain": "audio_mood", "variant_type": "synonym"},
    {"span": "intense", "canonical": "intense", "domain": "audio_mood", "variant_type": "synonym"},
    {"span": "powerful", "canonical": "intense", "domain": "audio_mood", "variant_type": "synonym"},
    {"span": "tense", "canonical": "tense", "domain": "audio_mood", "variant_type": "synonym"},
    {"span": "uplifting", "canonical": "uplifting", "domain": "audio_mood", "variant_type": "synonym"},
    {"span": "hopeful", "canonical": "hopeful", "domain": "audio_mood", "variant_type": "synonym"},
    {"span": "ominous", "canonical": "ominous", "domain": "audio_mood", "variant_type": "synonym"},
    {"span": "melancholy", "canonical": "melancholy", "domain": "audio_mood", "variant_type": "synonym"},
    {"span": "dreamy", "canonical": "dreamy", "domain": "audio_mood", "variant_type": "synonym"},
    {"span": "playful", "canonical": "playful", "domain": "audio_mood", "variant_type": "synonym"},
    {"span": "suspenseful", "canonical": "suspenseful", "domain": "audio_mood", "variant_type": "synonym"},
    {"span": "chaotic", "canonical": "chaotic", "domain": "audio_mood", "variant_type": "synonym"},
    {"span": "harsh", "canonical": "harsh", "domain": "audio_mood", "variant_type": "synonym"},
    {"span": "soft", "canonical": "soft", "domain": "audio_mood", "variant_type": "synonym"},
    {"span": "bright", "canonical": "bright", "domain": "audio_mood", "variant_type": "synonym"},
    {"span": "dramatic", "canonical": "dramatic", "domain": "audio_mood", "variant_type": "synonym"},
    # audio_tempo / presence
    {"span": "slow tempo", "canonical": "slow", "domain": "audio_tempo", "variant_type": "synonym"},
    {"span": "fast tempo", "canonical": "fast", "domain": "audio_tempo", "variant_type": "synonym"},
    {"span": "medium tempo", "canonical": "medium", "domain": "audio_tempo", "variant_type": "synonym"},
    {"span": "silence", "canonical": "silence", "domain": "audio_presence", "variant_type": "synonym"},
    {"span": "ambient bed", "canonical": "ambient", "domain": "audio_presence", "variant_type": "synonym"},
    {"span": "full mix", "canonical": "full", "domain": "audio_presence", "variant_type": "synonym"},
    {"span": "sfx heavy", "canonical": "sfx", "domain": "audio_presence", "variant_type": "synonym"},
    # camera
    {"span": "pan", "canonical": "pan", "domain": "camera", "variant_type": "synonym"},
    {"span": "tilt", "canonical": "tilt", "domain": "camera", "variant_type": "synonym"},
    {"span": "dolly", "canonical": "dolly", "domain": "camera", "variant_type": "synonym"},
    {"span": "crane", "canonical": "crane", "domain": "camera", "variant_type": "synonym"},
    {"span": "handheld", "canonical": "handheld", "domain": "camera", "variant_type": "synonym"},
    {"span": "whip pan", "canonical": "whip_pan", "domain": "camera", "variant_type": "synonym"},
    {"span": "birds eye", "canonical": "birds_eye", "domain": "camera", "variant_type": "synonym"},
    {"span": "tracking shot", "canonical": "tracking", "domain": "camera", "variant_type": "synonym"},
    # motion
    {"span": "jerky", "canonical": "jerky", "domain": "motion", "variant_type": "synonym"},
    {"span": "fluid", "canonical": "fluid", "domain": "motion", "variant_type": "synonym"},
    {"span": "pulsing", "canonical": "pulsing", "domain": "motion", "variant_type": "synonym"},
    {"span": "ease in", "canonical": "ease_in", "domain": "motion", "variant_type": "synonym"},
    {"span": "ease out", "canonical": "ease_out", "domain": "motion", "variant_type": "synonym"},
    {"span": "radial motion", "canonical": "radial", "domain": "motion", "variant_type": "synonym"},
    {"span": "diagonal drift", "canonical": "diagonal", "domain": "motion", "variant_type": "synonym"},
    # palette / color slang (multi-sense)
    {"span": "golden hour", "canonical": "warm", "domain": "palette", "variant_type": "synonym"},
    {"span": "neon", "canonical": "magenta", "domain": "palette", "variant_type": "synonym"},
    {"span": "pastel", "canonical": "pink", "domain": "palette", "variant_type": "synonym"},
    {"span": "monochrome", "canonical": "gray", "domain": "palette", "variant_type": "synonym"},
    {"span": "teal and orange", "canonical": "teal", "domain": "palette", "variant_type": "synonym"},
    # theme
    {"span": "nature", "canonical": "nature", "domain": "theme", "variant_type": "synonym"},
    {"span": "natural", "canonical": "nature", "domain": "theme", "variant_type": "synonym"},
    {"span": "organic", "canonical": "nature", "domain": "theme", "variant_type": "synonym"},
    {"span": "urban", "canonical": "urban", "domain": "theme", "variant_type": "synonym"},
    {"span": "city", "canonical": "urban", "domain": "theme", "variant_type": "synonym"},
    {"span": "metropolitan", "canonical": "urban", "domain": "theme", "variant_type": "synonym"},
    # motion_directionality
    {"span": "drifts left", "canonical": "horizontal", "domain": "motion_directionality", "variant_type": "synonym"},
    {"span": "moves right", "canonical": "horizontal", "domain": "motion_directionality", "variant_type": "synonym"},
    {"span": "goes up", "canonical": "vertical", "domain": "motion_directionality", "variant_type": "synonym"},
    {"span": "falls down", "canonical": "vertical", "domain": "motion_directionality", "variant_type": "synonym"},
    {"span": "diagonal drift", "canonical": "diagonal", "domain": "motion_directionality", "variant_type": "synonym"},
    {"span": "radiates out", "canonical": "radial", "domain": "motion_directionality", "variant_type": "synonym"},
    # audio_genre
    {"span": "deep house", "canonical": "deep_house", "domain": "audio_genre", "variant_type": "synonym"},
    {"span": "house music", "canonical": "deep_house", "domain": "audio_genre", "variant_type": "synonym"},
    {"span": "techno beat", "canonical": "techno", "domain": "audio_genre", "variant_type": "synonym"},
    {"span": "ambient pad", "canonical": "ambient", "domain": "audio_genre", "variant_type": "synonym"},
    # sfx
    {"span": "bouncing", "canonical": "bounce", "domain": "sfx", "variant_type": "synonym"},
    {"span": "ball bounce", "canonical": "bounce", "domain": "sfx", "variant_type": "synonym"},
    {"span": "impact hit", "canonical": "impact", "domain": "sfx", "variant_type": "synonym"},
    {"span": "whoosh by", "canonical": "whoosh", "domain": "sfx", "variant_type": "synonym"},
    # entity
    {"span": "red ball", "canonical": "circle", "domain": "entity", "variant_type": "synonym"},
    {"span": "bouncing ball", "canonical": "circle", "domain": "entity", "variant_type": "synonym"},
    {"span": "a person", "canonical": "character", "domain": "entity", "variant_type": "synonym"},
    {"span": "silhouette figure", "canonical": "character", "domain": "entity", "variant_type": "synonym"},
    # expression
    {"span": "happy face", "canonical": "happy", "domain": "expression", "variant_type": "synonym"},
    {"span": "smiling person", "canonical": "happy", "domain": "expression", "variant_type": "synonym"},
    {"span": "sad mood", "canonical": "sad", "domain": "expression", "variant_type": "synonym"},
    {"span": "angry look", "canonical": "angry", "domain": "expression", "variant_type": "synonym"},
    {"span": "calm expression", "canonical": "calm", "domain": "expression", "variant_type": "synonym"},
    # personality
    {"span": "playful character", "canonical": "playful", "domain": "personality", "variant_type": "synonym"},
    {"span": "shy figure", "canonical": "shy", "domain": "personality", "variant_type": "synonym"},
    {"span": "energetic walk", "canonical": "energetic", "domain": "personality", "variant_type": "synonym"},
    {"span": "confident stride", "canonical": "confident", "domain": "personality", "variant_type": "synonym"},
    # gag / entertainment
    {"span": "double take", "canonical": "double_take", "domain": "motion", "variant_type": "phrase"},
    {"span": "winks", "canonical": "wink", "domain": "expression", "variant_type": "synonym"},
    {"span": "spin flourish", "canonical": "spin", "domain": "motion", "variant_type": "phrase"},
    {"span": "squash bounce", "canonical": "bounce", "domain": "sfx", "variant_type": "phrase"},
    {"span": "then bounces", "canonical": "bounce", "domain": "sfx", "variant_type": "phrase"},
    {"span": "walks in", "canonical": "toward", "domain": "motion_directionality", "variant_type": "phrase"},
    {"span": "exits right", "canonical": "right", "domain": "motion_directionality", "variant_type": "phrase"},
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

    result = post_linguistic_growth(api_base, SEED_ITEMS)
    print(f"Linguistic seed: inserted={result.get('inserted', 0)}, updated={result.get('updated', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
